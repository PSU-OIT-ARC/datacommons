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

def getDatabaseMeta():
    """Returns a dict with keys as the schema name, and values as a dict with
    keys as table names, and values as a list of dicts with {type, type_label,
    name}. Basically it returns the topology of the entire database"""
    sql = """
        SELECT 
            nspname, 
            tablename 
        FROM 
            pg_namespace
        LEFT JOIN 
            pg_tables 
        ON pg_namespace.nspname = pg_tables.schemaname
        WHERE 
            pg_namespace.nspowner != 10 AND nspname != 'geometries'
    """
    cursor = connection.cursor()
    cursor.execute(sql)
    # meta is a dict, containing dicts, which hold lists, which hold dicts
    meta = {}
    for row in cursor.fetchall():
        schema, table = row
        if schema not in meta:
            meta[schema] = {}

        if table and table not in meta[schema]:
            meta[schema][table] = []

    # grab all the columns from every table with mharvey's stored proc
    # have to run a query in a loop because of the way the proc works
    for schema_name, tables in meta.items():
        for table_name in tables:
            cursor.execute("""
                SELECT 
                    column_name, 
                    column_type 
                FROM 
                    dc_get_table_metadata(%s, %s)
            """, (schema_name, table_name))
            for row in cursor.fetchall():
                column, data_type = row
                try:
                    type_id = ColumnTypes.fromPGTypeName(data_type)
                except KeyError:
                    #raise ValueError("Table '%s.%s' has a column of type '%s' which is not supported" % (schema_name, table_name, data_type))
                    continue
                meta[schema_name][table_name].append({
                    "name": column, 
                    "type": type_id,
                    "type_label": ColumnTypes.toString(type_id),
                })

    # tack on the primary key info
    pks = getPrimaryKeys()
    for schema in pks:
        for table in pks[schema]:
            for col in meta.get(schema, {}).get(table, []):
                col['pk'] = col['name'] in pks[schema][table]

    return meta

def addGeometryColumn(schema_name, table_name, srid, type, commit=False):
    cursor = connection.cursor()
    cursor.execute("""SELECT AddGeometryColumn(%s, %s, %s, %s, %s, 2)""",
        (schema_name, table_name, "the_geom", srid, type))

    if commit:
        transaction.commit_unless_managed()

def getPrimaryKeys():
    """
    Return a dict of dicts of sets where the keys are the schema name, the
    table name, and the value is a set of columns which are the primary key of
    `schema.table`
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT 
            tc.table_schema, 
            tc.table_name, 
            tc.constraint_type, 
            column_name 
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
    """)
    data = defaultdict(lambda: defaultdict(set))
    for row in cursor.fetchall(): 
        schema, table, constraint_type, column_name = row
        data[schema][table].add(column_name)

    return data

def getPrimaryKeysForTable(schema, table):
    """
    Returns a set of the column names in `schema.table` that are primary keys
    """
    return getPrimaryKeys()[schema][table]

def getColumnsForTable(schema, table):
    """Return a list of columns in schema.table"""
    meta = getDatabaseMeta()
    return meta[schema][table]

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
    cursor.execute('''SELECT %s FROM "%s"."%s" ORDER BY %s''' % (column_str, schema, table, pk_string))
    return coerceRowsAndParseColumns(cursor.fetchall(), cursor.description)

def fetchRowsForQuery(sql, limit, offset):
    # get the total number of rows
    cursor = connections['readonly'].cursor()
    cursor.execute(sql)
    length = cursor.rowcount

    sql += " LIMIT %s OFFSET %s"
    cursor.execute(sql, (limit, offset))

    return coerceRowsAndParseColumns(cursor.fetchall(), cursor.description), length

def coerceRowsAndParseColumns(rows, desc):
    cols = [
    {
        "name": t.name, 
        "type_label": ColumnTypes.toString(ColumnTypes.fromPGCursorTypeCode(t.type_code)),
        "type": ColumnTypes.fromPGCursorTypeCode(t.type_code)
    } for t in desc]
    has_geom = any(ColumnTypes.fromPGCursorTypeCode(t.type_code) == ColumnTypes.GEOMETRY for t in desc)

    if not has_geom:
        return rows, cols

    better_rows = []
    for row in rows:
        better_row = []
        for val, col in zip(row, cols):
            better_row.append(val if col['type'] != ColumnTypes.GEOMETRY else GEOSGeometry(val))
        better_rows.append(better_row)

    return better_rows, cols

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

from .models import ColumnTypes
