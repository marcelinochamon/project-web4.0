from django.contrib import admin
from .models import Wait, Table, Config

class WaitAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'party_size', 'arrival_time')

# Register your models here.
admin.site.register(Wait)
admin.site.register(Table)
admin.site.register(Config)


