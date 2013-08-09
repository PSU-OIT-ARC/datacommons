import json
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from ..models.dbhelpers import (
    fetchRowsFor,
    getDatabaseMeta,
    getColumnsForTable,
)
from ..models import ColumnTypes, Table, TablePermission, Version
from ..forms.schemas import PermissionsForm, TablePermissionsForm, CreateSchemaForm

@login_required
def all(request):
    """Display a nested list of all the schemas and tables in the database"""
    schemas = getDatabaseMeta()
    return render(request, "schemas/list.html", {
        "schemas": schemas,
    })

@login_required
def view(request, schema_name, table_name):
    """View the table in schema, including the column names and types"""
    # get all the data
    version_id = request.GET.get("version_id")
    version = None
    try:
        table = Table.objects.get(schema=schema_name, name=table_name)
    except Table.DoesNotExist:
        table = None

    if version_id:
        version = Version.objects.get(pk=version_id) 
        rows, cols = version.fetchRows()
        #version.restore(user=request.user)
    else:
        rows, cols = fetchRowsFor(schema_name, table_name)

    versions = Version.objects.filter(table=table)

    paginator = Paginator(rows, 100)
    page = request.GET.get("page")
    try:
        rows = paginator.page(page)
    except PageNotAnInteger:
        rows = paginator.page(1)
    except EmptyPage:
        rows = paginator.page(paginator.num_pages)

    return render(request, "schemas/view.html", {
        "rows": rows,
        "cols": cols,
        "schema": schema_name,
        "table": table_name,
        "versions": versions,
        "version": version,
    })

@login_required
def create(request):
    # make sure the user has permissions to do the creation
    if not any([request.user.is_authenticated, request.user.is_staff]):
        raise PermissionDenied()

    if request.POST:
        form = CreateSchemaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Schema Created!")
            return HttpResponseRedirect(reverse("schemas-create"))
    else:
        form = CreateSchemaForm()

    return render(request, "schemas/create.html", {
        'form': form,
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
    if request.POST:
        form = TablePermissionsForm(request.POST, table=table)
        if form.is_valid():
            form.save()
            messages.success(request, "Permissions updated")
            return HttpResponseRedirect(reverse("schemas-permissions-detail", args=(table.pk,)))
    else:
        form = TablePermissionsForm(table=table)
    return render(request, "schemas/permissions_detail.html", {
        "table": table,
        "form": form,
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
