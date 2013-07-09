import os
import re
import json
from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from ..models.dbhelpers import (
    getDatabaseMeta,
    getColumnsForTable,
)
from ..models import ColumnTypes, CSVUpload
from ..forms.shapefiles import ShapefileUploadForm, ShapefilePreviewForm

@login_required
def upload(request):
    """Display the shapefile upload form"""
    schemas = getDatabaseMeta()
    errors = {}
    if request.POST:
        form = ShapefileUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            # save state and move to the preview
            row = form.save()
            return HttpResponseRedirect(reverse("shapefile-preview") + "?upload_id=" + str(row.pk))
    else:
        form = ShapefileUploadForm(user=request.user)

    schemas_json = json.dumps(schemas)
    return render(request, 'shapefile/upload.html', {
        "schemas": schemas,
        "schemas_json": schemas_json,
        "errors": errors,
        "CSVUpload": CSVUpload,
        "form": form,
    })

@login_required
def preview(request):
    """Finalize the shapefile upload"""
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    # authorized to view this upload?
    if upload.user.pk != request.user.pk:
        raise PermissionDenied()
    if upload.status == upload.DONE:
        raise PermissionDenied()

    error = None
    
    if request.POST:
        form = ShapefilePreviewForm(request.POST, upload=upload)
        if form.is_valid():
            try:
                form.save(upload)
            except DatabaseError as e:
                error = str(e)
            else:
                messages.success(request, "You successfully imported the shapefile!")
                return HttpResponseRedirect(reverse('schemas-view', args=(upload.table.schema, upload.table.name)))
    else:
        form = ShapefilePreviewForm(upload=upload)

    # fetch the meta data about the shapfile
    column_names, data, column_types = form.importable.parse()
    # grab the columns from the existing table
    if upload.mode == CSVUpload.APPEND:
        existing_columns = getColumnsForTable(upload.table.schema, upload.table.name)
    else:
        existing_columns = None

    available_types = ColumnTypes.TO_HUMAN

    return render(request, "shapefile/preview.html", {
        'data': data,
        'upload': upload,
        'error': error,
        'existing_columns': existing_columns,
        'existing_columns_json': json.dumps(existing_columns),
        'pretty_type_name': json.dumps(available_types),
        'form': form,
    })
