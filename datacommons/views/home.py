import os
import re
from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from ..uploader.helpers import (
    handleUploadedCSV, 
    getSchemas, 
    createTable, 
    insertCSVInto, 
    isSaneName,
    fetchRowsFor,
)
from ..uploader.csvinspector import parseCSV
from ..uploader.models import ColumnTypes, CSVUpload

def index(request):
    schemas = getSchemas()
    return render(request, 'home/index.html', {
        "schemas": getSchemas,
    })

def upload(request):
    file = request.FILES['file']
    path = handleUploadedCSV(file)
    filename = os.path.basename(path)
    
    r = CSVUpload()
    r.filename = filename
    r.schema = request.POST['schema']
    r.name = "Nothing"
    r.save()

    return HttpResponseRedirect(reverse("preview") + "?upload_id=" + str(r.pk))

def preview(request):
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    c_names, data, c_types, type_names = parseCSV(upload.filename)
    errors = {}
    if request.POST:
        table = request.POST.get("table", None)
        column_names = request.POST.getlist("column_names")
        column_types = request.POST.getlist("column_types")

        # check sanity of names and column types
        if not isSaneName(table):
            errors['table'] = "Invalid name"
        for i, name in enumerate(column_names):
            if not isSaneName(name):
                errors.setdefault('column_names', {})[i] = "Invalid name"
        for i, id in enumerate(column_types):
            id = int(id)
            column_types[i] = id
            if id not in ColumnTypes.DESCRIPTION:
                errors.setdefault('column_types', {})[i] = "Invalid column type"

        if len(errors) == 0:
            upload.table = table
            upload.save()
            # insert all the data
            createTable(upload.schema, upload.table, column_names, column_types)
            insertCSVInto(upload.filename, upload.schema, upload.table, column_names, commit=True)
            return HttpResponseRedirect(reverse('review') + "?upload_id=" + str(upload.pk))
    else:
        column_names = c_names
        column_types = c_types

    available_types = ColumnTypes.DESCRIPTION

    return render(request, "home/preview.html", {
        'column_names': column_names,
        'data': data,
        'column_types': column_types,
        'type_names': type_names,
        'available_types': available_types,
        'upload_id': upload.pk,
        'errors': errors,
    })

def review(request):
    # need authorization
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    return render(request, "home/review.html", {
        "rows": fetchRowsFor(upload.schema, upload.table)
    })


