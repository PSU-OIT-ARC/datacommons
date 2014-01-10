from .models import CSVImport
from datacommons.utils.forms import ImportableUploadForm, ImportablePreviewForm

class CSVUploadForm(ImportableUploadForm):
    MODEL = CSVImport 

class CSVPreviewForm(ImportablePreviewForm):
    MODEL = CSVImport 
