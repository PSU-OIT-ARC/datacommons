from django.conf import settings as SETTINGS
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

def index(request):
    return render(request, 'home/index.html', {

    })
