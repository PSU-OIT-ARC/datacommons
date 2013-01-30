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
from ..uploader.csvhelpers import (
    handleUploadedCSV, 
    insertCSVInto, 
    parseCSV
)
from ..uploader.dbhelpers import (
    isSaneName,
    fetchRowsFor,
    getTablesForAllSchemas,
    getDatabaseMeta,
    getColumnsForTable,
    createTable, 
)
from ..uploader.models import ColumnTypes, CSVUpload

@login_required
def all(request):
    schemas = getDatabaseMeta()
    return render(request, "csv/list.html", {
        "schemas": schemas,
    })

@login_required
def view(request, schema, table):
    rows, cols = fetchRowsFor(schema, table)
    csv_id = request.session.get("csv_id", None)
    upload = None
    if csv_id:
        upload = CSVUpload.objects.get(pk=csv_id)
        del request.session['csv_id']
    return render(request, "csv/view.html", {
        "upload": upload,
        "rows": rows,
        "cols": cols,
        "schema": schema,
        "table": table,
    })

@login_required
def upload(request):
    schemas = getDatabaseMeta()
    errors = {}
    if request.POST:
        # check for errors
        # valid schema?
        schema = request.POST.get('schema', None)
        if schema not in schemas:
            errors['schema'] = "Please choose a schema"

        # valid table (if the mode is append)?
        table = request.POST.get('table', None)
        mode = int(request.POST.get('mode', 0))
        if mode == CSVUpload.CREATE:
            table = None
        elif mode == CSVUpload.APPEND:
            if table not in schemas.get(schema, []):
                errors['table'] = "Please choose a table"
        else:
            errors['mode'] = "Please choose a mode"

        # is there a file?
        file = request.FILES.get('file', None)
        if not file:
            errors['file'] = "Please choose a CSV to upload"

        # everything checked out, so can we upload?
        if len(errors) == 0:
            try:
                path = handleUploadedCSV(file)
            except TypeError as e:
                errors['file'] = str(e)

        if len(errors) == 0:
            # are there enough columns?
            if mode == CSVUpload.APPEND:
                existing_columns = getColumnsForTable(schema, table)
                header, data, types, type_names = parseCSV(os.path.basename(path))
                if len(existing_columns) != len(header):
                    errors['file'] = "The number of columns in the CSV you selected does not match the number of columns in the table you selected"
                    
        if len(errors) == 0:
            # upload was successful so save state, and move to the preview
            filename = os.path.basename(path)
            r = CSVUpload()
            r.filename = filename
            r.schema = schema
            r.table = table
            r.mode = mode
            r.user = request.user
            r.name = "Nothing"
            r.save()

            return HttpResponseRedirect(reverse("csv-preview") + "?upload_id=" + str(r.pk))

    schemas_json = json.dumps(schemas)
    return render(request, 'csv/upload.html', {
        "schemas": schemas,
        "schemas_json": schemas_json,
        "errors": errors,
        "CSVUpload": CSVUpload,
    })

@login_required
def preview(request):
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    if upload.user.pk != request.user.pk:
        raise PermissionDenied()
    if upload.status == upload.DONE:
        raise PermissionDenied()

    # fetch the meta data about the csv
    column_names, data, column_types, type_names = parseCSV(upload.filename)
    # grab the columns from the existing table
    if upload.mode == CSVUpload.APPEND:
        existing_columns = getColumnsForTable(upload.schema, upload.table)
    else:
        existing_columns = None
    errors = {}
    
    if request.POST and upload.mode == upload.CREATE: 
        # this branch is for creating a new table
        # valid table name?
        table = request.POST.get("table", None)
        if not isSaneName(table):
            errors['table'] = "Invalid name"

        # valid column names?
        column_names = request.POST.getlist("column_names")
        for i, name in enumerate(column_names):
            if not isSaneName(name):
                errors.setdefault('column_names', {})[i] = "Invalid name"

        # valid column types?
        column_types = request.POST.getlist("column_types")
        for column_index, column_type_id in enumerate(column_types):
            # convert to an int
            column_type_id = int(column_type_id)
            column_types[column_index] = column_type_id
            if not ColumnTypes.isValidType(column_type_id):
                errors.setdefault('column_types', {})[column_index] = "Invalid column type"

        if len(errors) == 0:
            upload.table = table
            upload.save()
            e = None
            # insert all the data
            try:
                createTable(upload.schema, upload.table, column_names, column_types)
                insertCSVInto(upload.filename, upload.schema, upload.table, column_names, commit=True)
            except DatabaseError as e:
                errors['form'] = str(e)

            if e is None:
                upload.status = upload.DONE
                upload.save()
                request.session['csv_id'] = upload.pk
                return HttpResponseRedirect(reverse('csv-view', args=(upload.schema, upload.table)))

    elif request.POST and upload.mode == upload.APPEND: 
        # branch for appending to a table
        column_names = request.POST.getlist("column_names")
        defined_columns = []
        column_name_to_column_index = {}
        # valid column names?
        for i, name in enumerate(column_names):
            if name == "": continue # truncate the column

            if not isSaneName(name):
                errors.setdefault('column_names', {})[i] = "Invalid name"
            else:
                defined_columns.append(name);
                column_name_to_column_index[name] = i

        if len(errors) == 0:
            # make sure all the columns are defined for the existing table
            existing = [c['name'] for c in existing_columns]
            if set(defined_columns) != set(existing):
                errors['form'] = "Not all columns defined"

            if len(errors) == 0:
                insertCSVInto(
                    upload.filename, 
                    upload.schema, 
                    upload.table, 
                    existing, 
                    commit=True, 
                    column_name_to_column_index=column_name_to_column_index
                )
                upload.status = upload.DONE
                upload.save()
                request.session['csv_id'] = upload.pk
                return HttpResponseRedirect(reverse('csv-view', args=(upload.schema, upload.table)))

    available_types = ColumnTypes.DESCRIPTION

    return render(request, "csv/preview.html", {
        'column_names': column_names,
        'data': data,
        'column_types': column_types,
        'available_types': available_types,
        'upload': upload,
        'errors': errors,
        'existing_columns': existing_columns,
        'existing_columns_json': json.dumps(existing_columns),
        'pretty_type_name': json.dumps(ColumnTypes.DESCRIPTION),
    })

@login_required
def review(request):
    # need authorization
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    rows, cols = fetchRowsFor(upload.schema, upload.table)
    return render(request, "csv/review.html", {
        "upload": upload,
        "rows": rows,
        "cols": cols,
    })


