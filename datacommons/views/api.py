from __future__ import absolute_import
import decimal
import os
import re
import json
import shapefile
import zipfile
import tempfile
from datacommons.jsonencoder import JSONEncoder
from datacommons.unicodecsv import UnicodeWriter
from django.conf import settings as SETTINGS
from django.contrib.gis.geos import GEOSGeometry
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.db import DatabaseError, transaction, DatabaseError, connection, connections
from django.core.exceptions import PermissionDenied
from ..models.dbhelpers import fetchRowsFor
from ..models import Version, ColumnTypes

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
        writer.writerow([col.name for col in cols])
        for row in pageable:
            writer.writerow([unicode(c) for c in row])
    elif format == "json":
        response['Content-Type'] = 'application/json'
        data = []
        for row in pageable:
            data.append(dict([(col.name, cell) for col, cell in zip(cols, row)]))
        json.dump(data, response, cls=JSONEncoder)
    elif format == "kml":
        response['Content-Type'] = 'application/vnd.google-earth.kml+xml'
        rows = []
        for i, row in enumerate(pageable):
            r = {}
            r['pk'] = ", ".join(item for item, col in zip(row, cols) if col.is_pk)
            r['geom'] = next(item for item, col in zip(row, cols) if col.type == ColumnTypes.GEOMETRY)
            rows.append(r)
        response.write(render_to_string("api/kml.kml", {
            "rows": rows, 
            "schema": schema, 
            "table": table
        }))
    elif format == "zip":
        response['Content-Type'] = 'application/octet-stream'
        # for each non geom column figure out which field to create on the shapefile
        # write all the field values and shape

        for i, row in enumerate(pageable):
            # do all the initialization
            if i == 0:
                cols = pageable.cols
                writer, geom_col_index = _getShapefileWriter(cols, row)

            record = [str(item) for item, col in zip(row, cols) if col.type != ColumnTypes.GEOMETRY]
            writer.record(*record)
            if writer.shapeType == shapefile.POINT:
                writer.point(*(row[geom_col_index].coords))
            else:
                writer.poly(row[geom_col_index].coords)

        shp = tempfile.TemporaryFile()
        dbf = tempfile.TemporaryFile()
        shx = tempfile.TemporaryFile()
        writer.save(shp=shp, dbf=dbf, shx=shx)
        zip_ = tempfile.TemporaryFile()
        z = zipfile.ZipFile(zip_, 'w')

        shp.seek(0)
        z.writestr('%s.shp' % table, shp.read())
        dbf.seek(0)
        z.writestr('%s.dbf' % table, dbf.read())
        shx.seek(0)
        z.writestr('%s.shx' % table, shx.read())
        z.writestr('%s.prj' % table, SETTINGS.OFFICIAL_PRJ)
        z.close()
        zip_.seek(0)
        response.write(zip_.read())

    return response 

def _getShapefileWriter(cols, row):
    geom_type_to_shapefile_type = {
        'Point': shapefile.POINT,
        'LineString': shapefile.POLYLINE,
        'Polygon': shapefile.POLYGON,
        'MultiPoint': shapefile.MULTIPOINT,
        'MultiLineString': shapefile.POLYLINE,
        'MultiPolygon': shapefile.POLYGON,
        None: shapefile.NULL,
    }
    geom_type = None
    # figure out the geom type of the geometry column
    for geom_col_index, col in enumerate(cols):
        # find the index of the first geom column
        if col.type == ColumnTypes.GEOMETRY:
            break

    # get the geom_type of that GEOSGeometry object in the row
    geom_type = row[geom_col_index].geom_type

    # find the geom type
    w = shapefile.Writer(geom_type_to_shapefile_type[geom_type])

    # now add all the columns to the shapefile besides the geom ones
    for col in cols:
        if col.type == ColumnTypes.GEOMETRY:
            continue
        w.field(name=col.name[:10])

    return w, geom_col_index

