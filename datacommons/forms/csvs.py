import os
import datetime
from django import forms
from django.forms.widgets import RadioSelect
from django.db import DatabaseError
from ..models import CSVUpload, ColumnTypes, Table
from ..models.csvhelpers import handleUploadedCSV, parseCSV, importCSVInto
from ..models.dbhelpers import getColumnsForTable, sanitize, isSaneName, getPrimaryKeysForTable, createTable, getDatabaseMeta

class CSVUploadForm(forms.Form):
    """This is the initial form displayed to upload a CSV"""
    MODES = (
        (CSVUpload.CREATE, "create a new table"), 
        (CSVUpload.APPEND, "append to an existing table"),
        (CSVUpload.UPSERT, "append to or update an existing table"),
        (CSVUpload.DELETE, "delete rows from an existing table"),
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

    def clean_file(self):
        # attempt an upload
        file = self.cleaned_data["file"]
        self.path = None

        if not file:
            return None

        try:
            self.path = handleUploadedCSV(file)
        except TypeError as e:
            raise forms.ValidationError(str(e))

        # try to parse it
        try:
            parseCSV(os.path.basename(self.path))
        except UnicodeDecodeError as e:
            raise forms.ValidationError("The file has corrupt characters on line %d. Edit the file and remove or replace the invalid characters" % (e.line))

        return file

    def clean(self):
        cleaned_data = super(CSVUploadForm, self).clean()
        # check if the table they chose exists (in append mode)
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        if mode in [CSVUpload.APPEND, CSVUpload.UPSERT, CSVUpload.DELETE]:
            if schema in self.db_meta and table not in self.db_meta[schema]:
                self._errors['table'] = self.error_class(['Choose a table!'])
                # make sure the error message is displayed by removing it from
                # cleaned_data
                cleaned_data.pop('table', None)

        # if the upload was successful, and the mode is append, make sure there
        # are the right amount of columns
        if len(self._errors) == 0 and mode in [CSVUpload.APPEND, CSVUpload.UPSERT]:
            existing_columns = getColumnsForTable(schema, table)
            header, data, types = parseCSV(os.path.basename(self.path))
            if len(existing_columns) != len(header):
                self._errors['file'] = self.error_class(["The number of columns in the CSV you selected does not match the number of columns in the table you selected"])
                del cleaned_data['file']

        if len(self._errors) == 0 and mode in [CSVUpload.DELETE]:
            pks = getPrimaryKeysForTable(schema, table)
            header, data, types = parseCSV(os.path.basename(self.path))
            if len(pks) != len(header):
                self._errors['file'] = self.error_class(['The number of columns in the CSV must match the number of primary keys in the table you selected'])

        return cleaned_data

    def save(self, user):
        """
        Create the CSVUpload object, and add or attach the
        corresponding table object
        """
        filename = os.path.basename(self.path)
        r = CSVUpload()
        r.filename = filename
        r.mode = self.cleaned_data['mode']
        r.user = user

        create_table_object = True
        owner = user

        if r.mode != CSVUpload.CREATE:
            # find the table object, and tack it onto the
            # CSVUpload object
            try:
                r.table = Table.objects.get(
                    name=self.cleaned_data['table'],
                    schema=self.cleaned_data['schema'],
                )
                create_table_object = False
            except Table.DoesNotExist as e:
                # this means the actual table was created
                # outside the application. We need to add the
                # table row into the Table table (that sounds
                # confusing). The owner of the table will be
                # the user with the lowest user_id
                owner = User.objects.all().order_by("pk")[0]

        if create_table_object:
            t = Table(
                schema=self.cleaned_data['schema'],
                name=self.cleaned_data['table'],
                owner=owner,
            )
            t.save()
            r.table = t

        r.save()
        return r

class CSVPreviewForm(forms.Form):
    """This form allows the user to specify the names and types of the columns
    in their uploaded CSV (see CSVUploadForm) IF they are creating a new table. 
    Or this form allows them to select which existing columns in the table
    match up with their uploaded CSV"""
    # we add all the fields dynamically here
    def __init__(self, *args, **kwargs):
        self.upload = kwargs.pop("upload")
        super(CSVPreviewForm, self).__init__(*args, **kwargs)

        column_names, data, column_types = parseCSV(self.upload.filename)

        if self.upload.mode == CSVUpload.CREATE:
            # show text field for table name
            self.fields['table'] = forms.CharField()
            # fields for each column name, and data type
            choices = [(k, v) for k, v in ColumnTypes.TO_HUMAN.items()]
            for i, column_name in enumerate(column_names):
                self.fields['column_name_%d' % (i, )] = forms.CharField(initial=sanitize(column_name))
                self.fields['type_%d' % (i, )] = forms.TypedChoiceField(
                    choices=choices, 
                    initial=column_types[i], 
                    coerce=int, 
                    empty_value=0
                )

            # add the primary key fields
            for i, column_name in enumerate(column_names):
                self.fields['is_pk_%d' % (i, )] = forms.BooleanField(initial=False, required=False)

        elif self.upload.mode in [CSVUpload.APPEND, CSVUpload.UPSERT, CSVUpload.DELETE]:
            if self.upload.mode == CSVUpload.DELETE:
                existing_column_names = getPrimaryKeysForTable(self.upload.schema, self.upload.table)
            else:
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

    def pkFields(self):
        """Return a list of pk fields so they can be iterated over in a
        template"""
        fields = []
        for k, v in self.fields.items():
            if k.startswith("is_pk_"):
                fields.append(self[k])
        return fields

    def cleanedPrimaryKeyColumnNames(self):
        """Return a list of booleans indicating if the field is a pk"""
        data = []
        index = 0
        for k, v in self.fields.items():
            if k.startswith("is_pk_"):
                if self.cleaned_data[k]:
                    data.append(self.cleaned_data["column_name_%d" % (index)])
                index += 1
        return data

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
        index = 0
        for field_name in self.fields:
            if field_name.startswith("column_name_"):
                map[self.cleaned_data[field_name]] = index
                index += 1
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

        if self.upload.mode in [CSVUpload.APPEND, CSVUpload.UPSERT]:
            # make sure the column names match the existing table
            existing_columns = getColumnsForTable(self.upload.schema, self.upload.table)
            existing_column_names = [c['name'] for c in existing_columns]
            if set(existing_column_names) != set(names):
                raise forms.ValidationError("The columns must match the existing table")

        return cleaned_data

    def save(self, upload):
        if upload.mode == upload.CREATE: 
            upload.table.name = self.cleaned_data['table']
            upload.table.save()

            # build the table and insert all the data
            column_names = self.cleanedColumnNames()
            column_types = self.cleanedColumnTypes()
            primary_keys = self.cleanedPrimaryKeyColumnNames()
            try:
                createTable(upload.table, column_names, column_types, primary_keys)
                importCSVInto(
                    upload.filename, 
                    upload.table,
                    column_names, 
                    column_name_to_column_index=self.mapColumnNameToColumnIndex(),
                    mode=upload.mode,
                    commit=True)
            except DatabaseError as e:
                raise

            upload.table.created_on = datetime.datetime.now()
            upload.table.save()

        elif upload.mode in [upload.APPEND, upload.UPSERT, upload.DELETE]:
            # insert all the data
            try:
                importCSVInto(
                    upload.filename, 
                    upload.table,
                    self.cleanedColumnNames(), 
                    column_name_to_column_index=self.mapColumnNameToColumnIndex(),
                    mode=upload.mode,
                    commit=True, 
                )
            except DatabaseError as e:
                raise

        upload.status = upload.DONE
        upload.save()

