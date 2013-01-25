import uuid
import os
import re
import csv
from django.conf import settings as SETTINGS
from django.db import connection, transaction
from .models import ColumnTypes

def handleUploadedCSV(f):
    allowed_content_types = ['text/csv', 'application/vnd.ms-excel']
    assert(f.content_type in allowed_content_types)
    filename = uuid.uuid4()
    path = os.path.join(SETTINGS.MEDIA_ROOT, str(filename.hex) + ".csv")
    with open(path, 'wb+') as dest:
            for chunk in f.chunks():
                dest.write(chunk)
    return path

def getSchemas():
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

def isSaneName(value):
    return value == sanitize(value) and len(value) >= 1

def sanitize(value):
    return re.sub(r'[^A-Za-z_0-9]', '', value)

def insertCSVInto(filename, schema_name, table_name, column_names, commit=False):
    schema_name = sanitize(schema_name)
    table_name = sanitize(table_name)
    names = []
    for name in column_names:
        names.append(sanitize(name))
    column_names = names

    path = os.path.join(SETTINGS.MEDIA_ROOT, filename)
    cursor = connection.cursor()
    cols = ','.join(column_names)
    escape_string = ",".join(["%s" for i in range(len(column_names))])
    sql = """INSERT INTO "%s"."%s" (%s) VALUES(%s)""" % (schema_name, table_name, cols, escape_string)
    with open(path, 'rb') as csvfile:
        reader = csv.reader(csvfile)
        for i, row in enumerate(reader):
            if i == 0: continue
            # insert the row
            cursor.execute(sql, row)

    if commit:
        transaction.commit_unless_managed()

def createTable(schema_name, table_name, column_names, column_types, commit=False):
    # santize all the names
    schema_name = sanitize(schema_name)
    table_name = sanitize(table_name)
    names = []
    for name in column_names:
        names.append(sanitize(name))
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
    schema = sanitize(schema)
    table = sanitize(table)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM "%s"."%s\"""" % (schema, table))
    return cursor.fetchall()

