from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from ..models.dbhelpers import (
    fetchRowsFor,
    getDatabaseMeta,
    getColumnsForTable,
)
from ..models import ColumnTypes, Table

@login_required
def all(request):
    """Display a nested list of all the schemas and tables in the database"""
    schemas = getDatabaseMeta()
    return render(request, "schemas/list.html", {
        "schemas": schemas,
    })

@login_required
def view(request, schema, table):
    """View the table in schema, including the column names and types"""
    # get all the data
    rows, cols = fetchRowsFor(schema, table)
    # create a list of column names, and human readable type labels
    # to display on the table header
    cols = [
    {
        "name": t.name, 
        "type_label": ColumnTypes.toString(ColumnTypes.fromPGCursorTypeCode(t.type_code))
    } for t in cols]

    return render(request, "schemas/view.html", {
        "rows": rows,
        "cols": cols,
        "schema": schema,
        "table": table,
    })

@login_required
def permissions(request):
    groups = Table.objects.groupedBySchema(owner=request.user)
    
    return render(request, "schemas/permissions.html", {
        "groups": groups,
    })
