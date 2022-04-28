from django.contrib import admin
from .models import Wait

class WaitAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'party_size', 'dining_time', 'seated', 'left')

# Register your models here.
admin.site.register(Wait)
