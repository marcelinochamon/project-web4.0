from django.shortcuts import render
from rest_framework import viewsets
from .models import Wait, Table
from .forms import WaitForm
from .assignment import assign_tables
from datetime import datetime
from django.utils import timezone

tz = timezone.get_default_timezone()


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
    returned_num = (request.POST or None)
    if returned_num is not None:
        if "accept_sugg" in returned_num:
            cust = Wait.objects.filter(assign_sugg= returned_num['accept_sugg']).first()
            table = Table.objects.filter(number= returned_num['accept_sugg']).first()
            table.party = cust.name
            table.time_seated = datetime.now(tz)
            table.save()
            cust.delete()
        elif "reject_sugg" in returned_num:
            cust = Wait.objects.filter(assign_sugg= returned_num['reject_sugg']).first()
            table = Table.objects.filter(number= returned_num['reject_sugg']).first()
            table.party = "Empty"
            table.save()
            cust.assign_sugg = 0
            cust.save()
        assign_tables()
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
