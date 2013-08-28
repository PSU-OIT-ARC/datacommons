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
from ..models.dbhelpers import (
    fetchRowsFor,
    getDatabaseMeta,
    getColumnsForTable,
    SQLInfo
)
from ..models import ColumnTypes, Table, TablePermission, Version
from ..forms.querybuilder import CreateViewForm

def build(request):
    if request.POST:
        form = CreateViewForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponse(json.dumps({"success": True}))
        return HttpResponse(json.dumps({"success": False, "errors": form.errors}))
    else:
        form = CreateViewForm()

    meta = getDatabaseMeta()
    return render(request, "querybuilder/build.html", {
        "form": form,
        "schemata": json.dumps(meta),
    })

def preview(request, sql):
    q = SQLInfo(sql)
    paginator = Paginator(q, 100)
    error = None
    rows = None

    page = request.GET.get("page")
    try:
        try:
            rows = paginator.page(page)
        except PageNotAnInteger:
            rows = paginator.page(1)
        except EmptyPage:
            rows = paginator.page(paginator.num_pages)
    except DatabaseError as e:
        error = str(e)


    return render(request, "querybuilder/preview.html", {
        "rows": rows,
        "cols": q.cols,
        "error": error,
        "sql": sql,
    })

