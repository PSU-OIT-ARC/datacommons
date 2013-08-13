from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model, authenticate
from django.core.validators import validate_email
from django.core.mail import send_mail
from .utils import BetterModelForm, BetterForm
from django.conf import settings as SETTINGS
from django.contrib.auth.forms import PasswordChangeForm
from datacommons.models import User

class RegistrationForm(BetterForm):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data['email']
        user_model = get_user_model()
        try:
            user_model.objects.get(email=email)
            raise forms.ValidationError("A user with that email address already exists")
        except user_model.DoesNotExist:
            pass

        return email

    def clean(self):
        cleaned_data = super(RegistrationForm, self).clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password != confirm_password:
            raise forms.ValidationError("Your passwords didn't match")

        return cleaned_data

    def save(self, request):
        user_model = get_user_model()
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        user = user_model.objects.create_user(email=email, password=password, is_active=False)
        user.save() # is this required?
        # send email to user
        self.sendVerificationEmail(user, request)
        return user

    def sendVerificationEmail(self, user, request):
        message = """My Dearest P-dawg:
I regret to inform you that yet another person (%s) has registered
on the datacommons site. Go to <whatever the datacommons url is>/admin, 
and activate their account.

Forever yours,

Django""" % (user.email)
        send_mail('Datacommons Registration', message, "django@pdx.edu", [SETTINGS.USER_REGISTRATION_NOTIFICATION_EMAIL])


class SettingsForm(BetterModelForm):
    class Meta:
        model = User
        fields = (
            'email',
            'first_name',
            'last_name',
        )

class PasswordChangeForm(PasswordChangeForm, BetterForm):
    pass

class LoginForm(BetterForm):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data['email']
        user_model = get_user_model()
        try:
            user_model.objects.get(email=email)
        except user_model.DoesNotExist:
            raise forms.ValidationError("A user with that email address does not exist")

        return email

    def clean(self):
        cleaned_data = super(LoginForm, self).clean()
        user_model = get_user_model()

        email = cleaned_data.get("email")
        password = cleaned_data.get('password')
        if email and password:
            user = authenticate(email=email, password=password)
            if user is not None:
                if not user.is_active:
                    raise forms.ValidationError("Your account is not active")
                else:
                    cleaned_data['user'] = user
            else:
                raise forms.ValidationError("Your password was incorrect")

        return cleaned_data

