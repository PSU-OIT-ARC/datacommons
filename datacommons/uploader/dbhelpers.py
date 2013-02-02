import uuid
import os
import re
import csv
from collections import defaultdict
from django.conf import settings as SETTINGS
from django.db import connection, transaction
from .models import ColumnTypes

def isSaneName(value):
    """Return true if value is a valid identifier"""
    return value == sanitize(value) and len(value) >= 1 and re.search("^[a-z]", value)

def sanitize(value):
    """Strip out bad characters from value"""
    value = value.lower()
    return re.sub(r'[^a-z_0-9]', '', value)

def getDatabaseMeta():
    """Returns a dict with keys as the schema name, and values as a dict with
    keys as table names, and values as a list of dicts with {type, type_label,
    name}. Basically it returns the topology of the entire database"""
    sql = """
        SELECT 
            schema_name, 
            tables.table_name,
            column_name,
            data_type
        FROM 
            information_schema.schemata 
        LEFT JOIN 
            information_schema.tables 
        ON 
            table_schema = schema_name 
        LEFT JOIN
            information_schema.columns
        ON
            tables.table_name = columns.table_name
            AND
            tables.table_schema = columns.table_schema
            AND column_name != 'id'
        WHERE
            schema_name NOT LIKE 'pg_%%' AND 
            schema_name != 'information_schema';
    """
    cursor = connection.cursor()
    cursor.execute(sql)
    meta = {}
    for row in cursor.fetchall():
        schema, table, column, data_type = row
        if schema not in meta:
            meta[schema] = {}

        if table:
            if table not in meta[schema]:
                meta[schema][table] = []
            type_id = ColumnTypes.fromPGTypeName(data_type)
            meta[schema][table].append({
                "name": column, 
                "type": type_id,
                "type_label": ColumnTypes.toString(type_id),
            })
    return meta

def getColumnsForTable(schema, table):
    """Return a list of columns in schema.table"""
    meta = getDatabaseMeta()
    return meta[schema][table]

def createTable(schema_name, table_name, column_names, column_types, commit=False):
    """Create a table in schema_name named table_name, with columns named
    column_names, with types column_types. Automatically creates a primary
    key for the table"""
    # santize all the names
    schema_name = sanitize(schema_name)
    table_name = sanitize(table_name)
    # sanitize and put quotes around the columns
    names = []
    for name in column_names:
        names.append('"' + sanitize(name) + '"')
    column_names = names

    # get all the column type names
    types = []
    for type in column_types:
        types.append(ColumnTypes.toPGType(int(type)))

    # build up part of the query
    sql = []
    for i in range(len(column_names)):
        sql.append(column_names[i] + " " + types[i])
    sql = ",".join(sql)

    # sure hope this is SQL injection proof
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

