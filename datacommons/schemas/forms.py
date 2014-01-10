from django.db import IntegrityError, transaction
from django import forms
from django.forms import widgets
from django.utils.datastructures import SortedDict
from django.db import DatabaseError
from datacommons.schemas.models import TablePermission, Table
from datacommons.accounts.models import User
from datacommons.utils.dbhelpers import getDatabaseTopology, isSaneName
from datacommons.utils.forms import BetterForm
from .models import Schema

class PermissionsForm(BetterForm):
    GRANT = 1
    REVOKE = 2

    option = forms.TypedChoiceField(choices=(
        (GRANT, "Grant"),
        (REVOKE, "Revoke"),
    ), coerce=int, empty_value=None)
    permissions = forms.TypedMultipleChoiceField(choices=(
        (TablePermission.INSERT, "Insert"),
        (TablePermission.UPDATE, "Update"),
        (TablePermission.DELETE, "Delete"),
    ), coerce=int, empty_value=None)
    user = forms.CharField(
        widget=widgets.TextInput(attrs={
            "placeholder": "Enter username",
            "class": "span2",
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super(PermissionsForm, self).__init__(*args, **kwargs)

        # create a bunch of fields for each table
        options = Table.objects.groupedBySchema(owner=self.user)
        # keep a dict of schemas, where the key is the schema name, and the
        # value is a list of boundfields for all the tables in the schemas
        self.schemas = SortedDict()
        for schema, tables in options.items():
            for table in tables:
                field_name = "table_%d" % table.pk
                field = self.fields[field_name] = forms.BooleanField(required=False, label=table.name)
                bound_field = self[field_name]
                bound_field.pk = table.pk
                self.schemas.setdefault(schema, []).append(bound_field)

    def clean_user(self):
        user = self.cleaned_data['user']
        try:
            user = User.objects.get(email=user)
        except User.DoesNotExist:
            raise forms.ValidationError("That user does not exist")
        return user

    def clean(self):
        cleaned_data = super(PermissionsForm, self).clean()

        # validate all the tables selected by the user to make sure they exist
        # and are owned by the user
        tables = dict([(t.pk, t) for t in Table.objects.filter(owner=self.user)])
        # we create our own cleaned_data for the table objects that should be
        # mutated
        cleaned_data['tables'] = []
        for field_name in self.fields:
            if field_name.startswith("table_") and cleaned_data[field_name]:
                pk = int(field_name[len("table_"):])
                if pk not in tables:
                    raise forms.ValidationError("Not a valid table")
                cleaned_data['tables'].append(tables[pk])
        
        return cleaned_data

    def save(self):
        tables = self.cleaned_data['tables']
        permissions = self.cleaned_data['permissions']
        user = self.cleaned_data['user']
        option = self.cleaned_data['option']

        for table in tables:
            for permission in permissions:
                if option == self.REVOKE:
                    table.revoke(user, permission)
                elif option == self.GRANT:
                    table.grant(user, permission)

class TablePermissionsForm(BetterForm):
    def __init__(self, *args, **kwargs):
        self.table = kwargs.pop("table")
        super(TablePermissionsForm, self).__init__(*args, **kwargs)

        self.grid = self.table.permissionGrid()
        for user, perm_list in self.grid.items():
            self.fields['user_%d_can_insert' % user.pk] = forms.BooleanField(initial=perm_list['can_insert'], required=False)
            self.fields['user_%d_can_update' % user.pk] = forms.BooleanField(initial=perm_list['can_update'], required=False)
            self.fields['user_%d_can_delete' % user.pk] = forms.BooleanField(initial=perm_list['can_delete'], required=False)

    def fieldIter(self):
        for user, perm_list in self.grid.items():
            yield (
                user, 
                self['user_%d_can_insert' % user.pk],
                self['user_%d_can_update' % user.pk],
                self['user_%d_can_delete' % user.pk],
            )

    def save(self):
        # for each user who has permissions on this table
        for user, perm_list in self.grid.items():
            # for each type of permission
            for action in ["insert", "update", "delete"]:
                # check if the checkbox was checked for this permission type
                new_perm = self.cleaned_data.get("user_%d_can_%s" % (user.pk, action), False)
                # see what the old value was for this permission type
                old_perm = perm_list["can_%s" % action]
                # if they differ, we need to update the DB
                if new_perm != old_perm:
                    # we know the TablePermission class has constants called
                    # INSERT, UPDATE and DELETE, so we convert the permission
                    # name to upper case, and pass that to the grant/revoke
                    # functions
                    if new_perm:
                        self.table.grant(user, getattr(TablePermission, action.upper()))
                    else:
                        self.table.revoke(user, getattr(TablePermission, action.upper()))

class CreateSchemaForm(BetterForm):
    name = forms.CharField(max_length=255)

    def clean_name(self):
        meta = getDatabaseTopology()
        name = self.cleaned_data['name']
        if name in [s.name for s in meta]:
            raise forms.ValidationError("That schema name already exists!")

        if not isSaneName(name):
            raise forms.ValidationError("That schema name contains invalid characters")

        return name

    def save(self):
        name = self.cleaned_data['name']
        Schema.create(name)

class DeleteViewForm(BetterForm):
    def __init__(self, *args, **kwargs):
        self.table = kwargs.pop("table")
        super(DeleteViewForm, self).__init__(*args, **kwargs)

    def save(self):
        self.table.delete()


