# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from .models import KernelChange, CiBuild, ReportBuild

# Register your models here.
class KernelChangeAdmin(admin.ModelAdmin):
    list_display = ['branch', 'describe', 'trigger_name', 'trigger_number', 'reported']


class CiBuildAdmin(admin.ModelAdmin):
    list_display = ['name', 'number']

class ReportBuildAdmin(admin.ModelAdmin):
    list_display = ['group', 'name', 'version', 'number_passed', 'number_failed', 'number_total', 'modules_done', 'modules_total']

admin.site.register(KernelChange, KernelChangeAdmin)
admin.site.register(CiBuild, CiBuildAdmin)
admin.site.register(ReportBuild, ReportBuildAdmin)
