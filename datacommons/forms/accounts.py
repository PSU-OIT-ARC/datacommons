from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import validate_email

class UserRegistrationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super(UserRegistrationForm, self).__init__(*args, **kwargs)
        self.fields['username'].validators.append(validate_email)
        self.fields['username'].label = "Email"
