from django import forms
from django.forms.forms import BoundField
import django.forms.util
from django.utils.html import format_html, format_html_join
from django.utils.encoding import force_text

class BetterForm(forms.Form):
    def __init__(self, *args, **kwargs):
        # custom error class that uses bootstrap css classes
        kwargs['error_class'] = ErrorList
        super(BetterForm, self).__init__(*args, **kwargs)

class BetterModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        # custom error class that uses bootstrap css classes
        kwargs['error_class'] = ErrorList
        super(BetterModelForm, self).__init__(*args, **kwargs)

class ErrorList(django.forms.util.ErrorList):
    def as_ul(self):
        if not self: return ''
        return format_html(
            '<ul class="text-error">{0}</ul>',
            format_html_join('', '<li>{0}</li>', ((force_text(e),) for e in self))
        )
