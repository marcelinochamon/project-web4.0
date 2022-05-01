from django.shortcuts import render
from rest_framework import viewsets
from .models import Wait, Table, Config
from .forms import WaitForm, ConfigForm
from .assignment import assign_tables
from datetime import datetime
from django.utils import timezone

tz = timezone.get_default_timezone()


def waitlist_view(request):
    waitlist = Wait.objects.all()
    formW = WaitForm(request.POST or None)
    open_tables_list = [table.number for table in Table.objects.filter(party = "Empty")]
    open_tables_list += [table.number for table in Table.objects.filter(party = "Pending")]
    if formW.is_valid():
        formW.save()
        formW = WaitForm()
    context = {
        'waitlist' : waitlist,
        'formW' : formW,
        'open_tables': sorted(open_tables_list)
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
        elif "manual_submit" in returned_num:
            cust = Wait.objects.filter(name= returned_num['guest_name']).first()
            table = Table.objects.filter(number= returned_num['table_num']).first()
            table.party = cust.name
            table.time_seated = datetime.now(tz)
            table.save()
            cust.delete()
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

def config_view(request):
    config = Config.objects.all()
    formC = ConfigForm(request.POST or None)
    if formC.is_valid():
        Config.objects.all().delete()
        formC.save()
        formC = ConfigForm()
    context = {
        'config' : config,
        'formC' : formC,
    }

    if config:
        setup = Config.objects.last()
        names_list = setup.server_names.split(',')
        num = len(names_list)
        table2 = setup.tables_for_2
        table4 = setup.tables_for_4
        table6 = setup.tables_for_6
        table8 = setup.tables_for_8
        table_size_list = []
        total_tables = table2 + table4 + table6 + table8
        for i in range(table2):
            table_size_list.append(2)
        for i in range(table4):
            table_size_list.append(4)
        for i in range(table6):
            table_size_list.append(6)
        for i in range(table8):
            table_size_list.append(8)
        Table.objects.all().delete()
        for i in range(1, total_tables + 1):
            table = Table(number = i, party = "Empty", seats = table_size_list[i-1], time_seated = datetime.now(tz), server = names_list[i % num])
            table.save()
    return render(request, "config.html", context)
