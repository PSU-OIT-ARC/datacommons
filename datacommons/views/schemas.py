import json
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.db.models import Q
from ..models.dbhelpers import (
    fetchRowsFor,
    getDatabaseMeta,
    getColumnsForTable,
)
from ..models import ColumnTypes, Table, TablePermission
from ..forms.schemas import PermissionsForm

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
    form = PermissionsForm(user=request.user)
    
    return render(request, "schemas/permissions.html", {
        "groups": groups,
        "form": form,
    })


@login_required
def permissionsDetail(request, table_id):
    user = request.user
    table = get_object_or_404(Table, table_id=table_id, owner=user)
    grid = table.permissionGrid()
    return render(request, "schemas/permissions_detail.html", {
        "table": table,
        "grid": grid,
    });

@login_required
def users(request):
    username = request.GET.get("term", "")
    users = User.objects.filter(
        Q(username__startswith=username) |
        Q(first_name__startswith=username) |
        Q(last_name__startswith=username)
    )[:10]
    return HttpResponse(json.dumps([{
        "username": u.username,
        "first_name": u.first_name,
        "last_name": u.last_name,
    } for u in users]))

@login_required
def grant(request):
    form = PermissionsForm(request.POST, user=request.user)
    if not form.is_valid():
        response = {"errors": form.errors, "success": False}
        return HttpResponse(json.dumps(response))

    form.save()
    return HttpResponse(json.dumps({"success": True}))
