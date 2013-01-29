import uuid
import os
import re
import csv
from django.conf import settings as SETTINGS
from django.db import connection, transaction
from .models import ColumnTypes

def isSaneName(value):
    """Return true if value is a valid identifier"""
    return value == sanitize(value) and len(value) >= 1

def sanitize(value):
    """Strip out bad characters from value"""
    return re.sub(r'[^A-Za-z_0-9]', '', value)


def getSchemas():
    """Return a list of schemas in the database"""
    cursor = connection.cursor()
    cursor.execute("""
        SELECT 
            schema_name
        FROM 
            information_schema.schemata 
        WHERE
            schema_name NOT LIKE 'pg_%%' AND 
            schema_name != 'information_schema';
    """)
    schemas = []
    for row in cursor.fetchall():
        schemas.append(row[0])
    
    return schemas

def getTablesForAllSchemas():
    """Return a dict where the key is the schema name, and the value is a list
    of tables in the schema"""
    cursor = connection.cursor()
    cursor.execute("""
        SELECT 
            schema_name, 
            table_name 
        FROM 
            information_schema.schemata 
        LEFT JOIN 
            information_schema.tables 
        ON 
            table_schema = schema_name 
        WHERE
            schema_name NOT LIKE 'pg_%%' AND 
            schema_name != 'information_schema';
    """)
    schemas = {}
    for row in cursor.fetchall():
        schema = row[0]
        table = row[1]
        if table is not None:
            schemas.setdefault(schema, []).append(table)
        else:
            schemas.setdefault(schema, [])

    return schemas

def getColumnsForTable(schema, table):
    """Return a list of columns in schema.table"""
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    sql = """
        SELECT 
            column_name,
            data_type
        FROM 
            information_schema.columns 
        WHERE 
            table_schema = %s AND table_name = %s AND column_name != 'id'
    """
    cursor.execute(sql, (schema, table))
    rows = []
    for row in cursor.fetchall():
        rows.append({"name": row[0], "type": ColumnTypes.pgColumnTypeNameToType(row[1])})
    return rows

def createTable(schema_name, table_name, column_names, column_types, commit=False):
    """Create a table in schema_name named table_name, with columns named
    column_names, with types column_types. Automatically creates a primary
    key for the table"""
    # santize all the names
    schema_name = sanitize(schema_name)
    table_name = sanitize(table_name)
    names = []
    for name in column_names:
        names.append('"' + sanitize(name) + '"')
    column_names = names

    types = []
    for type in column_types:
        types.append(ColumnTypes.toPGType(int(type)))

    sql = []
    for i in range(len(column_names)):
        sql.append(column_names[i] + " " + types[i])
    sql = ",".join(sql)

    # sure how this is SQL injection proof
    sql = """
        CREATE TABLE "%s"."%s" (
            id SERIAL PRIMARY KEY,
            %s
        );
    """ % (schema_name, table_name, sql)
    cursor = connection.cursor()
    cursor.execute(sql)
    if commit:
        transaction.commit_unless_managed()

def fetchRowsFor(schema, table):
    """Return a 2-tuple of the rows in schema.table, and the cursor description"""
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM "%s"."%s\"""" % (schema, table))
    return cursor.fetchall(), cursor.description

