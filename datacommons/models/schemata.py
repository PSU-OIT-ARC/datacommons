from django.utils.datastructures import SortedDict
from .models import ColumnTypes, AUDIT_SCHEMA_NAME, TableOrView, TablePermission
from django.db import models, connection, transaction, DatabaseError, connections

class SchemataItem(object):
    def __unicode__(self):
        return self.name

class Schema(SchemataItem):
    def __init__(self, name):
        self.tables = []
        self.views = []
        self.name = name

    def __iter__(self):
        return iter(self.tables + self.views)

    @classmethod
    def create(cls, name):
        name = sanitize(name)
        cursor = connection.cursor()
        # we aren't using the second parameter to execute() to pass the name in
        # because we already (hopefully) escaped the input
        cursor.execute("CREATE SCHEMA %s" % name)

        # use the stored proc created by mharvey to setup the proper perms on the
        # table
        cursor.execute("SELECT dc_set_perms(%s);", (name,))

        transaction.commit_unless_managed()

class View(SchemataItem, TableOrView):
    class Meta:
        proxy = True

    def __init__(self, *args, **kwargs):
        super(View, self).__init__(*args, **kwargs)
        self.columns = []
        self.name = self.name or kwargs.pop("name", None)
        self.is_view = True

    def toJSON(self):
        return {"name": self.name, "columns": self.columns, "is_view": self.is_view}

    def create(self, sql, commit=False):
        # this will raise a database Error is there is a problem with the SQL (hopefully)
        SQLHandle(sql).count()
        cursor = connection.cursor()
        cursor.execute("SELECT dc_create_view(%s, %s, %s)", (self.schema, self.name, sql))
        if commit:
            transaction.commit_unless_managed()
        else:
            connection._rollback()

class TableManager(models.Manager):
    def get_queryset(self):
        return super(TableManager, self).get_queryset().filter(is_view=False)

    def groupedBySchema(self, owner=None, include_views=False):
        # build a set of all the (schema, table) tuples in the db
        topology = getDatabaseTopology()
        s = set()
        for schema in topology:
            for table in schema.tables:
                s.add((schema.name, table.name))

        if owner is None:
            tables = Table.objects.exclude(created_on=None)
        else:
            tables = Table.objects.filter(owner=owner).exclude(created_on=None)

        if not include_views:
            tables = tables.exclude(is_view=True)

        results = SortedDict()
        for table in tables:
            # the tables in the database, and the tables in the "table" table
            # might not quite match. So only return the results where there is a match
            if (table.schema, table.name) in s:
                results.setdefault(table.schema, []).append(table)

        return results

class Table(SchemataItem, TableOrView):
    objects = TableManager()

    class Meta:
        proxy = True

    def __init__(self, *args, **kwargs):
        super(Table, self).__init__(*args, **kwargs)
        self.columns = []
        self.name = self.name or kwargs.pop("name", None)
        self.is_view = False

    def __iter__(self):
        return iter(self.columns)

    def toJSON(self):
        return {"name": self.name, "columns": self.columns, "is_view": self.is_view}

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

    def create(self, columns, commit=False):
        column_names = [col.name for col in columns if col.type != ColumnTypes.GEOMETRY]
        column_types = [col.type for col in columns if col.type != ColumnTypes.GEOMETRY]

        # santize all the names
        schema_name = sanitize(self.schema)
        table_name = sanitize(self.name)

        # sanitize 
        names = []
        for name in column_names:
            names.append(sanitize(name))
        column_names = names

        names = []
        for name in [col.name for col in columns if col.is_pk]:
            names.append(sanitize(name))
        primary_keys = names

        # get all the column type names
        types = []
        for type in column_types:
            types.append(ColumnTypes.toPGType(int(type)))

        column_sql = []
        for i in range(len(column_names)):
            column_sql.append(column_names[i] + " " + types[i])
        column_sql = ",".join(column_sql)

        # sure hope this is SQL injection proof
        create_table_sql = """
            CREATE TABLE "%s"."%s" (
                %s
            );
        """ % (schema_name, table_name, column_sql)
        cursor = connection.cursor()
        cursor.execute(create_table_sql)

        # now add the audit table
        audit_table_name = self.auditTableName()
        audit_table_sql = """
            CREATE TABLE "%s"."%s" (
                _version_id INTEGER NOT NULL REFERENCES "version" ("version_id") DEFERRABLE INITIALLY DEFERRED,
                _inserted_or_deleted smallint,
                %s
            );
        """ % (AUDIT_SCHEMA_NAME, audit_table_name, column_sql)
        cursor.execute(audit_table_sql)

        # add the primary key, if there is one
        if len(primary_keys):
            sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (schema_name, table_name, ",".join(primary_keys))
            cursor.execute(sql)

            audit_pks = primary_keys + ['_version_id', '_inserted_or_deleted']
            sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (AUDIT_SCHEMA_NAME, audit_table_name, ",".join(audit_pks))
            cursor.execute(sql)

        has_geom = any(col.srid for col in columns)
        if has_geom:
            # find the column with the geometry
            col = [col for col in columns if col.srid][0]
            cls._addGeometryColumn(schema_name, table_name, col, commit=commit)
            cls._addGeometryColumn(AUDIT_SCHEMA_NAME, audit_table_name, col, commit=commit)

        # run morgan's fancy proc
        cursor.execute("SELECT dc_set_perms(%s, %s);", (schema_name, table_name))
        cursor.execute("SELECT dc_set_perms(%s, %s);", (AUDIT_SCHEMA_NAME, audit_table_name))

        if commit:
            transaction.commit_unless_managed()

    @classmethod
    def _addGeometryColumn(cls, schema_name, table_name, col, commit=False):
        cursor = connection.cursor()
        cursor.execute("""SELECT AddGeometryColumn(%s, %s, %s, %s, %s, 2)""",
            (schema_name, table_name, col.name, col.srid, col.geom_type))

        if commit:
            transaction.commit_unless_managed()

class Column(SchemataItem):
    def __init__(self, name, type, is_pk, srid=None, geom_type=None):
        self.name = name
        self.type = type
        self.is_pk = is_pk
        self.srid = srid
        self.geom_type = geom_type

        self.type_label = ColumnTypes.toString(self.type)

from .dbhelpers import sanitize, SQLHandle, getDatabaseTopology
