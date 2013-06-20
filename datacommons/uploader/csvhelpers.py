import re
import uuid
import os
from django.conf import settings as SETTINGS
from django.db import connection, transaction, DatabaseError
from .models import ColumnTypes, CSVUpload
from .dbhelpers import sanitize, getPrimaryKeysForTable
from datacommons.unicodecsv import UnicodeReader

ALLOWED_CONTENT_TYPES = [
    'text/csv', 
    'application/vnd.ms-excel', 
    'text/comma-separated-values',
]

def parseCSV(filename):
    """Parse a CSV and return the header row, some of the data rows and
    inferred data types"""
    rows = []
    max_rows = 10
    # read in the first few rows, and save to a buffer.
    # Continue reading to check for any encoding errors
    path = os.path.join(SETTINGS.MEDIA_ROOT, filename)
    with open(path, 'r') as csvfile:
        reader = UnicodeReader(csvfile)
        try:
            for i, row in enumerate(reader):
                if i < max_rows:
                    rows.append(row)
        except UnicodeDecodeError as e:
            # tack on the line number to the exception so the caller can know
            # which line the error was on. The +2 is because i starts at 0, *and*
            # i in not incremented when the exception is thrown
            e.line = (i + 2)
            raise

    header = [sanitize(c) for c in rows[0]]
    data = rows[1:]
    types = inferColumnTypes(data)
    return header, data, types

def handleUploadedCSV(f):
    """Write a CSV to the media directory"""
    if f.content_type not in ALLOWED_CONTENT_TYPES:
        raise TypeError("Not a CSV! It is '%s'" % (f.content_type))

    filename = uuid.uuid4()
    path = os.path.join(SETTINGS.MEDIA_ROOT, str(filename.hex) + ".csv")
    with open(path, 'wb+') as dest:
            for chunk in f.chunks():
                dest.write(chunk)
    return path

def importCSVInto(filename, schema_name, table_name, column_names, column_name_to_column_index, mode, commit=False):
    """Read a CSV and insert into schema_name.table_name"""
    # sanitize everything
    schema_name = sanitize(schema_name)
    table_name = sanitize(table_name)
    names = []
    for name in column_names:
        names.append(sanitize(name))
    column_names = names

    # build the query string for insert
    do_insert = mode in [CSVUpload.CREATE, CSVUpload.APPEND, CSVUpload.UPSERT]
    if do_insert:
        cols = ','.join([n for n in column_names])
        escape_string = ",".join(["%s" for i in range(len(column_names))])
        insert_sql = """INSERT INTO %s.%s (%s) VALUES(%s)""" % (schema_name, table_name, cols, escape_string)

    # build the query string for delete
    do_delete = mode in [CSVUpload.UPSERT, CSVUpload.DELETE]
    if do_delete:
        pks = getPrimaryKeysForTable(schema_name, table_name)
        escape_string = ",".join(["%s = %%s" % pk for pk in pks])
        delete_sql = "DELETE FROM %s.%s WHERE %s" % (schema_name, table_name, escape_string)

    # execute the query string for every row
    path = os.path.join(SETTINGS.MEDIA_ROOT, filename)
    with open(path, 'r') as csvfile:
        reader = UnicodeReader(csvfile)
        for row_i, row in enumerate(reader):
            if row_i == 0: continue # skip header row
            # convert empty strings to null
            for col_i, col in enumerate(row):
                row[col_i] = col if col != "" else None

            if do_delete:
                # remap the primary key columns since the order of the columns in the CSV does not match
                # the order of the columns in the db table
                params = [row[column_name_to_column_index[k]] for k in pks]
                _doSQL(delete_sql, params, "delete", row_i + 1)

            if do_insert:
                # remap the columns since the order of the columns in the CSV does not match
                # the order of the columns in the db table
                params = [row[column_name_to_column_index[k]] for k in column_names]
                _doSQL(insert_sql, params, "insert", row_i + 1)

    if commit:
        transaction.commit_unless_managed()

def _doSQL(sql, params, exception_operation, exception_line):
    """
    helper for importCSVInto(), just runs the sql, with params, and
    generates a nice exception
    """
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
    except DatabaseError as e:
        connection._rollback()
        raise DatabaseError("Tried to %s line %s of the CSV, got this from database: %s. SQL was: %s" % 
            (exception_operation, exception_line, str(e), connection.queries[-1]['sql'])) 

# helpers for parseCsv
def inferColumnType(data):
    # try to deduce the column type
    # int?
    for val in data:
        try:
            val = int(val)
            # http://www.postgresql.org/docs/8.2/static/datatype-numeric.html
            # is the value too big (positive or negative) for postgres?
            if val < -2147483648 or val > +2147483647:
                raise ValueError('Too big')
        except ValueError:
            break
    else:
        return ColumnTypes.INTEGER

    # float?
    for val in data:
        try:
            float(val)
        except ValueError:
            break
    else:
        return ColumnTypes.NUMERIC

    # is timestamp?
    for val in data:
        # timestamps only will contain these chars
        if not re.search(r'^[+: 0-9-]+$', val):
            break
    else:
        # if the value is longer than "2012-05-05 08:01:01" it probably
        # has a timezone appended to the end
        if len(data[0]) > len("2012-05-05 08:01:01"):
            return ColumnTypes.TIMESTAMP_WITH_ZONE
        else:
            return ColumnTypes.TIMESTAMP

    # nothing special
    return ColumnTypes.CHAR

def inferColumnTypes(rows):
    types = []
    number_of_columns = len(rows[0])
    for column_index in range(number_of_columns):
        data = []
        for row_index in range(len(rows)):
            data.append(rows[row_index][column_index])
        types.append(inferColumnType(data))
    return types
