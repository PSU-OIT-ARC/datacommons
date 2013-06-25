from django import forms
from django.contrib.auth.models import User
from ..models import TablePermission, Table
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
                if option == self.GRANT:
                    TablePermission(table=table, user=user, permission=permission).save()
                elif option == self.REVOKE:
                    TablePermission.objects.filter(table=table, user=user, permission=permission).delete()
