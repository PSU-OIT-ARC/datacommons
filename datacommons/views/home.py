import re
from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from ..forms.accounts import UserRegistrationForm

def index(request):
    if request.user.is_authenticated():
        return HttpResponseRedirect(reverse("profile"))
    return render(request, "home/home.html", {

    })

def register(request):
    if request.POST:
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.email = user.username
            user.save()
            message = """My Dearest P-dawg:
I regret to inform you that yet another person (%s) has registered
on the datacommons site. Go to <whatever the datacommons url is>/admin, 
and activate their account.

Forever yours,

Django""" % (user.username)
            send_mail('Datacommons Registration', message, "django@pdx.edu", [SETTINGS.USER_REGISTRATION_NOTIFICATION_EMAIL])

            return render(request, "registration/register_done.html")
    else:
        form = UserRegistrationForm()

    return render(request, "registration/register.html", {
        "form": form,
    })

@login_required
def profile(request):
    return render(request, "home/account.html", {

    })

