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
from django.contrib import messages
from ..models.dbhelpers import (
    getColumnsForTable,
    getDatabaseTopology,
)
from ..models import ColumnTypes, ImportableUpload
from ..forms.csvs import ImportableUploadForm, CSVPreviewForm
from datacommons.jsonencoder import JSONEncoder
from .importable import upload as upload_view, preview as preview_view

@login_required
def upload(request):
    """Display the CSV upload form"""
    return upload_view(request, ImportableUploadForm, 'csv/upload.html', 'csv-preview')

@login_required
def preview(request):
    """Finalize the CSV upload"""
    return preview_view(request, CSVPreviewForm, 'csv/preview.html')
