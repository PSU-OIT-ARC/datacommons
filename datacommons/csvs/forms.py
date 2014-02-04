from .models import CSVImport
from datacommons.importable.forms import ImportableUploadForm, ImportablePreviewForm

class CSVUploadForm(ImportableUploadForm):
    MODEL = CSVImport 

class CSVPreviewForm(ImportablePreviewForm):
    MODEL = CSVImport 
