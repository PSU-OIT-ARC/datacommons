import re
import sqlparse
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

def sanitizeSelectSQL(sql):
    """This is probably not bulletproof, but good enough for now?"""
    SAFE_FUNCTIONS = set("COUNT AVG MAX MIN STDDEV SUM".split())

    try:
        # because the sql might contain multiple statements, only use the first
        # one, and drop the rest
        stmt = sqlparse.parse(sql)[0]
    except IndexError:
        raise ValueError("Not a valid SQL statement")

    if stmt.get_type() != "SELECT":
        raise ValueError("Not a SELECT statement")

    function_names = set()
    i = 0
    expore = [stmt]
    # walk through all the tokens, find the ones that are functions, and add
    # the function name to the list
    while i < len(expore):
        sub_stmt = expore[i]
        for token in sub_stmt.tokens:
            if len(getattr(token, 'tokens', [])) > 0:
                expore.append(token)
            if isinstance(token, sqlparse.sql.Function):
                function_names.add(token.get_name().upper())
        i += 1

    # make sure all the functions being used are safe
    non_safe_functions = function_names - SAFE_FUNCTIONS
    if non_safe_functions != set():
        raise ValueError("You tried to use functions that aren't whitelisted: %s" % ", ".join(non_safe_functions))

    return stmt.to_unicode()

def internalSanitize(value):
    """This differs from sanitize() because it allows names that start or end
    with underscore"""
    value = value.lower().strip()
    return re.sub(r'[^a-z_0-9]', '', value)

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

def getDatabaseTopology(owner=None):
    sql = """
        SELECT
            nspname,
            t.table_name,
            t.table_type,
            c.column_name,
            CASE WHEN c.data_type = 'USER-DEFINED' THEN 'geometry' ELSE c.data_type END AS data_type,
            pks.constraint_type,
            CASE WHEN c.data_type = 'USER-DEFINED' AND t.table_type != 'VIEW' THEN Find_SRID(nspname::varchar, t.table_name::varchar, c.column_name::varchar) ELSE NULL END AS srid
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
            nspname != 'geometries' AND
            nspname != %s
        ORDER BY 
            nspname, table_name, c.ordinal_position
    """
    cursor = connection.cursor()
    cursor.execute(sql, (AUDIT_SCHEMA_NAME,))

    topology = []
    for schema_name, table_name, table_type, column_name, data_type, constraint_type, srid in cursor.fetchall():
        # add the schema object
        if len(topology) == 0 or topology[-1].name != schema_name:
            topology.append(Schema(schema_name))
        schema = topology[-1]

        # this schema has no tables, so move on
        if not table_name: continue

        if table_type == "VIEW":
            if len(schema.views) == 0 or table_name != schema.views[-1].name:
                schema.views.append(View(name=table_name))
                table = schema.views[-1]
        else:
            if len(schema.tables) == 0 or table_name != schema.tables[-1].name:
                schema.tables.append(Table(name=table_name))
                table = schema.tables[-1]

        # this table has no columns, so move on
        if not column_name: continue

        table.columns.append(Column(column_name, ColumnTypes.fromPGTypeName(data_type), constraint_type is not None, srid=srid))

    if owner:
        views = set((v.schema, v.name) for v in TableOrView.objects.filter(owner=owner))
        for schema in topology:
            for v in schema.views + schema.tables:
                if (schema.name, v.name) in views:
                    v.owner = owner
                    v.owner_id = owner.pk

    return topology

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

def fetchRowsFor(schema, table, columns=None):
    """Return a 2-tuple of the rows in schema.table, and the cursor description"""
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    pks = getPrimaryKeysForTable(schema, table)
    pk_string = ",".join([pk.name for pk in pks])
    if columns:
        column_str = ",".join('"%s"' % sanitize(col) for col in columns)
    else:
        column_str = "*"

    if pk_string != "":
        sql = '''SELECT %s FROM "%s"."%s" ORDER BY %s''' % (column_str, schema, table, pk_string)
    else:
        sql = '''SELECT %s FROM "%s"."%s" ''' % (column_str, schema, table)

    return SQLHandle(sql)

class SQLHandle(object):
    """This class wraps up a SQL statement with its parameters and allows it to
    be paginated over efficently, and iterated over"""
    def __init__(self, sql, params=(), privileged=False):
        self._sql = sql
        self._params = params
        self._count = None
        self._cursor = None
        self._cols = None
        self._user = "readonly" if not privileged else "default"

    def count(self):
        """Returns a count of the number of rows returned by the SQL. This method helps make this class Django Paginator compatible""" 
        if self._count == None:
            # construct some SQL that will efficently return the number of rows
            # returned by the SQL 
            cursor = connections[self._user].cursor()
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
                Column(name=t.name, type=ColumnTypes.fromPGCursorTypeCode(t.type_code), is_pk=False)
                for t in self._cursor.description
            ]

        return self._cols

    def __iter__(self):
        """Iterate over all the rows returned by the query"""
        # if the cursor has already been set (like in the `self.cols` method)
        # use that, otherwise execute the query
        if not self._cursor:
            self._fetchRowsForQuery()

        has_geom = any(c.type == ColumnTypes.GEOMETRY for c in self.cols)

        # if there is no geometry column, all the type casting is taken care of
        # automagically by python
        if not has_geom:
            for row in self._cursor:
                yield row
        else:
            # we need to cast the geometry columns in the row to a Geometry type
            for row in self._cursor:
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
            if col.type == ColumnTypes.GEOMETRY:
                val = GEOSGeometry(val)
            better_row.append(val)
        return better_row

    def _fetchRowsForQuery(self, limit=None, offset=None):
        """Actually execute the query defined by `self._sql` with the optional
        limit and offset"""
        self._cursor = connections[self._user].cursor()
        sql = self._sql
        if not (limit == offset == None):
            # tack on the offset and limit
            sql += " LIMIT %s OFFSET %s"
            self._cursor.execute(sql, self._params + (limit, offset))
        else:
            self._cursor.execute(sql, self._params)


from .models import ColumnTypes, AUDIT_SCHEMA_NAME, TableOrView
from .schemata import Schema, View, Table, Column
