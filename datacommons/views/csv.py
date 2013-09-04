from django.contrib.auth.decorators import login_required
from ..forms.csvs import ImportableUploadForm, CSVPreviewForm
from .importable import upload as upload_view, preview as preview_view

@login_required
def upload(request):
    """Display the CSV upload form"""
    return upload_view(request, ImportableUploadForm, 'csv/upload.html', 'csv-preview')

@login_required
def preview(request):
    """Finalize the CSV upload"""
    return preview_view(request, CSVPreviewForm, 'csv/preview.html')
