import decimal
import os
import re
import json
from datacommons.jsonencoder import JSONEncoder
from datacommons.unicodecsv import UnicodeWriter
from django.conf import settings as SETTINGS
from django.contrib.gis.geos import GEOSGeometry
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.db import DatabaseError, transaction, DatabaseError, connection, connections
from django.core.exceptions import PermissionDenied
from ..models.dbhelpers import fetchRowsFor, fetchRowsForQuery
from ..models import Version

def query(request):
    # this is totally insecure
    sql = request.GET['sql']
    truncate_geoms = 'truncate_geoms' in request.GET
    truncate_geoms = True

    try:
        limit = int(request.GET['limit'])
    except KeyError, ValueError:
        limit = 100

    try:
        offset = int(request.GET['offset'])
    except KeyError, ValueError:
        offset = 0

    try:
        (rows, cols), length = fetchRowsForQuery(sql, limit, offset)
    except DatabaseError as e:
        return HttpResponse(json.dumps({"success": False, "error": str(e)}))

    response = HttpResponse()
    response['Content-Type'] = 'application/json'
    obj = {
        "success": True,
        "length": length,
        "limit": limit,
        "offset": offset,
        "rows": rows,
        "cols": cols
    }
    # the geom is assumed to be the last row
    if truncate_geoms:
        rows = obj['rows']
        if len(rows) != 0: 
            for row in rows:
                for c, col in enumerate(row):
                    if isinstance(col, GEOSGeometry):
                        # there's a faster way to do this
                        row[c] = str(col).split(" ")[0]


    json.dump(obj, response, cls=JSONEncoder)
    return response

def view(request, schema, table, format):
    """View the table in schema, including the column names and types"""
    # get all the data
    version_id = request.GET.get("version_id")
    if version_id:
        version = Version.objects.get(pk=version_id) 
        rows, cols = version.fetchRows()
    else:
        rows, cols = fetchRowsFor(schema, table)

    response = HttpResponse()
    if format == "csv":
        response['Content-Type'] = 'text/csv'
        writer = UnicodeWriter(response)
        writer.writerow([col['name'] for col in cols])
        for row in rows:
            writer.writerow([unicode(c) for c in row])
    elif format == "json":
        response['Content-Type'] = 'application/json'
        data = []
        for row in rows:
            data.append(dict([(col['name'], cell) for col, cell in zip(cols, row)]))
        json.dump(data, response, cls=JSONEncoder)

    return response 

