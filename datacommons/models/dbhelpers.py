import uuid
import os
import re
from collections import defaultdict
from django.conf import settings as SETTINGS
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection, transaction, DatabaseError, connections

def isSaneName(value):
    """Return true if value is a valid identifier"""
    return value == sanitize(value) and len(value) >= 1 and len(value) <= 63 and re.search("^[a-z]", value)

def sanitize(value):
    """Strip out bad characters from value"""
    value = value.lower().strip()
    value = re.sub(r'\s+', '_', value).strip('_')
    return re.sub(r'[^a-z_0-9]', '', value)

def internalSanitize(value):
    """This differs from sanitize() because it allows names that start or end
    with underscore"""
    value = value.lower().strip()
    return re.sub(r'[^a-z_0-9]', '', value)

class SchemataItem(object):
    def __unicode__(self):
        return self.name

class Schema(SchemataItem):
    def __init__(self, name):
        self.tables = []
        self.name = name

    def __iter__(self):
        return iter(self.tables)

class Table(SchemataItem):
    def __init__(self, name, is_view=False):
        self.columns = []
        self.name = name
        self.is_view = is_view

    def __iter__(self):
        return iter(self.columns)

class Column(SchemataItem):
    def __init__(self, name, type, is_pk):
        self.name = name
        self.type = type
        self.is_pk = is_pk

        self.type_label = ColumnTypes.toString(self.type)

def getDatabaseTopology():
    sql = """
        SET session authorization datacommons_rw;
        SELECT
            nspname,
            t.table_name,
            t.table_type,
            c.column_name,
            c.data_type,
            pks.constraint_type
        FROM
            pg_namespace
        LEFT JOIN
            information_schema.tables t ON t.table_schema = nspname
        LEFT JOIN 
            information_schema.columns c on c.table_schema = nspname AND t.table_name = c.table_name
        LEFT JOIN (
            SELECT
                tc.table_schema,
                tc.table_name,
                column_name,
                tc.constraint_type
            FROM
                information_schema.table_constraints as tc
            INNER JOIN
                information_schema.key_column_usage as kcu
            ON
                tc.constraint_name = kcu.constraint_name
                AND
                tc.table_schema = kcu.table_schema
                AND
                tc.table_name = kcu.table_name
            WHERE
                tc.constraint_type = 'PRIMARY KEY'
        ) pks ON pks.table_schema = nspname AND pks.table_name = t.table_name AND pks.column_name = c.column_name
        WHERE 
            pg_namespace.nspowner != 10 AND 
            nspname != 'geometries'
            ORDER BY nspname, table_name, c.ordinal_position
    """
    cursor = connection.cursor()
    cursor.execute(sql)

    topology = []
    for schema_name, table_name, table_type, column_name, data_type, constraint_type in cursor.fetchall():
        # add the schema object
        if len(topology) == 0 or topology[-1].name != schema_name:
            topology.append(Schema(schema_name))
        schema = topology[-1]

        # this schema has no tables, so move on
        if not table_name: continue

        if len(schema.tables) == 0 or schema.tables[-1].name != table_name:
            schema.tables.append(Table(table_name, table_type == "VIEW"))
        table = schema.tables[-1]

        # this table has no columns, so move on
        if not column_name: continue

        table.columns.append(Column(column_name, ColumnTypes.fromPGTypeName(data_type), constraint_type is not None))

    return topology

def addGeometryColumn(schema_name, table_name, srid, type, commit=False):
    cursor = connection.cursor()
    cursor.execute("""SELECT AddGeometryColumn(%s, %s, %s, %s, %s, 2)""",
        (schema_name, table_name, "the_geom", srid, type))

    if commit:
        transaction.commit_unless_managed()

def getPrimaryKeysForTable(schema, table):
    """
    Returns a set of the column names in `schema.table` that are primary keys
    """
    cols = getColumnsForTable(schema, table)
    return [col for col in cols if col.is_pk]

def getColumnsForTable(schema, table):
    """Return a list of columns in schema.table"""
    topology = getDatabaseTopology()
    for s in topology:
        if s.name == schema:
            break

    for t in s:
        if t.name == table:
            return t.columns

def createSchema(name):
    name = sanitize(name)
    cursor = connection.cursor()
    # we aren't using the second parameter to execute() to pass the name in
    # because we already (hopefully) escaped the input
    cursor.execute("CREATE SCHEMA %s" % name)

    # use the stored proc created by mharvey to setup the proper perms on the
    # table
    cursor.execute("SELECT dc_set_perms(%s);", (name,))

    transaction.commit_unless_managed()

def createTable(table, column_names, column_types, primary_keys, commit=False, geometry_config=None):
    """Create a table in `table.schema` named `table.name`, with columns named
    column_names, with types column_types."""
    # remove the geom type
    column_names = [name for type, name in zip(column_types, column_names) if type != ColumnTypes.GEOMETRY]
    column_types = [type for type in column_types if type != ColumnTypes.GEOMETRY]

    # santize all the names
    schema_name = sanitize(table.schema)
    table_name = sanitize(table.name)
    # sanitize and put quotes around the columns
    names = []
    for name in column_names:
        names.append('"' + sanitize(name) + '"')
    column_names = names

    names = []
    for name in primary_keys:
        names.append('"' + sanitize(name) + '"')
    primary_keys = names

    # get all the column type names
    types = []
    for type in column_types:
        types.append(ColumnTypes.toPGType(int(type)))

    # build up part of the query string defining the columns. e.g.
    # alpha integer,
    # beta decimal,
    # gamma text
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
    """ % ("public", audit_table_name, column_sql)
    cursor.execute(audit_table_sql)

    # add the primary key, if there is one
    if len(primary_keys):
        sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (schema_name, table_name, ",".join(primary_keys))
        cursor.execute(sql)

        audit_pks = primary_keys + ['_version_id', '_inserted_or_deleted']
        sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % ("public", audit_table_name, ",".join(audit_pks))
        cursor.execute(sql)

    if geometry_config:
        addGeometryColumn(schema_name, table_name, geometry_config['srid'], geometry_config['type'], commit=commit)
        addGeometryColumn("public", audit_table_name, geometry_config['srid'], geometry_config['type'], commit=commit)

    # run morgan's fancy proc
    cursor.execute("SELECT dc_set_perms(%s, %s);", (schema_name, table_name))

    if commit:
        transaction.commit_unless_managed()

def fetchRowsFor(schema, table, columns=None):
    """Return a 2-tuple of the rows in schema.table, and the cursor description"""
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    pks = getPrimaryKeysForTable(schema, table)
    pk_string = ",".join(pks)
    if columns:
        column_str = ",".join('"%s"' % sanitize(col) for col in columns)
    else:
        column_str = "*"

    if pk_string != "":
        sql = '''SELECT %s FROM "%s"."%s" ORDER BY %s''' % (column_str, schema, table, pk_string)
    else:
        sql = '''SELECT %s FROM "%s"."%s" ''' % (column_str, schema, table)

    return SQLHandle(sql)

def createView(schema_name, view_name, sql, commit=False):
    # this will raise a database Error is there is a problem with the SQL (hopefully)
    SQLHandle(sql).count()
    cursor = connection.cursor()
    cursor.execute("SELECT dc_create_view(%s, %s, %s)", (schema_name, view_name, sql))
    if commit:
        transaction.commit_unless_managed()
    else:
        connection._rollback()

def inferColumnTypes(rows):
    """`rows` is a list of lists (i.e. a table). For each column in the table,
    determine the appropriate postgres datatype for that column. Return a list
    of ColumnTypes enums where the n-th item in the list corrsponds to the
    datatype of the n-th column in the table"""
    transposed = zip(*rows)
    return map(_inferColumnType, transposed)

def _inferColumnType(data):
    # try to deduce the column type
    # this must be ordered from most strict type to least strict type
    is_valid_as_type = [
        ColumnTypes.GEOMETRY,
        ColumnTypes.TIMESTAMP_WITH_ZONE,
        ColumnTypes.TIMESTAMP,
        ColumnTypes.INTEGER,
        ColumnTypes.NUMERIC,
        ColumnTypes.CHAR,
    ]

    # for each data item, for each type, check if that data item is an
    # acceptable value for that type
    for val in data:
        is_valid_as_type = [type for type in is_valid_as_type if _isValidValueAsPGType(val, type)]

    return is_valid_as_type[0]

def _isValidValueAsPGType(value, type):
    pg_type = ColumnTypes.toPGType(type)
    cursor = connection.cursor()
    if type == ColumnTypes.GEOMETRY:
        try:
            cursor.execute("""SELECT ST_GeomFromText(%s)""", (value,))
        except DatabaseError as e:
            connection._rollback()
            return False
    else:
        try:
            cursor.execute("""SELECT %%s::%s""" % (pg_type), (value,))
        except DatabaseError as e:
            connection._rollback()
            return False

    # if we're checking for a timestamp with a timezone, we need to figure out
    # if it *actually* has a timezone component, since postgres unfortunately
    # assumes UTC when a timezone is not present
    if type == ColumnTypes.TIMESTAMP_WITH_ZONE:
        timestamp_pg_type = ColumnTypes.toPGType(ColumnTypes.TIMESTAMP)
        # compare the value as a TIMESTAMP WITH TIME ZONE and a TIMEZONE. If they
        # are equal, then this value does *not* have a useful timezone
        # component
        cursor.execute("""SELECT %%s::%s = %%s::%s""" % (pg_type, timestamp_pg_type), (value, value))
        if cursor.fetchone()[0]:
            return False

    return True


class SQLHandle(object):
    """This class wraps up a SQL statement with its parameters and allows it to
    be paginated over efficently, and iterated over"""
    def __init__(self, sql, params=()):
        self._sql = sql
        self._params = params
        self._count = None
        self._cursor = None
        self._cols = None

    def count(self):
        """Returns a count of the number of rows returned by the SQL. This method helps make this class Django Paginator compatible""" 
        if self._count == None:
            # construct some SQL that will efficently return the number of rows
            # returned by the SQL 
            cursor = connections['readonly'].cursor()
            count_sql = "SELECT COUNT(*) FROM (" + self._sql + ") AS f"
            cursor.execute(count_sql, self._params)
            self._count = cursor.fetchall()[0][0]
        return self._count

    @property
    def cols(self):
        """Returns the the column info related to the SQL as a list of dicts
        with keys for the column name, type_label and type."""
        # we need to fetch the col info based on the SQL, since it hasn't been generated yet
        if self._cols == None:
            # we haven't executed a query yet, so do that to get the cursor.description
            if self._cursor == None:
                self._fetchRowsForQuery()

            # build up the col info list
            self._cols = [
            {
                "name": t.name, 
                "type_label": ColumnTypes.toString(ColumnTypes.fromPGCursorTypeCode(t.type_code)),
                "type": ColumnTypes.fromPGCursorTypeCode(t.type_code)
            } for t in self._cursor.description]

        return self._cols

    def __iter__(self):
        """Iterate over all the rows returned by the query"""
        # if the cursor has already been set (like in the `self.cols` method)
        # use that, otherwise execute the query
        cursor = self._cursor or self._fetchRowsForQuery()

        has_geom = any(c['type'] == ColumnTypes.GEOMETRY for c in self.cols)

        # if there is no geometry column, all the type casting is taken care of
        # automagically by python
        if not has_geom:
            for row in cursor:
                yield row
        else:
            # we need to cast the geometry columns in the row to a Geometry type
            for row in cursor:
                yield self._castRow(row)

    def __getitem__(self, key):
        """Fetch part of the results of the query using slice notation for the
        offset and limit. Hopefully the query contains a well crafted order by
        clause, otherwise the results may not be as expected. This method helps
        make the class Django Paginator compatible"""
        if isinstance(key, slice):
            self._fetchRowsForQuery(offset=key.start, limit=(key.stop-key.start))
            # convert the iterator to a list since len() needs to be defined
            return list(self)
        else:
            raise NotImplementedError("This class only supports __getitem__ via slicing")

    def _castRow(self, row):
        """Convert a row of data to the appropriate types"""
        better_row = []
        for val, col in zip(row, self.cols):
            # convert Geom types to GEOSGeometry
            if col['type'] == ColumnTypes.GEOMETRY:
                val = GEOSGeometry(val)
            better_row.append(val)
        return better_row

    def _fetchRowsForQuery(self, limit=None, offset=None):
        """Actually execute the query defined by `self._sql` with the optional
        limit and offset"""
        # we want to execute this query with the readonly DB user to prevent
        # the most harmful SQL injection
        self._cursor = connections['readonly'].cursor()
        sql = self._sql
        if not (limit == offset == None):
            # tack on the offset and limit
            sql += " LIMIT %s OFFSET %s"
            self._cursor.execute(sql, self._params + (limit, offset))
        else:
            self._cursor.execute(sql, self._params)

from .models import ColumnTypes
