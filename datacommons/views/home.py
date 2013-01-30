from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.core.urlresolvers import reverse
from django.contrib.auth.forms import UserCreationForm

def index(request):
    return render(request, "home/home.html", {

    })

def register(request):
    form = UserCreationForm(request.POST or None)
    if request.POST:
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            return reverse('django.contrib.auth.views.login')

    return render(request, "registration/register.html", {
        "form": form,
    })

def profile(request):
    return HttpResponseRedirect(reverse("csv-upload"))

