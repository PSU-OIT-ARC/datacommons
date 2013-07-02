import os
import datetime
from django import forms
from django.forms.widgets import RadioSelect
from django.db import DatabaseError
from ..models import CSVUpload, ColumnTypes, Table
from ..models.importable import ShapefileImport as CSVImport
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
        self.user = kwargs.pop("user")

        super(CSVUploadForm, self).__init__(*args, **kwargs)

        # get all the schemas from the db, and set the choices for schemas and tables
        self.db_meta = getDatabaseMeta()
        self.fields['schema'].choices = [("", "")] + [(name, name) for name in self.db_meta]
        tables = [("", "")]
        for x, table in self.db_meta.items():
            for name, x in table.items():
                if name:
                    tables.append((name, name))
        self.fields['table'].choices = tables

    def clean_file(self):
        file = self.cleaned_data["file"]
        self.importable = None

        if not file:
            return None

        try:
            # attempt an upload
            self.importable = CSVImport.upload(file)
        except TypeError as e:
            raise forms.ValidationError(str(e))

        # try to parse it
        try:
            self.importable.parse()
        except UnicodeDecodeError as e:
            raise forms.ValidationError("The file has corrupt characters on line %d. Edit the file and remove or replace the invalid characters" % (e.line))

        return file

    def validate_table_choice(self, cleaned_data):
        # check if the table they chose exists
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        # only applies to these modes
        if mode not in [CSVUpload.APPEND, CSVUpload.UPSERT, CSVUpload.DELETE]:
            return

        if schema in self.db_meta and table not in self.db_meta[schema]:
            self._errors.setdefault("table", self.error_class).append('Choose a table!')
            # make sure the error message is displayed by removing it from
            # cleaned_data
            cleaned_data.pop('table', None)

    def validate_permissions(self, cleaned_data):
        # check permissions
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        # only applies to these modes
        if mode not in [CSVUpload.APPEND, CSVUpload.UPSERT, CSVUpload.DELETE]:
            return

        try:
            table_obj = Table.objects.get(schema=schema, name=table)
        except Table.DoesNotExist:
            # the table doesn't exist in our database, so we don't know what
            # the permissions on it are supposed to be
            self._errors.setdefault("table", self.error_class()).append("That table was created outside of datacommons, and cannot be modified")
            cleaned_data.pop('table', None)
            # no need to continue validating
            return

        # can the user insert?
        if mode in [CSVUpload.APPEND, CSVUpload.UPSERT] and not table_obj.canInsert(self.user):
            self._errors.setdefault("table", self.error_class()).append('You do not have permission to insert into that table!')
            cleaned_data.pop('table', None)

        # can the user update?
        if mode == CSVUpload.UPSERT and not table_obj.canUpdate(self.user):
            self._errors.setdefault("table", self.error_class()).append('You do not have permission to update rows in that table!')
            cleaned_data.pop('table', None)

        # can the user delete?
        if mode == CSVUpload.DELETE and not table_obj.canDelete(self.user):
            self._errors.setdefault("table", self.error_class()).append('You do not have permission to delete rows in that table!')
            cleaned_data.pop('table', None)

    def validate_number_of_columns(self, cleaned_data):
        # make sure the uploaded CSV has the right number of columns in APPEND
        # or UPSERT mode
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        # don't do any validation if there are already errors, or if we're not
        # in the right mode
        if len(self._errors) != 0 or mode not in [CSVUpload.APPEND, CSVUpload.UPSERT]:
            return

        # compare the number of columns in the table, and the csv
        existing_columns = getColumnsForTable(schema, table)
        header, data, types = self.importable.parse()
        if len(existing_columns) != len(header):
            self._errors['file'] = self.error_class(["The number of columns in the CSV you selected does not match the number of columns in the table you selected"])
            del cleaned_data['file']

    def validate_number_of_primary_keys(self, cleaned_data):
        # if in delete mode, make sure the number of columns in the CSV
        # match the number of PK columns
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        if len(self._errors) == 0 and mode in [CSVUpload.DELETE]:
            pks = getPrimaryKeysForTable(schema, table)
            header, data, types = self.importable.parse()
            if len(pks) != len(header):
                self._errors['file'] = self.error_class(['The number of columns in the CSV must match the number of primary keys in the table you selected'])

    def clean(self):
        cleaned_data = super(CSVUploadForm, self).clean()

        self.validate_table_choice(cleaned_data)
        self.validate_permissions(cleaned_data)
        self.validate_number_of_columns(cleaned_data)
        self.validate_number_of_primary_keys(cleaned_data)

        return cleaned_data

    def save(self):
        """
        Create the CSVUpload object, and add or attach the
        corresponding table object
        """
        filename = os.path.basename(self.importable.path)
        r = CSVUpload()
        r.filename = filename
        r.mode = self.cleaned_data['mode']
        r.user = self.user

        owner = self.user

        if r.mode != CSVUpload.CREATE:
            # find the table object, and tack it onto the
            # CSVUpload object
            r.table = Table.objects.get(
                name=self.cleaned_data['table'],
                schema=self.cleaned_data['schema'],
            )
        else:
            # create the table
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

        self.importable = CSVImport(self.upload.filename)
        column_names, data, column_types = self.importable.parse()

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
                existing_column_names = getPrimaryKeysForTable(self.upload.table.schema, self.upload.table.name)
            else:
                existing_columns = getColumnsForTable(self.upload.table.schema, self.upload.table.name)
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

                self.fields['column_name_%d' % i] = forms.ChoiceField(**params)

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
        """Return a list of the names of the pk fields"""
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
            existing_columns = getColumnsForTable(self.upload.table.schema, self.upload.table.name)
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
                self.importable.importInto(
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
                self.importable.importInto(
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

