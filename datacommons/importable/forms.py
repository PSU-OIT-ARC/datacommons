import shapefile
import datetime
from django import forms
from django.forms.forms import BoundField
from django.forms.widgets import RadioSelect
from django.db import DatabaseError, transaction
import django.forms.util
from django.utils.html import format_html, format_html_join
from django.utils.encoding import force_text
from datacommons.schemas.models import ColumnTypes, Table, Column
from datacommons.utils.dbhelpers import getColumnsForTable, sanitize, isSaneName, getPrimaryKeysForTable, getDatabaseTopology
from datacommons.utils.forms import BetterForm, BetterModelForm
from .models import ImportableUpload

class ImportableUploadForm(BetterForm):
    """This is the base class for importable file uploads"""
    IMPORTABLE = None 

    MODES = (
        (ImportableUpload.CREATE, "create a new table"), 
        (ImportableUpload.APPEND, "append to an existing table"),
        (ImportableUpload.UPSERT, "append to or update an existing table"),
        (ImportableUpload.DELETE, "delete rows from an existing table"),
        (ImportableUpload.REPLACE, "delete all existing rows and insert new ones"),
    )

    schema = forms.ChoiceField(widget=forms.Select)
    mode = forms.TypedChoiceField(choices=MODES, widget=forms.RadioSelect, coerce=int, empty_value=0)
    table = forms.ChoiceField(widget=forms.Select, required=False)
    file = forms.FileField(label="Upload a file")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")

        super(ImportableUploadForm, self).__init__(*args, **kwargs)

        # get all the schemas from the db, and set the choices for schemas and tables
        self.db_topology = getDatabaseTopology()
        self.fields['schema'].choices = [("", "")] + [(schema.name, schema.name) for schema in self.db_topology]
        tables = [("", "")]
        for schema in self.db_topology:
            for table in schema.tables:
                tables.append((table.name, table.name))
        self.fields['table'].choices = tables

    def clean_file(self):
        file = self.cleaned_data["file"]
        self.model = None

        if not file:
            return None

        try:
            # attempt an upload
            self.model = self.MODEL.upload(file)
        except TypeError as e:
            raise forms.ValidationError(str(e))

        # try to parse it
        try:
            self.model.parse()
        except UnicodeDecodeError as e:
            raise forms.ValidationError("The file has corrupt characters on line %d. Edit the file and remove or replace the invalid characters" % (e.line))
        except shapefile.ShapefileException as e:
            raise forms.ValidationError("Could not import shapefile: %s" % str(e))
        except ValueError as e:
            raise forms.ValidationError(str(e))

        return file

    def validate_table_choice(self, cleaned_data):
        # check if the table they chose exists
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        # only applies to these modes
        if mode not in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.DELETE, ImportableUpload.REPLACE]:
            return

        db_schema = None
        for s in self.db_topology:
            if s.name == schema:
                db_schema = s
                break

        if db_schema and not any(t for t in db_schema if t.name == table):
            self._errors.setdefault("table", self.error_class()).append('Choose a table!')
            # make sure the error message is displayed by removing it from
            # cleaned_data
            cleaned_data.pop('table', None)

    def validate_permissions(self, cleaned_data):
        # check permissions
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        # only applies to these modes
        if mode not in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.DELETE, ImportableUpload.REPLACE]:
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
        if mode in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.REPLACE] and not table_obj.canInsert(self.user):
            self._errors.setdefault("table", self.error_class()).append('You do not have permission to insert into that table!')
            cleaned_data.pop('table', None)

        # can the user update?
        if mode == ImportableUpload.UPSERT and not table_obj.canUpdate(self.user):
            self._errors.setdefault("table", self.error_class()).append('You do not have permission to update rows in that table!')
            cleaned_data.pop('table', None)

        # can the user delete?
        if mode in [ImportableUpload.DELETE, ImportableUpload.REPLACE] and not table_obj.canDelete(self.user):
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
        if len(self._errors) != 0 or mode not in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.REPLACE]:
            return

        # compare the number of columns in the table, and the csv
        existing_columns = getColumnsForTable(schema, table)
        header, data, types = self.model.parse()
        if len(existing_columns) != len(header):
            self._errors['file'] = self.error_class(["The number of columns in the CSV you selected does not match the number of columns in the table you selected"])
            del cleaned_data['file']

    def validate_number_of_primary_keys(self, cleaned_data):
        # if in delete mode, make sure the number of columns in the CSV
        # match the number of PK columns
        mode = cleaned_data.get("mode", 0)
        table = cleaned_data.get("table", "")
        schema = cleaned_data.get("schema", "")
        if len(self._errors) == 0 and mode in [ImportableUpload.DELETE]:
            pks = getPrimaryKeysForTable(schema, table)
            header, data, types = self.model.parse()
            if len(pks) != len(header):
                self._errors['file'] = self.error_class(['The number of columns in the CSV must match the number of primary keys in the table you selected'])

    def clean(self):
        cleaned_data = super(ImportableUploadForm, self).clean()

        self.validate_table_choice(cleaned_data)
        if not self._errors:
            self.validate_permissions(cleaned_data)
        if not self._errors:
            self.validate_number_of_columns(cleaned_data)
        if not self._errors:
            self.validate_number_of_primary_keys(cleaned_data)

        return cleaned_data

    def save(self):
        """
        Create the ImportableUpload object, and add or attach the
        corresponding table object
        """
        self.model.mode = self.cleaned_data['mode']
        self.model.user = self.user

        owner = self.user

        if self.model.mode != ImportableUpload.CREATE:
            # find the table object, and tack it onto the
            # ImportableUpload object
            self.model.table = Table.objects.get(
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
            self.model.table = t

        self.model.save()
        return self.model

class ImportablePreviewForm(BetterForm):
    """This form allows the user to specify the names and types of the columns
    in their uploaded CSV (see ImportableUploadForm) IF they are creating a new table. 
    Or this form allows them to select which existing columns in the table
    match up with their uploaded CSV"""
    # we add all the fields dynamically here
    def __init__(self, *args, **kwargs):
        self.model = kwargs.pop("model")
        super(ImportablePreviewForm, self).__init__(*args, **kwargs)

        column_names, data, column_types = self.model.parse()

        if self.model.mode == ImportableUpload.CREATE:
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

        elif self.model.mode in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.DELETE, ImportableUpload.REPLACE]:
            if self.model.mode == ImportableUpload.DELETE:
                existing_columns = getPrimaryKeysForTable(self.model.table.schema, self.model.table.name)
                existing_column_names = [c.name for c in existing_columns]
            else:
                existing_columns = getColumnsForTable(self.model.table.schema, self.model.table.name)
                existing_column_names = [c.name for c in existing_columns]

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

    def clean_table(self):
        """Validate the table name; only applies to create mode"""
        if not isSaneName(self.cleaned_data['table']):
            raise forms.ValidationError("Not a valid name")
        return self.cleaned_data['table']

    def clean(self):
        cleaned_data = super(ImportablePreviewForm, self).clean()
        names = [] # save a copy of all the column names

        # make sure all the column names are valid
        for k, v in self.fields.items():
            if k.startswith("column_name_") and k in cleaned_data:
                names.append(cleaned_data[k])
                if not isSaneName(cleaned_data[k]):
                    self._errors[k] = self.error_class(["Not a valid column name"])
                    cleaned_data.pop(k, None)

        if self.model.mode in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.REPLACE]:
            # make sure the column names match the existing table
            existing_columns = getColumnsForTable(self.model.table.schema, self.model.table.name)
            existing_column_names = [c.name for c in existing_columns]
            if set(existing_column_names) != set(names):
                raise forms.ValidationError("The columns must match the existing table")

        if self.model.mode in [ImportableUpload.DELETE]:
            # make sure all the pks are defined
            existing_columns = getPrimaryKeysForTable(self.model.table.schema, self.model.table.name)
            existing_column_names = [c.name for c in existing_columns]
            if set(existing_column_names) != set(names):
                raise forms.ValidationError("The columns must match the primary keys of the existing table")

        # make sure at least one pk is defined
        if self.model.mode == ImportableUpload.CREATE:
            for k, v in self.fields.items():
                if k.startswith("is_pk"):
                    if cleaned_data.get(k):
                        break
            else:
                raise forms.ValidationError("You must specify a primary key!")

        return cleaned_data

    def save(self, model):
        if model.mode == ImportableUpload.CREATE: 
            model.table.name = self.cleaned_data['table']
            model.table.save()

            with transaction.atomic():
                self._createTable(model.table)
                self.model.importInto(self._columns())

            model.table.created_on = datetime.datetime.now()
            model.table.save()

        elif model.mode in [ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.DELETE, ImportableUpload.REPLACE]:
            # insert all the data
            with transaction.atomic():
                self.model.importInto(self._columns())

        model.status = model.DONE
        model.save()

    def _createTable(self, table):
        columns = self._columns()
        table.create(columns)

    def _columns(self):
        """Construct a list of schemata.Column objects that represent the
        columns in the table to be created"""
        column_names = self._cleanedColumnNames()

        if self.model.mode == ImportableUpload.CREATE:
            column_types = self._cleanedColumnTypes()
            primary_keys = set(self._cleanedPrimaryKeyColumnNames())

            columns = []
            for name, type in zip(column_names, column_types):
                columns.append(Column(name, type, name in primary_keys))
        else:
            columns = getColumnsForTable(self.model.table.schema, self.model.table.name)
            # reorder the columns based on the order of the columns_name list
            column_names_map = dict((col.name, col) for col in columns)
            columns = [column_names_map[name] for name in column_names]

        return columns

    def _cleanedPrimaryKeyColumnNames(self):
        """Return a list of the names of the pk fields"""
        data = []
        index = 0
        for k, v in self.fields.items():
            if k.startswith("is_pk_"):
                if self.cleaned_data[k]:
                    data.append(self.cleaned_data["column_name_%d" % (index)])
                index += 1
        return data

    def _cleanedColumnNames(self):
        """Return a list of the cleaned column name data"""
        data = []
        for k, v in self.fields.items():
            if k.startswith("column_name_"):
                data.append(self.cleaned_data[k])
        return data

    def _cleanedColumnTypes(self):
        """Return a list of the cleaned column types data"""
        data = []
        for k, v in self.fields.items():
            if k.startswith("type_"):
                data.append(self.cleaned_data[k])
        return data
