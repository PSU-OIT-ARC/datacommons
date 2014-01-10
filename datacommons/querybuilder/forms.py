import datetime
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model, authenticate
from django.utils.datastructures import SortedDict
from django.core.validators import validate_email
from django.core.mail import send_mail
from django.db import DatabaseError, transaction
from datacommons.utils.forms import BetterModelForm, BetterForm
from django.conf import settings as SETTINGS
from django.contrib.auth.forms import PasswordChangeForm
from datacommons.accounts.models import User
from datacommons.schemas.models import Table, View
from datacommons.utils.dbhelpers import isSaneName, SQLHandle, getDatabaseTopology, sanitizeSelectSQL

class RollbackTrigger(Exception):
    pass

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
            sql = sanitizeSelectSQL(sql)
            SQLHandle(sql).count()
        except (DatabaseError, ValueError) as e:
            raise forms.ValidationError(str(e))
        return sql

    def clean(self):
        cleaned = super(CreateViewForm, self).clean()
        sql = cleaned.get("sql", None)
        view_name = cleaned.get("view_name", None)
        schema = cleaned.get("schema", None)
        if sql and view_name and schema:
            try:
                with transaction.atomic():
                    View(schema=schema, name=view_name).create(sql)
                    raise RollbackTrigger("Rolling Back") # this causes the trasnaction to be rolledback, which we always want
            except DatabaseError as e:
                raise forms.ValidationError(str(e))
            except RollbackTrigger:
                pass # this is expected to happen

        return cleaned

    def save(self):
        schema = self.cleaned_data['schema']
        view_name = self.cleaned_data['view_name']
        sql = self.cleaned_data['sql']
        v = View(schema=schema, name=view_name, created_on=datetime.datetime.now(), owner=self.user)
        v.create(sql)
        v.save()
        return v
