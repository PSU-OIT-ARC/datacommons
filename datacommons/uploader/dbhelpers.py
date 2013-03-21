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
    value = value.lower().strip()
    value = re.sub(r'\s+', '_', value).strip('_')
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
            pg_namespace.nspowner != 10;
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
                    raise ValueError("Table '%s.%s' has a column of type '%s' which is not supported" % (schema_name, table_name, data_type))
                meta[schema_name][table_name].append({
                    "name": column, 
                    "type": type_id,
                    "type_label": ColumnTypes.toString(type_id),
                })
    return meta

def getColumnsForTable(schema, table):
    """Return a list of columns in schema.table"""
    meta = getDatabaseMeta()
    return meta[schema][table]

def createTable(schema_name, table_name, column_names, column_types, primary_keys, commit=False):
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
    sql = []
    for i in range(len(column_names)):
        sql.append(column_names[i] + " " + types[i])
    sql = ",".join(sql)

    # sure hope this is SQL injection proof
    sql = """
        CREATE TABLE "%s"."%s" (
            %s
        );
    """ % (schema_name, table_name, sql)
    cursor = connection.cursor()
    cursor.execute(sql)
    # add the primary key, if there is one
    if len(primary_keys):
        sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (schema_name, table_name, ",".join(primary_keys))
        cursor.execute(sql)

    # run morgan's fancy proc
    cursor.execute("SELECT dc_set_perms(%s, %s);", (schema_name, table_name))

    if commit:
        transaction.commit_unless_managed()

def fetchRowsFor(schema, table):
    """Return a 2-tuple of the rows in schema.table, and the cursor description"""
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM "%s"."%s\"""" % (schema, table))
    return cursor.fetchall(), cursor.description

