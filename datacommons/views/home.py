from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm

def index(request):
    if request.user.is_authenticated():
        return HttpResponseRedirect(reverse("account-home"))
    return render(request, "home/home.html", {

    })

def register(request):
    if request.POST:
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            return render(request, "registration/register_done.html")
    else:
        form = UserCreationForm()

    return render(request, "registration/register.html", {
        "form": form,
    })

@login_required
def profile(request):
    return render(request, "home/account.html", {

    })

