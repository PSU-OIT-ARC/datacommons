from ..models.importable import CSVImport
from .importable import ImportableUploadForm, ImportablePreviewForm

class CSVUploadForm(ImportableUploadForm):
    MODEL = CSVImport 

class CSVPreviewForm(ImportablePreviewForm):
    MODEL = CSVImport 
