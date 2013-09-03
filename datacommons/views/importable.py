import os
import re
import json
from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.views.generic.base import View
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from ..models.dbhelpers import (
    getDatabaseTopology,
    getColumnsForTable,
)
from ..models import ColumnTypes, ImportableUpload
from ..forms.shapefiles import ShapefileUploadForm, ShapefilePreviewForm
from datacommons.jsonencoder import JSONEncoder

def upload(request, form_class, template_name, redirect_to):
    schemas = getDatabaseTopology()
    errors = {}
    if request.POST:
        form = form_class(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            # save state and move to the preview
            row = form.save()
            return HttpResponseRedirect(reverse(redirect_to) + "?upload_id=" + str(row.pk))
    else:
        form = form_class(user=request.user)

    schemas_json = json.dumps(schemas, cls=JSONEncoder)
    return render(request, template_name, {
        "schemas": schemas,
        "schemas_json": schemas_json,
        "errors": errors,
        "ImportableUpload": ImportableUpload,
        "form": form,
    })

def preview(request, form_class, template_name):
    """Finalize the shapefile upload"""
    upload = ImportableUpload.objects.get(pk=request.REQUEST['upload_id'])
    # authorized to view this upload?
    if upload.user.pk != request.user.pk:
        raise PermissionDenied()
    if upload.status == upload.DONE:
        raise PermissionDenied()

    error = None
    
    if request.POST:
        form = form_class(request.POST, upload=upload)
        if form.is_valid():
            try:
                form.save(upload)
            except DatabaseError as e:
                error = str(e)
            else:
                messages.success(request, "You successfully imported the file!")
                return HttpResponseRedirect(reverse('schemas-view', args=(upload.table.schema, upload.table.name)))
    else:
        form = form_class(upload=upload)

    # fetch the meta data about the shapfile
    column_names, data, column_types = form.importable.parse()
    # grab the columns from the existing table
    if upload.mode == ImportableUpload.APPEND:
        existing_columns = getColumnsForTable(upload.table.schema, upload.table.name)
    else:
        existing_columns = []

    name_to_human_type = dict((col.name, ColumnTypes.toString(col.type)) for col in existing_columns)

    return render(request, template_name, {
        'data': data,
        'upload': upload,
        'error': error,
        'col_name_to_human_type_json': json.dumps(name_to_human_type),
        'form': form,
    })
