from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model, authenticate
from django.utils.datastructures import SortedDict
from django.core.validators import validate_email
from django.core.mail import send_mail
from .utils import BetterModelForm, BetterForm
from django.conf import settings as SETTINGS
from django.contrib.auth.forms import PasswordChangeForm
from datacommons.models import User, Table
from ..models.dbhelpers import getDatabaseMeta

class ChooseTablesForm(BetterForm):
    def __init__(self, *args, **kwargs):
        super(ChooseTablesForm, self).__init__(*args, **kwargs)
        options = Table.objects.groupedBySchema()
        self.schemas = SortedDict()
        for schema, tables in options.items():
            for table in tables:
                field_name = "table_%d" % table.pk
                field = self.fields[field_name] = forms.BooleanField(required=False, label=table.name)
                bound_field = self[field_name]
                bound_field.pk = table.pk
                self.schemas.setdefault(schema, []).append(bound_field)


    def clean(self):
        cleaned_data = super(ChooseTablesForm, self).clean()
        table_count = 0
        for field_name in self.fields:
            if not field_name.startswith("table_"): continue
            if cleaned_data.get(field_name, False):
                table_count += 1
            else:
                # remove the table from the cleaned data so it isn't saved to
                # the session
                cleaned_data.pop(field_name, None)
        
        if table_count < 2:
            raise forms.ValidationError("You must select at least 2 tables")

        return cleaned_data

class JoinForm(BetterForm):
    def __init__(self, *args, **kwargs):
        tables_form = kwargs.pop("tables_form")
        self.tables = []
        for field_name in tables_form:
            if not field_name.startswith("table_"): continue
            table_id = field_name[len("table_"):]
            self.tables.append(Table.objects.get(pk=table_id))

        super(JoinForm, self).__init__(*args, **kwargs)

        meta = getDatabaseMeta()
        choices = []
        for table in self.tables:
            cols = meta[table.schema][table.name]
            choices.append(
                (
                    table.schema + "." + table.name,
                    [(table.schema + "." + table.name + "." + col['name'], col['name']) for col in meta[table.schema][table.name]]
                )
            )
        self.fields['cols'] = forms.ChoiceField(
            label="Cols",
            choices=choices,
        )

        choices = [(table.pk, table.schema + "." + table.name) for table in self.tables]
        self.fields['tables'] = forms.ChoiceField(
            label="Tables",
            choices=choices
        )

        self.fields['joins'] = forms.ChoiceField(
            label="Joins",
            choices=(
                ('INNER JOIN', 'INNER JOIN'),
                ('LEFT JOIN', 'LEFT JOIN'),
                ('RIGHT JOIN', 'RIGHT JOIN'),
                ('FULL OUTER JOIN', 'FULL OUTER JOIN'),
            ),
        )
