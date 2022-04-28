from django.shortcuts import render
from rest_framework import viewsets
from .models import Wait


def waitlist_view(request):
    waitlist = Wait.objects.all()
    context = {'waitlist' : waitlist}
    return render(request, "waitlist.html", context)
