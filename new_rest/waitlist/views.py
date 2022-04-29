from django.shortcuts import render
from rest_framework import viewsets
from .models import Wait, Table
from .forms import WaitForm
from .assignment import assign_tables


def waitlist_view(request):
    waitlist = Wait.objects.all()
    form = WaitForm(request.POST or None)
    if form.is_valid():
        form.save()
        assign_tables()
        form = WaitForm()
    context = {
        'waitlist' : waitlist,
        'form' : form
    }
    return render(request, "waitlist.html", context)

def tables_view(request):
    tables = Table.objects.all()
    context = {'tables' : tables}
    returned_num = (request.POST or None)
    if returned_num is not None:
        table = Table.objects.filter(number= returned_num['table_num']).first()
        table.party = "Empty"
        table.save()
        assign_tables()
    print(returned_num)
    return render(request, "tables.html", context)
