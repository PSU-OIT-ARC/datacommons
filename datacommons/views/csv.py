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
    getDatabaseMeta,
    getColumnsForTable,
    createTable, 
)
from ..uploader.models import ColumnTypes, CSVUpload
from ..uploader.forms import CSVUploadForm, CSVPreviewForm

@login_required
def all(request):
    """Display a nested list of all the schemas and tables in the database"""
    schemas = getDatabaseMeta()
    return render(request, "csv/list.html", {
        "schemas": schemas,
    })

@login_required
def view(request, schema, table):
    """View the table in schema, including the column names and types"""
    # get all the data
    rows, cols = fetchRowsFor(schema, table)

    # was this CSV *just* modified/created by the user?
    # if so, we will display a message on the template saying the change was successful
    csv_id = request.session.get("csv_id", None)
    upload = None
    if csv_id:
        upload = CSVUpload.objects.get(pk=csv_id)
        # delete the session so the success message doesn't appear again
        del request.session['csv_id']

    # create a list of column names, and human readable type labels
    # to display on the table header
    cols = [
    {
        "name": t.name, 
        "type_label": ColumnTypes.toString(ColumnTypes.fromPGCursorTypeCode(t.type_code))
    } for t in cols]

    return render(request, "csv/view.html", {
        "upload": upload,
        "rows": rows,
        "cols": cols,
        "schema": schema,
        "table": table,
    })

@login_required
def upload(request):
    """Display the CSV upload form"""
    schemas = getDatabaseMeta()
    errors = {}
    if request.POST:
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # save state and move to the preview
            filename = os.path.basename(form.path)
            r = CSVUpload()
            r.filename = filename
            r.schema = form.cleaned_data['schema']
            r.table = form.cleaned_data['table']
            r.mode = form.cleaned_data['mode']
            r.user = request.user
            r.name = "Nothing"
            r.save()
            return HttpResponseRedirect(reverse("csv-preview") + "?upload_id=" + str(r.pk))
        else:
            form.es = form._errors

    else:
        form = CSVUploadForm()

    schemas_json = json.dumps(schemas)
    return render(request, 'csv/upload.html', {
        "schemas": schemas,
        "schemas_json": schemas_json,
        "errors": errors,
        "CSVUpload": CSVUpload,
        "form": form,
    })

@login_required
def preview(request):
    """Finalize the CSV upload"""
    upload = CSVUpload.objects.get(pk=request.REQUEST['upload_id'])
    # authorized to view this upload?
    if upload.user.pk != request.user.pk:
        raise PermissionDenied()
    if upload.status == upload.DONE:
        raise PermissionDenied()

    error = None
    
    if request.POST:
        form = CSVPreviewForm(request.POST, upload=upload)
        if form.is_valid():
            if upload.mode == upload.CREATE: 
                upload.table = form.cleaned_data['table']
                upload.save()

                # build the table and insert all the data
                column_names = form.cleanedColumnNames()
                column_types = form.cleanedColumnTypes()
                primary_keys = form.cleanedPrimaryKeyColumnNames()
                try:
                    createTable(upload.schema, upload.table, column_names, column_types, primary_keys)
                    insertCSVInto(upload.filename, upload.schema, upload.table, column_names, commit=True)
                except DatabaseError as e:
                    error = str(e)
            elif upload.mode == upload.APPEND:
                # insert all the data
                try:
                    insertCSVInto(
                        upload.filename, 
                        upload.schema, 
                        upload.table, 
                        form.cleanedColumnNames(), 
                        commit=True, 
                        column_name_to_column_index=form.mapColumnNameToColumnIndex(),
                    )
                except DatabaseError as e:
                    error = str(e)

            if error == None:
                upload.status = upload.DONE
                upload.save()
                # use a session var to indicate on the next page that the
                # upload was successful
                request.session['csv_id'] = upload.pk
                return HttpResponseRedirect(reverse('csv-view', args=(upload.schema, upload.table)))
    else:
        form = CSVPreviewForm(upload=upload)

    # fetch the meta data about the csv
    column_names, data, column_types = parseCSV(upload.filename)
    # grab the columns from the existing table
    if upload.mode == CSVUpload.APPEND:
        existing_columns = getColumnsForTable(upload.schema, upload.table)
    else:
        existing_columns = None

    available_types = ColumnTypes.TO_HUMAN

    return render(request, "csv/preview.html", {
        'data': data,
        'upload': upload,
        'error': error,
        'existing_columns': existing_columns,
        'existing_columns_json': json.dumps(existing_columns),
        'pretty_type_name': json.dumps(available_types),
        'form': form,
    })
