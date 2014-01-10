import json
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.db import DatabaseError
from datacommons.utils.dbhelpers import (
    fetchRowsFor,
    getDatabaseTopology,
    SQLHandle,
    sanitizeSelectSQL
)
from datacommons.schemas.models import ColumnTypes, Table, TablePermission, Version, View
from .forms import CreateViewForm
from datacommons.jsonencoder import JSONEncoder

def build(request):
    meta = getDatabaseTopology(owner=request.user)
    # filter out all views not owned by this user
    for schema in meta:
        schema.views = [v for v in schema.views if getattr(v, 'owner_id') == request.user.pk]

    return render(request, "querybuilder/build.html", {
        "schemata": json.dumps(meta, cls=JSONEncoder),
    })


def preview(request, sql):
    # make sure the sql is valid
    try:
        sql = sanitizeSelectSQL(sql)
    except ValueError as e:
        return render(request, "querybuilder/preview.html", {
            "error": str(e),
            "sql": sql,
        })

    # if we are here, we can assume the SQL is safe (hopefully!)
    q = SQLHandle(sql)
    paginator = Paginator(q, 100)
    error = None
    rows = None

    page = request.GET.get("page")
    cols = []
    try:
        try:
            rows = paginator.page(page)
        except PageNotAnInteger:
            rows = paginator.page(1)
        except EmptyPage:
            rows = paginator.page(paginator.num_pages)
    except DatabaseError as e:
        error = str(e)
    else:
        cols = q.cols


    if request.POST:
        form = CreateViewForm(request.POST, user=request.user)
        if form.is_valid():
            view = form.save()
            messages.success(request, "View created!")
            return HttpResponseRedirect(reverse("schemas-show", args=(view.schema, view.name)))
    else:
        form = CreateViewForm(user=request.user)

    return render(request, "querybuilder/preview.html", {
        "rows": rows,
        "cols": cols,
        "error": error,
        "sql": sql,
        "form": form,
    })

