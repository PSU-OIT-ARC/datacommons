from django.db import IntegrityError, transaction
from django import forms
from django.contrib.auth.models import User
from ..models import TablePermission, Table
from ..models.dbhelpers import getDatabaseMeta, isSaneName, createSchema
import widgets

class PermissionsForm(forms.Form):
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
    tables = forms.ModelMultipleChoiceField(
        queryset=None, 
        widget=widgets.CheckboxSelectMultiple(renderer=widgets.NestedCheckboxRender),
    )
    user = forms.CharField(
        widget=widgets.TextInput(attrs={"placeholder": "Enter username"})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super(PermissionsForm, self).__init__(*args, **kwargs)

        options = Table.objects.groupedBySchema(owner=user)
        choices = []
        for schema, tables in options.items():
            tables = [(t.pk, t.name) for t in tables]
            choices.append((schema, tables))
        self.fields['tables'].choices = choices
        self.fields['tables'].queryset = Table.objects.filter(owner=user).exclude(created_on=None)

    def clean_user(self):
        user = self.cleaned_data['user']
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            raise forms.ValidationError("That user does not exist")
        return user

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

class TablePermissionsForm(forms.Form):
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

class CreateSchemaForm(forms.Form):
    name = forms.CharField(max_length=255)

    def clean_name(self):
        meta = getDatabaseMeta()
        name = self.cleaned_data['name']
        if name in meta:
            raise forms.ValidationError("That schema name already exists!")

        if not isSaneName(name):
            raise forms.ValidationError("That schema name contains invalid characters")

        return name

    def save(self):
        name = self.cleaned_data['name']
        print name
        createSchema(name)
