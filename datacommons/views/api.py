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
from ..models.dbhelpers import fetchRowsFor
from ..models import Version

def view(request, schema, table, format):
    """View the table in schema, including the column names and types"""
    # get all the data
    version_id = request.GET.get("version_id")
    if version_id:
        version = Version.objects.get(pk=version_id) 
        pageable = version.fetchRows()
    else:
        pageable = fetchRowsFor(schema, table)

    response = HttpResponse()
    cols = pageable.cols
    if format == "csv":
        response['Content-Type'] = 'text/csv'
        writer = UnicodeWriter(response)
        writer.writerow([col['name'] for col in cols])
        for row in pageable:
            writer.writerow([unicode(c) for c in row])
    elif format == "json":
        response['Content-Type'] = 'application/json'
        data = []
        for row in pageable:
            data.append(dict([(col['name'], cell) for col, cell in zip(cols, row)]))
        json.dump(data, response, cls=JSONEncoder)

    return response 

