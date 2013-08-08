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
from ..models import DocUpload
from ..forms.docs import DocUploadForm

@login_required
def upload(request):
    errors = {}
    if request.POST:
        form = DocUploadForm(request.POST, request.FILES);
        if form.is_valid():
            doc = form.instance
            doc.user = request.user
            doc.filename = doc.file.name
            doc.save()
            request.session['doc_id'] = doc.pk
            return HttpResponseRedirect(reverse("doc-all"))
    else:
        form = DocUploadForm()

    return render(request, 'doc/upload.html', {
        'errors': errors,
        'form': form,
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

@login_required
def download(request, doc_id):
    """Send a document to download"""
    doc = get_object_or_404(DocUpload, pk=doc_id)
    file = open(os.path.join(SETTINGS.MEDIA_ROOT, doc.file.name), 'rb')
    response = HttpResponse(file.read(), mimetype='application/force-download')
    response['Content-Disposition'] = 'attachment; filename=%s' % doc.filename.encode('ascii', 'ignore')
    return response

