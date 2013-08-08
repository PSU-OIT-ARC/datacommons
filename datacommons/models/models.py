import uuid
import os
from collections import defaultdict
from django.db import models, connection, transaction, DatabaseError
from django.utils.datastructures import SortedDict
from django.contrib.auth.models import User

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
    def groupedBySchema(self, owner):
        tables = Table.objects.filter(owner=owner).exclude(created_on=None)
        results = SortedDict()
        for table in tables:
            results.setdefault(table.schema, []).append(table)

        return results

class Version(models.Model):
    version_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(User)
    table = models.ForeignKey('Table')

    class Meta:
        db_table = 'version'
        ordering = ['created_on']

    def restore(self, user):
        """Overwrite all the data in the table, and replace it with this version""" 
        table = self.table
        audit_table_name = table.auditTableName()
        table_name = table.schema + "." + table.name
        pks = getPrimaryKeysForTable(table.schema, table.name)
        pks_str = ",".join(pks)
        columns = [col['name'] for col in getColumnsForTable(table.schema, table.name)]
        columns_str = ",".join(columns)

        safe_params = {
            "table_name": table_name,
            "pks": pks_str, 
            "columns": columns_str,
            "audit_table_name": audit_table_name,
            "table_columns": ",".join("%s.%s" % (table_name, col) for col in columns),
            "audit_table_columns": ",".join("%s.%s" % (audit_table_name, col) for col in columns),
        }
        args = (self.pk,)

        with transaction.commit_on_success():
            sql = """
            SELECT 
                %(table_columns)s, 
                restore_to.*, 
                %(pks)s,
                CASE WHEN restore_to.* IS null THEN 'delete' WHEN %(table_name)s.* IS NULL THEN 'insert' ELSE 'update' END
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
            ) AS restore_to

            FULL OUTER JOIN

            %(table_name)s USING(%(pks)s)

            WHERE COALESCE(restore_to.* != %(table_name)s.*, true)
            """ % safe_params
            cursor = connection.cursor()
            cursor.execute(sql, args)

            version = Version(user=user, table=table)
            version.save()

            for row in cursor.fetchall():
                original_data = row[0:len(columns)]
                restore_to = row[len(columns):len(columns)+len(columns)]
                pk_values = row[len(columns)*2:-1]
                action = row[-1]
                print original_data, restore_to, action, pk_values
                pk_key_value = dict([(pk_name, pk_values[i]) for i, pk_name in enumerate(pks)])
                if action in ['delete', 'update']:
                    # delete from the current table
                    # log the delete in the audit table
                    cursor.execute("DELETE FROM %(table_name)s WHERE %(escape_string)s" % {
                        'table_name': table_name,
                        'escape_string': " AND ".join("%s = %%s" % key for key in pk_key_value.keys())
                    }, pk_key_value.values())

                    cursor.execute("INSERT INTO public.%(audit_table_name)s (%(pks)s, _inserted_or_deleted, _version_id) VALUES(%(escape_string)s, -1, %%s)" % {
                        'audit_table_name': audit_table_name,
                        'pks': ",".join(pk_key_value.keys()),
                        'escape_string': ",".join("%s" for _ in pk_key_value.values()),
                    }, pk_key_value.values() + [version.pk])

                if action in ['update', 'insert']:
                    # insert into the current table
                    # insert into the log table
                    cursor.execute("INSERT INTO %(table_name)s (%(columns)s) VALUES(%(escape_string)s)" % {
                        'table_name': table_name,
                        'columns': ",".join(columns),
                        'escape_string': ",".join("%s" for _ in columns),
                    }, restore_to)

                    cursor.execute("INSERT INTO public.%(audit_table_name)s (%(columns)s, _inserted_or_deleted, _version_id) VALUES(%(escape_string)s, 1, %%s)" % {
                        'audit_table_name': audit_table_name,
                        'columns': ",".join(columns),
                        'escape_string': ",".join("%s" for _ in columns),
                    }, restore_to + (version.pk,))

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
        """ % safe_params
        cursor = connection.cursor()
        cursor.execute(sql, params)

        return cursor.fetchall(), cursor.description


class Table(models.Model):
    table_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    created_on = models.DateTimeField(null=True, default=None)

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

from .dbhelpers import getPrimaryKeysForTable, getColumnsForTable
