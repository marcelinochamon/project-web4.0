from django.contrib import admin
from .models import Wait, Table

# class WaitAdmin(admin.ModelAdmin):
#     list_display = ('id', 'name', 'party_size', 'arrival_time')

# Register your models here.
admin.site.register(Wait)
admin.site.register(Table)


