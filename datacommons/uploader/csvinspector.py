import re
import csv
import uuid
import os
from django.conf import settings as SETTINGS
from .models import ColumnTypes
from .helpers import sanitize

def parseCSV(filename):
    rows = []
    max_rows = 10
    # read in the first few rows
    path = os.path.join(SETTINGS.MEDIA_ROOT, filename)
    with open(path, 'rb') as csvfile:
        reader = csv.reader(csvfile)
        for i, row in enumerate(reader):
            if i < max_rows:
                rows.append(row)
            else:
                break

    header = sanitizeColumnNames(rows[0])
    data = rows[1:]
    types = inferColumnTypes(data)
    type_names = [ColumnTypes.toString(type) for type in types]
    return header, data, types, type_names

# helpers for parseCsv
def sanitizeColumnNames(row):
    header = []
    for name in row:
        header.append(sanitize(name))
        
    return header

def inferColumnType(rows, column_index):
    data = []
    for row_index in range(len(rows)):
        data.append(rows[row_index][column_index])

    # try to deduce the column type
    # is char?
    for val in data:
        # purposefully exlcuding e and E because we want to exclude numbers like 5.5e10
        if re.search(r'[A-DF-Za-df-z]', val):
            return ColumnTypes.CHAR

    # is timestamp?
    for val in data:
        if re.search(r'[:]', val):
            # if the value is longer than "2012-05-05 08:01:01" it probably
            # has a timezone appended to the end
            if len(val) > len("2012-05-05 08:01:01"):
                return ColumnTypes.TIMESTAMP_WITH_ZONE
            else:
                return ColumnTypes.TIMESTAMP

    # is numeric?
    for val in data:
        if re.search(r'[.e]', val):
            return ColumnTypes.NUMERIC

    # ...must be an int
    return ColumnTypes.INTEGER

def inferColumnTypes(rows):
    types = []
    number_of_columns = len(rows[0])
    for i in range(number_of_columns):
        types.append(inferColumnType(rows, i))
    return types
