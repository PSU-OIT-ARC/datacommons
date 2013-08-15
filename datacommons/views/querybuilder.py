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
from ..forms.querybuilder import ChooseTablesForm, JoinForm

def build(request):
    if request.POST:
        form = ChooseTablesForm(request.POST)
        if form.is_valid():
            request.session['tables_form'] = form.cleaned_data
            return HttpResponseRedirect(reverse("querybuilder-join"))
    else:
        form = ChooseTablesForm(initial=request.session.get("tables_form"))

    meta = getDatabaseMeta()
    return render(request, "querybuilder/build.html", {
        "form": form,
        "schemata": json.dumps(meta),
    })

def join_(request):
    if request.POST:
        form = JoinForm(request.POST, tables=request.session['tables_form'])
        if form.is_valid():
            return HttpResponse("foo")
    else:
        form = JoinForm(tables_form=request.session['tables_form'])
    return render(request, "querybuilder/join.html", {
        "form": form,
    })
