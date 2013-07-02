import os
import datetime
from django import forms
from django.forms.widgets import RadioSelect
from django.db import DatabaseError
from ..models import CSVUpload, ColumnTypes, Table
from ..models.csvhelpers import handleUploadedCSV, parseCSV, importCSVInto
from ..models.dbhelpers import getColumnsForTable, sanitize, isSaneName, getPrimaryKeysForTable, createTable, getDatabaseMeta
from .csvs import CSVUploadForm

class ShapefileUploadForm(CSVUploadForm):
    pass
