import datetime
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model, authenticate
from django.utils.datastructures import SortedDict
from django.core.validators import validate_email
from django.core.mail import send_mail
from django.db import DatabaseError
from .utils import BetterModelForm, BetterForm
from django.conf import settings as SETTINGS
from django.contrib.auth.forms import PasswordChangeForm
from datacommons.models import User, Table
from ..models.dbhelpers import isSaneName, SQLHandle, getDatabaseTopology
from ..models import schemata

class CreateViewForm(BetterForm):
    view_name = forms.CharField()
    sql = forms.CharField()

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super(CreateViewForm, self).__init__(*args, **kwargs)
        options = [s.name for s in getDatabaseTopology()]
        self.fields['schema'] = forms.ChoiceField(choices=zip(options, options))
        self.fields['view_name'].widget.attrs.update({
            'class': 'span2',
            'placeholder': "View name",
        })

    def clean_view_name(self):
        view_name = self.cleaned_data['view_name']
        if not isSaneName(view_name):
            raise forms.ValidationError("That is not a valid name")
        return view_name

    def clean_sql(self):
        sql = self.cleaned_data['sql']
        try:
            SQLHandle(sql).count()
        except DatabaseError as e:
            raise forms.ValidationError(str(e))
        return sql

    def clean(self):
        cleaned = super(CreateViewForm, self).clean()
        sql = cleaned.get("sql", None)
        view_name = cleaned.get("view_name", None)
        schema = cleaned.get("schema", None)
        if sql and view_name and schema:
            try:
                schemata.View(schema=schema, name=view_name).create(sql, commit=False)
            except DatabaseError as e:
                raise forms.ValidationError(str(e))

        return cleaned

    def save(self):
        schema = self.cleaned_data['schema']
        view_name = self.cleaned_data['view_name']
        sql = self.cleaned_data['sql']
        v = schemata.View(schema=schema, name=view_name, created_on=datetime.datetime.now(), owner=self.user)
        v.create(sql, commit=True)
        v.save()
        return v
