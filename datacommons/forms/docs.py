from django import forms
from ..models import DocUpload
from ..models.csvhelpers import handleUploadedCSV, parseCSV, importCSVInto

class DocUploadForm(forms.ModelForm):
    """A simple form to upload any type of document"""
    def __init__(self, *args, **kwargs):
        super(DocUploadForm, self).__init__(*args, **kwargs)
        choices = list(self.fields['source'].choices)
        choices.pop(0)
        self.fields['source'].choices = choices

    class Meta:
        model = DocUpload
        fields = ("description", "file", "source")

