from django import forms
from ..models import TablePermission, Table

class PermissionsForm(forms.Form):
    GRANT = 1
    REVOKE = 2

    option = forms.ChoiceField(choices=(
        (GRANT, "Grant"),
        (REVOKE, "Revoke"),
    ))
    permissions = forms.TypedMultipleChoiceField(choices=(
        (TablePermission.INSERT, "Insert"),
        (TablePermission.UPDATE, "Update"),
        (TablePermission.DELETE, "Delete"),
    ), coerce=int, empty_value=None)
    tables = forms.TypedMultipleChoiceField(coerce=int, empty_value=None)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super(PermissionsForm, self).__init__(*args, **kwargs)

        choices = Table.objects.groupedBySchema(owner=user)

