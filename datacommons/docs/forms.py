from django import forms
from .models import DocUpload
from datacommons.utils.forms import BetterModelForm

class DocUploadForm(BetterModelForm):
    """A simple form to upload any type of document"""
    def __init__(self, *args, **kwargs):
        super(DocUploadForm, self).__init__(*args, **kwargs)
        choices = list(self.fields['source'].choices)
        choices.pop(0)
        self.fields['source'].choices = choices

    class Meta:
        model = DocUpload
        fields = ("description", "file", "source")

