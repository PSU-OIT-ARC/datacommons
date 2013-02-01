import os
from django import forms
from django.forms.widgets import RadioSelect
from dbhelpers import getDatabaseMeta
from models import CSVUpload
from csvhelpers import handleUploadedCSV, parseCSV
from dbhelpers import getColumnsForTable

class CSVUploadForm(forms.Form):
    MODES = (
        (CSVUpload.CREATE, "create a new table"), 
        (CSVUpload.APPEND, "append to an existing table")
    )

    schema = forms.ChoiceField(widget=forms.Select)
    mode = forms.ChoiceField(choices=MODES, widget=forms.RadioSelect)
    table = forms.ChoiceField(widget=forms.Select, required=False)
    file = forms.FileField(label="Upload a CSV")

    def __init__(self, *args, **kwargs):
        super(CSVUploadForm, self).__init__(*args, **kwargs)

        # get all the schemas from the db
        self.db_meta = getDatabaseMeta()
        self.fields['schema'].choices = [("", "")] + [(name, name) for name in self.db_meta]
        tables = [("", "")]
        for x, table in self.db_meta.items():
            for name, x in table.items():
                if name:
                    tables.append((name, name))
        self.fields['table'].choices = tables

    def clean_schema(self):
        schema = self.cleaned_data['schema']
        if schema == "":
            raise ValidationError("Select a schema!")
        
        return schema

    def clean_mode(self):
        return int(self.cleaned_data['mode']) # why isn't this done for me?

    def clean(self):
        cleaned_data = super(CSVUploadForm, self).clean()
        # check if the table they chose exists (in append mode)
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        if mode == CSVUpload.APPEND:
            if schema in self.db_meta and table not in self.db_meta[schema]:
                self._errors['mode'] = self.error_class(['Choose a table!'])
                try:
                    del cleaned_data['mode']
                except KeyError:
                    pass # who cares

        # attempt an upload
        file = self.cleaned_data.get("file", None)
        self.path = None
        if len(self._errors) == 0 and file is not None:
            try:
                self.path = handleUploadedCSV(file)
            except TypeError as e:
                self._errors['file'] = self.error_class([str(e)])
                del cleaned_data['file']

        # if the upload was successful, and the mode is append, make sure there
        # are the right amount of columns
        if len(self._errors) == 0 and mode == CSVUpload.APPEND:
            existing_columns = getColumnsForTable(schema, table)
            header, data, types, type_names = parseCSV(os.path.basename(self.path))
            if len(existing_columns) != len(header):
                self._errors['file'] = self.error_class(["The number of columns in the CSV you selected does not match the number of columns in the table you selected"])
                del cleaned_data['file']

        return cleaned_data
