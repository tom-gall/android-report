# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from .models import KernelChange, CiBuild

# Register your models here.
class KernelChangeAdmin(admin.ModelAdmin):
    list_display = ['branch', 'describe', 'trigger_name', 'trigger_number', 'reported']


class CiBuildAdmin(admin.ModelAdmin):
    list_display = ['name', 'number']


admin.site.register(KernelChange, KernelChangeAdmin)
admin.site.register(CiBuild, CiBuildAdmin)
