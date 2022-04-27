from django.shortcuts import render
# from .forms import TableForm
from .models import Table

# Create your views here.
def tables_view(request):
    context = {}
    return render(request, "tables.html", context)

# def table_form_view(request):
#     form = TableForm(request.POST or None)
#     if form.is_valid():
#         form.save()
#         form = TableForm()
#     context = {
#         'form': form
#     }
#     return render(request, "table_form.html", context)