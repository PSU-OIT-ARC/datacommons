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
    getDatabaseTopology,
    getColumnsForTable,
)
from ..models import ColumnTypes, ImportableUpload
from ..forms.shapefiles import ShapefileUploadForm, ShapefilePreviewForm
from datacommons.jsonencoder import JSONEncoder
from .importable import upload as upload_view, preview as preview_view

@login_required
def upload(request):
    return upload_view(request, ShapefileUploadForm, 'shapefile/upload.html', 'shapefile-preview')

@login_required
def preview(request):
    return preview_view(request, ShapefilePreviewForm, 'shapefile/preview.html')
