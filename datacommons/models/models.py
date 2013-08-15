import uuid
import os
from collections import defaultdict
from django.db import models, connection, transaction, DatabaseError
from django.utils.datastructures import SortedDict
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **kwargs):
        if not email:
            raise ValueError('Users must have an email address')

        user = self.model(email=self.normalize_email(email), **kwargs)

        user.set_password(password)
        user.save(using=self._db)
        return user

class User(AbstractBaseUser):
    id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, blank=True)
    is_superuser = models.BooleanField(default=False, blank=True)
    is_staff = models.BooleanField(default=False, blank=True)

    USERNAME_FIELD = 'email'

    objects = UserManager()

    class Meta:
        db_table = "auth_user"


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
        if type_code == "USER-DEFINED":
            return cls.GEOMETRY
        # invert the PG_TYPE_NAME dict
        return dict(zip(cls.TO_PG_TYPE.values(), cls.TO_PG_TYPE.keys()))[type_code]

class ImportableUpload(models.Model):
    # mode
    CREATE = 1
    APPEND = 2
    UPSERT = 3
    DELETE = 4
    REPLACE = 5

    # status
    DONE = 4
    PENDING = 8

    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255)
    status = models.IntegerField(choices=((DONE, "Done"), (PENDING, "Pending")), default=PENDING)
    mode = models.IntegerField(choices=(
        (APPEND, "Append"), 
        (CREATE, "Create"),
        (UPSERT, "Upsert"),
        (DELETE, "Delete"),
        (REPLACE, "Replace"),
    ))

    table = models.OneToOneField('Table')
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'csv'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s.%s' % (self.table.schema, self.table.name)

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

class TableManager(models.Manager):
    def groupedBySchema(self, owner=None):
        if owner is None:
            tables = Table.objects.exclude(created_on=None)
        else:
            tables = Table.objects.filter(owner=owner).exclude(created_on=None)
        results = SortedDict()
        for table in tables:
            results.setdefault(table.schema, []).append(table)

        return results


class Table(models.Model):
    table_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    created_on = models.DateTimeField(null=True, default=None)
    #is_view = models.BooleanField(default=False, blank=True)

    owner = models.ForeignKey(User, related_name="+")
    
    objects = TableManager()

    class Meta:
        db_table = 'table'
        ordering = ['schema', 'name']

    def __unicode__(self):
        return u'%s' % (self.name)

    def auditTableName(self):
        return "_" + self.schema + "_" + self.name

    def canDo(self, user, permission_bit, perm=None):
        # owner can always do stuff
        if self.owner == user:
            return True

        try:
            if not perm:
                perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            return False

        return bool(perm.permission & permission_bit)

    def canInsert(self, user, perm=None):
        return self.canDo(user, TablePermission.INSERT, perm)
    def canUpdate(self, user, perm=None):
        return self.canDo(user, TablePermission.UPDATE, perm)
    def canDelete(self, user, perm=None):
        return self.canDo(user, TablePermission.DELETE, perm)
    def canRestore(self, user, perm=None):
        return self.canInsert(user, perm) and self.canUpdate(user, perm) and self.canDelete(user, perm)

    def grant(self, user, perm_bit):
        try:
            perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            perm = TablePermission(table=self, user=user, permission=0)

        perm.permission |= perm_bit
        perm.save()

    def revoke(self, user, perm_bit):
        try:
            perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            perm = TablePermission(table=self, user=user, permission=0)

        perm.permission &= ~perm_bit
        perm.save()

        # if there are no permissions set, just delete the record
        if perm.permission == 0:
            perm.delete()

    def permissionGrid(self):
        perms = TablePermission.objects.filter(table=self).select_related("user")
        rows = {}
        for perm in perms:
            item = rows.setdefault(perm.user, {})
            item['can_insert'] = self.canInsert(perm.user, perm)
            item['can_update'] = self.canUpdate(perm.user, perm)
            item['can_delete'] = self.canDelete(perm.user, perm)

        return rows


class TableMutator(object):
    def __init__(self, version):
        table = version.table
        self.column_info = getColumnsForTable(table.schema, table.name)

        # add the pk flag to the column info
        pks = getPrimaryKeysForTable(table.schema, table.name)
        for col in self.column_info:
            col['is_pk'] = col['name'] in pks

        # build SQL query strings for inserting data and deleting data from the
        # table itself, and the audit table
        
        # build the escape string for insert queries. A little complex because
        # we have to handle Geometry columns. This requires the caller to add
        # an srid dictionary key to the appropriate column.
        escape_string = []
        for col in self.column_info:
            if col['type'] == ColumnTypes.GEOMETRY:
                escape_string.append("ST_GeomFromText(%%s, %s)" % (col['srid']))
            else:
                escape_string.append("%s")
        escape_string = ",".join(escape_string)
        safe_col_name_str = ",".join('"%s"' % sanitize(col['name']) for col in self.column_info)
        self.insert_sql = """INSERT INTO "%s"."%s" (%s) VALUES(%s)""" % (
            sanitize(table.schema), 
            sanitize(table.name),
            safe_col_name_str,
            escape_string,
        )
        self.audit_insert_sql = """INSERT INTO public."%s" (%s, _inserted_or_deleted, _version_id) VALUES(%s, 1, %s)""" % (
            internalSanitize(table.auditTableName()),
            safe_col_name_str, 
            escape_string,
            int(version.pk),
        )

        # now build the delete SQL strings
        escape_string = " AND ".join(['"%s" = %%s' % sanitize(col['name']) for col in self.column_info if col['is_pk']])
        self.delete_sql = 'DELETE FROM "%s"."%s" WHERE %s' % (
            sanitize(table.schema), 
            sanitize(table.name), 
            escape_string
        )
        escape_string = ",".join(["%s" for _ in pks])
        safe_pk_name_str = ",".join(['"%s"' % sanitize(col['name']) for col in self.column_info if col['is_pk']])
        self.audit_delete_sql = """INSERT INTO public.%s (%s, _inserted_or_deleted, _version_id) VALUES(%s, -1, %s)""" % (
            internalSanitize(table.auditTableName()), 
            safe_pk_name_str,
            escape_string,
            int(version.pk)
        )
        self.cursor = connection.cursor()

    def insertRow(self, values):
        """Values is a tuple of values that corresponds to the order of self.column_info"""
        self._doSQL(self.insert_sql, values)
        self._doSQL(self.audit_insert_sql, values)

    def deleteRow(self, values):
        """Values is a tuple of pk values that corresponds to the order of self.column_info"""
        self._doSQL(self.delete_sql, values)
        self._doSQL(self.audit_delete_sql, values)

    def pkNames(self):
        return [col['name'] for col in self.column_info if col['is_pk']]

    def columnNames(self):
        return [col['name'] for col in self.column_info]

    def _doSQL(self, sql, params):
        cursor = self.cursor
        try:
            cursor.execute(sql, params)
        except DatabaseError as e:
            connection._rollback()
            # tack on the SQL statement that caused the error
            e.sql = connection.queries[-1]['sql']
            raise

class Version(models.Model):
    version_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(User)
    table = models.ForeignKey('Table')

    class Meta:
        db_table = 'version'
        ordering = ['created_on']

    def diff(self, column_info):
        table_name = '"%s"."%s"' % (sanitize(self.table.schema), sanitize(self.table.name))
        audit_table_name = '"%s"' % (internalSanitize(self.table.auditTableName()))

        safe_params = {
            "table_name": table_name,
            "pks": ",".join('"%s"' % sanitize(col['name']) for col in column_info if col['is_pk']), 
            "audit_table_name": audit_table_name,
            "table_columns": ",".join('%s."%s"' % (table_name, sanitize(col['name'])) for col in column_info),
            "audit_table_columns": ",".join('%s."%s"' % (audit_table_name, col['name']) for col in column_info),
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
                        %(audit_table_name)s
                    WHERE _version_id <= %%s
                    GROUP BY
                        %(pks)s
                    HAVING
                        SUM(_inserted_or_deleted) >= 0
                ) pks
                INNER JOIN %(audit_table_name)s USING(%(pks)s, _version_id)
                WHERE _inserted_or_deleted = 1
        ) _restore_to

        FULL OUTER JOIN

        %(table_name)s USING(%(pks)s)

        WHERE COALESCE(_restore_to.* != %(table_name)s.*, true)
        """ % safe_params
        cursor = connection.cursor()

        cursor.execute(sql, (self.pk,))
        for row in cursor.fetchall():
            original_data = row[0:len(column_info)]
            restore_to = row[len(column_info):2*len(column_info)]
            pk_values = row[len(column_info)*2:-1]
            action = row[-1]
            yield original_data, restore_to, pk_values, action

    def restore(self, user):
        """Overwrite all the data in the table, and replace it with this version""" 
        with transaction.commit_on_success():
            version = Version(user=user, table=self.table)
            version.save()
            tm = TableMutator(version)

            rows = self.diff(tm.column_info)
            for original_data, restore_to, pk_values, action in rows:
                if action in ['delete', 'update']:
                    tm.deleteRow(pk_values)

                if action in ['update', 'insert']:
                    tm.insertRow(restore_to)

            rows, desc = version.fetchRows()
            print "----"
            for row in rows:
                print row
            #raise ValueError("foo")

    def fetchRows(self):
        """Fetch all the rows in the table for this version of the table"""
        table = self.table
        audit_table_name = table.auditTableName()
        pks = getPrimaryKeysForTable(table.schema, table.name)
        pks_str = ",".join(pks)
        columns = [col['name'] for col in getColumnsForTable(table.schema, table.name)]
        columns_str = ",".join(columns)

        safe_params = {"table": audit_table_name, "pks": pks_str, "columns": columns_str}
        params = (self.pk,)
        sql = """
        SELECT %(columns)s FROM
        (
            SELECT 
                SUM(_inserted_or_deleted), 
                MAX(_version_id) AS _version_id, 
                %(pks)s
            FROM 
                %(table)s
            WHERE _version_id <= %%s
            GROUP BY 
                %(pks)s
            HAVING 
                SUM(_inserted_or_deleted) >= 0
        ) pks
        INNER JOIN %(table)s USING(%(pks)s, _version_id)
        WHERE _inserted_or_deleted = 1
        ORDER BY %(pks)s
        """ % safe_params
        cursor = connection.cursor()
        cursor.execute(sql, params)

        return coerceRowsAndParseColumns(cursor.fetchall(), cursor.description)


class TablePermission(models.Model):
    # permissions need to be powers of 2 so we can do bitwise ANDs and ORs
    INSERT = 1
    UPDATE = 2
    DELETE = 4

    table_permission_id = models.AutoField(primary_key=True)
    table = models.ForeignKey(Table)
    user = models.ForeignKey(User)
    permission = models.IntegerField()

    class Meta:
        db_table = 'tablepermission'
        unique_together = ("table", "user")

from .dbhelpers import getPrimaryKeysForTable, getColumnsForTable, coerceRowsAndParseColumns, sanitize, internalSanitize
