import uuid
import os
from collections import defaultdict
from django.db import models, connection, transaction, DatabaseError
from django.conf import settings as SETTINGS
from django.contrib import admin
from django.utils.datastructures import SortedDict
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

AUDIT_SCHEMA_NAME = "_version"

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **kwargs):
        if not email:
            raise ValueError('Users must have an email address')

        user = self.model(email=self.normalize_email(email), **kwargs)

        user.set_password(password)
        user.save(using=self._db)
        return user

class User(AbstractBaseUser, PermissionsMixin):
    id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, blank=True)
    is_staff = models.BooleanField(default=False, blank=True)

    USERNAME_FIELD = 'email'

    objects = UserManager()

    class Meta:
        db_table = "auth_user"

    def get_short_name(self):
        return self.email

#admin.site.register(User)

class ColumnTypes:
    """An enum for column types"""
    INTEGER = 1
    NUMERIC = 2
    TIMESTAMP = 4
    TIMESTAMP_WITH_ZONE = 8
    CHAR = 16
    GEOMETRY = 32

    # map the enum to human readable form
    TO_HUMAN = {
        INTEGER: "Integer", 
        NUMERIC: "Decimal",
        TIMESTAMP: "Timestamp",
        TIMESTAMP_WITH_ZONE: "Timestamp w/timezone",
        CHAR: "Text",
        GEOMETRY: "Geometry",
    }

    # map to a PG datatype
    TO_PG_TYPE = {
        INTEGER: "integer", 
        NUMERIC: "numeric",
        TIMESTAMP: "timestamp without time zone",
        TIMESTAMP_WITH_ZONE: "timestamp with time zone",
        CHAR: "text",
        GEOMETRY: "geometry",
    }

    # maps a *cursor* type code to the enum value
    # you can get these numbers from the cursor.description
    FROM_PG_CURSOR_TYPE_CODE = {
        23: INTEGER,
        1700: NUMERIC,
        1114: TIMESTAMP,
        1184: TIMESTAMP_WITH_ZONE,
        25: CHAR,
        16463: GEOMETRY,
    }

    @classmethod
    def toString(cls, enum):
        """Convert type number to a human readable form"""
        return cls.TO_HUMAN[enum]

    @classmethod
    def toPGType(cls, enum):
        """Convert a type number to a PG data type string"""
        return cls.TO_PG_TYPE[enum]

    @classmethod
    def isValidType(cls, enum):
        return enum in cls.TO_HUMAN

    @classmethod 
    def fromPGCursorTypeCode(cls, type_code):
        """Convert a cursor.description type_code to a type number"""
        return cls.FROM_PG_CURSOR_TYPE_CODE.get(type_code, cls.CHAR)

    @classmethod 
    def fromPGTypeName(cls, type_code):
        """Convert a PG column type like "timestamp" to a type number"""
        # assume user defined types are geometries
        return dict(zip(cls.TO_PG_TYPE.values(), cls.TO_PG_TYPE.keys()))[type_code]

class Source(models.Model):
    source_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, default="")
    rank = models.IntegerField(verbose_name="Order") # just the order these rows should appear in

    class Meta:
        db_table = 'source'
        ordering = ['rank']

    def __unicode__(self):
        return u'%s' % (self.name)

class DocUpload(models.Model):
    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, default="")
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=lambda instance, filename: str(uuid.uuid4().hex) + os.path.splitext(filename)[-1])

    source = models.ForeignKey(Source)
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'document'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s' % (self.filename)


class TableOrView(models.Model):
    table_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    created_on = models.DateTimeField(null=True, default=None)
    is_view = models.BooleanField(default=False, blank=True)

    owner = models.ForeignKey(User, related_name="+")
    
    class Meta:
        db_table = 'table'
        ordering = ['schema', 'name']

    def __unicode__(self):
        return u'%s' % (self.name)


class Version(models.Model):
    version_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(User)
    table = models.ForeignKey('Table')

    class Meta:
        db_table = 'version'
        ordering = ['created_on']

    def diff(self, columns):
        """Compares this version of the table with the current version. Returns
        an iterator of 4-tuples, where each element in the 4-tuple is:
            * a row from the current version of the table
            * the corresponding row from this version of the table
            * a tuple of the primary key values (these will be the same for the current and old version)
            * a string "update", "insert" or "delete" that indicates should be
              done to the current table to make it match this version 
        """
        table_name = '"%s"."%s"' % (sanitize(self.table.schema), sanitize(self.table.name))
        audit_table_name = '"%s"' % (internalSanitize(self.table.auditTableName()))

        safe_params = {
            "table_name": table_name,
            "pks": ",".join('"%s"' % sanitize(col.name) for col in columns if col.is_pk), 
            "audit_table_name": audit_table_name,
            "audit_schema_name": AUDIT_SCHEMA_NAME,
            "table_columns": ",".join('%s."%s"' % (table_name, sanitize(col.name)) for col in columns),
            "audit_table_columns": ",".join('%s."%s"' % (audit_table_name, col.name) for col in columns),
        }

        sql = """
        SELECT 
            %(table_columns)s, 
            _restore_to.*, 
            %(pks)s,
            CASE WHEN _restore_to.* IS null THEN 'delete' WHEN %(table_name)s.* IS NULL THEN 'insert' ELSE 'update' END
        FROM 
        (
            SELECT %(audit_table_columns)s FROM
                (
                    SELECT
                        SUM(_inserted_or_deleted),
                        MAX(_version_id) AS _version_id,
                        %(pks)s
                    FROM
                        %(audit_schema_name)s.%(audit_table_name)s
                    WHERE _version_id <= %%s
                    GROUP BY
                        %(pks)s
                    HAVING
                        SUM(_inserted_or_deleted) >= 0
                ) pks
                INNER JOIN %(audit_schema_name)s.%(audit_table_name)s USING(%(pks)s, _version_id)
                WHERE _inserted_or_deleted = 1
        ) _restore_to

        FULL OUTER JOIN

        %(table_name)s USING(%(pks)s)

        WHERE COALESCE(_restore_to.* != %(table_name)s.*, true)
        """ % safe_params
        cursor = connection.cursor()

        cursor.execute(sql, (self.pk,))
        for row in cursor.fetchall():
            original_data = row[0:len(columns)]
            restore_to = row[len(columns):2*len(columns)]
            pk_values = row[len(columns)*2:-1]
            action = row[-1]
            yield original_data, restore_to, pk_values, action

    def restore(self, user):
        """Overwrite all the data in the table, and replace it with this version""" 
        with transaction.commit_on_success():
            version = Version(user=user, table=self.table)
            version.save()
            tm = TableMutator(version)

            rows = self.diff(tm.columns)
            for original_data, restore_to, pk_values, action in rows:
                if action in ['delete', 'update']:
                    tm.deleteRow(pk_values)

                if action in ['update', 'insert']:
                    tm.insertRow(restore_to)

            #rows, desc = version.fetchRows()
            #print "----"
            #for row in rows:
            #    print row
            #raise ValueError("foo")

    def fetchRows(self):
        """Fetch all the rows in the table for this version of the table"""
        table = self.table
        audit_table_name = table.auditTableName()
        pks = getPrimaryKeysForTable(table.schema, table.name)
        pks_str = ",".join(pk.name for pk in pks)
        columns = [col.name for col in getColumnsForTable(table.schema, table.name)]
        columns_str = ",".join(columns)

        safe_params = {
            "table": audit_table_name, 
            "pks": pks_str, 
            "columns": columns_str,
            "schema": AUDIT_SCHEMA_NAME,
        }
        params = (self.pk,)
        sql = """
        SELECT %(columns)s FROM
        (
            SELECT 
                SUM(_inserted_or_deleted), 
                MAX(_version_id) AS _version_id, 
                %(pks)s
            FROM 
                %(schema)s.%(table)s
            WHERE _version_id <= %%s
            GROUP BY 
                %(pks)s
            HAVING 
                SUM(_inserted_or_deleted) >= 0
        ) pks
        INNER JOIN %(schema)s.%(table)s USING(%(pks)s, _version_id)
        WHERE _inserted_or_deleted = 1
        ORDER BY %(pks)s
        """ % safe_params
        #cursor = connection.cursor()
        #cursor.execute(sql, params)
        return SQLHandle(sql, params, privileged=True)


class TablePermission(models.Model):
    # permissions need to be powers of 2 so we can do bitwise ANDs and ORs
    INSERT = 1
    UPDATE = 2
    DELETE = 4

    table_permission_id = models.AutoField(primary_key=True)
    table = models.ForeignKey('Table')
    user = models.ForeignKey(User)
    permission = models.IntegerField()

    class Meta:
        db_table = 'tablepermission'
        unique_together = ("table", "user")

class TableMutator(object):
    def __init__(self, version, columns=None):
        self.table = version.table

        # the caller can pass in the columns, or we can fetch them ourselves
        if columns is None:
            self.columns = getColumnsForTable(self.table.schema, self.table.name)
        else:
            self.columns = columns

        # build SQL query strings for inserting data and deleting data from the
        # table itself, and the audit table
        
        # build the escape string for insert queries. A little complex because
        # we have to handle Geometry columns. 
        escape_string = []
        for col in self.columns:
            if col.type == ColumnTypes.GEOMETRY:
                escape_string.append("ST_Transform(ST_GeomFromText(%%s, %s), %d)" % (col.srid, SETTINGS.OFFICIAL_SRID))
            else:
                escape_string.append("%s")
        escape_string = ",".join(escape_string)
        safe_col_name_str = ",".join('"%s"' % sanitize(col.name) for col in self.columns)
        self.insert_sql = """INSERT INTO "%s"."%s" (%s) VALUES(%s)""" % (
            sanitize(self.table.schema), 
            sanitize(self.table.name),
            safe_col_name_str,
            escape_string,
        )
        self.audit_insert_sql = """INSERT INTO "%s"."%s" (%s, _inserted_or_deleted, _version_id) VALUES(%s, 1, %s)""" % (
            AUDIT_SCHEMA_NAME,
            internalSanitize(self.table.auditTableName()),
            safe_col_name_str, 
            escape_string,
            int(version.pk),
        )

        # now build the delete SQL strings
        escape_string = " AND ".join(['"%s" = %%s' % sanitize(col.name) for col in self.columns if col.is_pk])
        self.delete_sql = 'DELETE FROM "%s"."%s" WHERE %s' % (
            sanitize(self.table.schema), 
            sanitize(self.table.name), 
            escape_string
        )
        escape_string = ",".join(["%s" for col in self.columns if col.is_pk])
        safe_pk_name_str = ",".join(['"%s"' % sanitize(col.name) for col in self.columns if col.is_pk])
        self.audit_delete_sql = """INSERT INTO %s.%s (%s, _inserted_or_deleted, _version_id) VALUES(%s, -1, %s)""" % (
            AUDIT_SCHEMA_NAME,
            internalSanitize(self.table.auditTableName()), 
            safe_pk_name_str,
            escape_string,
            int(version.pk)
        )
        self.cursor = connection.cursor()

    def insertRow(self, values):
        """Values is a tuple of values that corresponds to the order of self.columns"""
        self._doSQL(self.insert_sql, values)
        self._doSQL(self.audit_insert_sql, values)

    def deleteRow(self, values):
        """Values is a tuple of pk values that corresponds to the order of self.columns"""
        if self._doSQL(self.delete_sql, values) > 0:
            self._doSQL(self.audit_delete_sql, values)

    def deleteAllRows(self):
        pks = [col.name for col in self.columns if col.is_pk]
        handle = fetchRowsFor(self.table.schema, self.table.name, pks)
        for row in handle:
            self.deleteRow(row)

    def _doSQL(self, sql, params):
        cursor = self.cursor
        try:
            cursor.execute(sql, params)
        except DatabaseError as e:
            connection._rollback()
            # tack on the SQL statement that caused the error
            e.sql = connection.queries[-1]['sql']
            raise

        return cursor.rowcount

from .dbhelpers import getPrimaryKeysForTable, getColumnsForTable, sanitize, internalSanitize, SQLHandle, getDatabaseTopology, fetchRowsFor
from .importable import ImportableUpload, CSVImport, ShapefileImport
from .schemata import Table
