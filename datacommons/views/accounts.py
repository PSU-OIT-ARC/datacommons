from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth import login as django_login, logout as django_logout, get_user_model
from ..forms.accounts import LoginForm, RegistrationForm, SettingsForm, PasswordChangeForm

def settings(request):
    if request.POST:
        form = SettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated")
            return HttpResponseRedirect(reverse("settings"))
    else:
        form = SettingsForm(instance=request.user)

    return render(request, "registration/settings.html", {
        'form': form,
    })

def password(request):
    if request.POST:
        form = PasswordChangeForm(data=request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Password updated")
            return HttpResponseRedirect(reverse("settings"))
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "registration/password.html", {
        'form': form,
    })

def login(request):
    if request.user.is_authenticated():
        return HttpResponseRedirect(reverse("profile"))

    if request.POST:
        form = LoginForm(request.POST)
        if form.is_valid():
            django_login(request, form.cleaned_data['user'])
            return HttpResponseRedirect(reverse("profile"))
    else:
        form = LoginForm()
    return render(request, "registration/login.html", {
        'form': form,
    })

def register(request):
    if request.POST:
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(request=request)
            messages.warning(request, "You must now wait for someone to activate your account")
            return HttpResponseRedirect(reverse("home"))
    else:
        form = RegistrationForm()

    return render(request, "registration/register.html", {
        "form": form,
    })

@login_required
def profile(request):
    return render(request, "registration/account.html", {

    })

