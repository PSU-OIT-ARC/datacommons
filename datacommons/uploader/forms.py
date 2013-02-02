import os
from django import forms
from django.forms.widgets import RadioSelect
from dbhelpers import getDatabaseMeta
from models import CSVUpload, ColumnTypes, DocUpload
from csvhelpers import handleUploadedCSV, parseCSV
from dbhelpers import getColumnsForTable, sanitize, isSaneName

class CSVUploadForm(forms.Form):
    MODES = (
        (CSVUpload.CREATE, "create a new table"), 
        (CSVUpload.APPEND, "append to an existing table")
    )

    schema = forms.ChoiceField(widget=forms.Select)
    mode = forms.TypedChoiceField(choices=MODES, widget=forms.RadioSelect, coerce=int, empty_value=0)
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
            raise forms.ValidationError("Select a schema!")
        
        return schema

    def clean(self):
        cleaned_data = super(CSVUploadForm, self).clean()
        # check if the table they chose exists (in append mode)
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        if mode == CSVUpload.APPEND:
            if schema in self.db_meta and table not in self.db_meta[schema]:
                self._errors['mode'] = self.error_class(['Choose a table!'])
                # make sure the error message is displayed by removing it from
                # cleaned_data
                cleaned_data.pop('mode', None)

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

class DocUploadForm(forms.ModelForm):
    class Meta:
        model = DocUpload
        fields = ("description", "file", "preference")

    def clean_preference(self):
        if self.cleaned_data['preference'] == 2:
            raise forms.ValidationError("Wrong answer, buddy!")
        return self.cleaned_data['preference']

class CSVPreviewForm(forms.Form):
    # we add all the fields dynamically in __init__
    def __init__(self, *args, **kwargs):
        self.upload = kwargs.pop("upload")
        super(CSVPreviewForm, self).__init__(*args, **kwargs)

        column_names, data, column_types, type_names = parseCSV(self.upload.filename)

        if self.upload.mode == CSVUpload.CREATE:
            # show text field for table name
            self.fields['table'] = forms.CharField()
            # fields for each column name, and data type
            choices = [(k, v) for k, v in ColumnTypes.TO_HUMAN.items()]
            for i, column_name in enumerate(column_names):
                self.fields['column_name_%d' % (i, )] = forms.CharField(initial=sanitize(column_name))
                self.fields['type_%d' % (i, )] = forms.TypedChoiceField(choices=choices, initial=column_types[i], coerce=int, empty_value=0)
        elif self.upload.mode == CSVUpload.APPEND:
            existing_columns = getColumnsForTable(self.upload.schema, self.upload.table)
            existing_column_names = [c['name'] for c in existing_columns]
            choices = [(c, c) for c in existing_column_names]
            # add the field that lets the user select a column
            for i, csv_name in enumerate(column_names):
                params = {
                    "choices": choices,
                    "widget": forms.Select(attrs={"id": "name-%d" % i}),
                }
                # preselect this option for the user if the names match
                if csv_name in existing_column_names:
                    params['initial'] = csv_name

                self.fields['column_name_%d' % (i, )] = forms.ChoiceField(**params)

    def clean_table(self):
        """Validate the table name; only applies to create mode"""
        if not isSaneName(self.cleaned_data['table']):
            raise forms.ValidationError("Not a valid name")
        return self.cleaned_data['table']
    
    def nameFields(self):
        """Return a list of the column name fields so they can be iterated over
        in a template"""
        fields = []
        for k, v in self.fields.items():
            if k.startswith("column_name_"):
                fields.append(self[k])
        return fields

    def typeFields(self):
        """Return a list of column type fields so they can be iterated over in
        a template"""
        fields = []
        for k, v in self.fields.items():
            if k.startswith("type_"):
                fields.append(self[k])
        return fields

    def cleanedColumnNames(self):
        """Return a list of the cleaned column name data"""
        data = []
        for k, v in self.fields.items():
            if k.startswith("column_name_"):
                data.append(self.cleaned_data[k])
        return data

    def cleanedColumnTypes(self):
        """Return a list of the cleaned column types data"""
        data = []
        for k, v in self.fields.items():
            if k.startswith("type_"):
                data.append(self.cleaned_data[k])
        return data

    def mapColumnNameToColumnIndex(self):
        """Return a map where the key is the column name, and the value is the
        int representing the order of the column in the csv""" 
        map = {}
        for i, k in enumerate(self.fields):
            if k.startswith("column_name_"):
                map[self.cleaned_data[k]] = i
        return map

    def clean(self):
        cleaned_data = super(CSVPreviewForm, self).clean()
        names = [] # save a copy of all the column names

        # make sure all the column names are valid
        for k, v in self.fields.items():
            if k.startswith("column_name_") and k in cleaned_data:
                names.append(cleaned_data[k])
                if not isSaneName(cleaned_data[k]):
                    self._errors[k] = self.error_class(["Not a valid column name"])
                    cleaned_data.pop(k, None)

        if self.upload.mode == CSVUpload.APPEND:
            # make sure the column names match the existing table
            existing_columns = getColumnsForTable(self.upload.schema, self.upload.table)
            existing_column_names = [c['name'] for c in existing_columns]
            if set(existing_column_names) != set(names):
                raise forms.ValidationError("The columns must match the existing table")

        return cleaned_data
