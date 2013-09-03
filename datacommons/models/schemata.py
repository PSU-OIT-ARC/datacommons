from .models import ColumnTypes, AUDIT_SCHEMA_NAME
from django.db import connection, transaction, DatabaseError, connections

class Topology(object):
    _instance = None

class SchemataItem(object):
    def __unicode__(self):
        return self.name

class Schema(SchemataItem):
    def __init__(self, name):
        self.tables = []
        self.views = []
        self.name = name

    def __iter__(self):
        return iter(self.tables)

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

class View(SchemataItem):
    def __init__(self, name):
        self.columns = []
        self.name = name
        self.is_view = True

    @classmethod
    def create(schema, name, sql, commit=False):
        # this will raise a database Error is there is a problem with the SQL (hopefully)
        SQLHandle(sql).count()
        cursor = connection.cursor()
        cursor.execute("SELECT dc_create_view(%s, %s, %s)", (schema.name, name, sql))
        if commit:
            transaction.commit_unless_managed()
        else:
            connection._rollback()

class Table(SchemataItem):
    def __init__(self, name):
        self.columns = []
        self.name = name
        self.is_view = False

    def __iter__(self):
        return iter(self.columns)

    @classmethod
    def create(cls, table, columns, commit=False):
        column_names = [col.name for col in columns if col.type != ColumnTypes.GEOMETRY]
        column_types = [col.type for col in columns if col.type != ColumnTypes.GEOMETRY]

        # santize all the names
        schema_name = sanitize(table.schema)
        table_name = sanitize(table.name)

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
        audit_table_name = table.auditTableName()
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
        self.srid = None
        self.geom_type = None

        self.type_label = ColumnTypes.toString(self.type)

from .dbhelpers import sanitize
