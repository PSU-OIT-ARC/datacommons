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
    getDatabaseTopology,
    SQLHandle
)
from ..models import ColumnTypes, Table, TablePermission, Version
from ..forms.querybuilder import CreateViewForm
from datacommons.jsonencoder import JSONEncoder

def build(request):
    meta = getDatabaseTopology()
    return render(request, "querybuilder/build.html", {
        "schemata": json.dumps(meta, cls=JSONEncoder),
    })


def preview(request, sql):
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
            form.save()
            return HttpResponse(json.dumps({"success": True}))
    else:
        form = CreateViewForm(user=request.user)

    return render(request, "querybuilder/preview.html", {
        "rows": rows,
        "cols": cols,
        "error": error,
        "sql": sql,
        "form": form,
    })

