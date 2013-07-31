import os
import datetime
from django import forms
from django.forms.widgets import RadioSelect
from django.db import DatabaseError
from ..models import CSVUpload, ColumnTypes, Table
from ..models.importable import CSVImport
from ..models.dbhelpers import getColumnsForTable, sanitize, isSaneName, getPrimaryKeysForTable, createTable, getDatabaseMeta
from .importable import ImportableUploadForm, ImportablePreviewForm

class CSVUploadForm(ImportableUploadForm):
    """This is the initial form displayed to upload a CSV"""
    IMPORTABLE = CSVImport 

class CSVPreviewForm(ImportablePreviewForm):
    IMPORTABLE = CSVImport 
