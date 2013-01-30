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
from ..uploader.dochelpers import handleUploadedDoc
from ..uploader.models import DocUpload

@login_required
def upload(request):
    errors = {}
    if request.POST:
        file = request.FILES.get('file', None)
        if file is None:
            errors['file'] = "Please choose a file to upload"

        if len(errors) == 0:
            path = handleUploadedDoc(file)
            doc = DocUpload()
            doc.name = file.name
            doc.filename = os.path.basename(path)
            doc.user = request.user
            doc.save()
            request.session['doc_id'] = doc.pk
            return HttpResponseRedirect(reverse("doc-all"))

    return render(request, 'doc/upload.html', {
        'errors': errors,
    })

@login_required
def all(request):
    docs = DocUpload.objects.select_related()
    doc = None
    # did the user just upload something? 
    if request.session.get("doc_id", None):
        doc = DocUpload.objects.get(pk=request.session['doc_id'])
        del request.session['doc_id']

    return render(request, 'doc/list.html', {
        'docs': docs,
        'doc': doc,
    })
