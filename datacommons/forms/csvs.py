from ..models.importable import CSVImport
from .importable import ImportableUploadForm, ImportablePreviewForm

class ImportableUploadForm(ImportableUploadForm):
    """This is the initial form displayed to upload a CSV"""
    IMPORTABLE = CSVImport 

class CSVPreviewForm(ImportablePreviewForm):
    IMPORTABLE = CSVImport 
