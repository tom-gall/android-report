# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from .models import KernelChange, CiBuild, ReportBuild, ReportProject

# Register your models here.
class KernelChangeAdmin(admin.ModelAdmin):
    list_display = ['branch', 'describe', 'trigger_name', 'trigger_number', 'reported']
    search_fields = ('branch', 'describe')


class CiBuildAdmin(admin.ModelAdmin):
    list_display = ['name', 'number', 'kernel_change', 'result']
    search_fields = ('name', 'number', 'kernel_change')


class ReportBuildAdmin(admin.ModelAdmin):
    list_display = ['qa_project', 'version', 'number_passed', 'number_failed', 'number_total', 'modules_done', 'modules_total', 'qa_build_id']
    search_fields = ('qa_project', 'version')


class ReportProjectAdmin(admin.ModelAdmin):
    list_display = ['group', 'name', 'slug', 'project_id']
    search_fields = ['group', 'name', 'slug', 'project_id']


admin.site.register(KernelChange, KernelChangeAdmin)
admin.site.register(CiBuild, CiBuildAdmin)
admin.site.register(ReportBuild, ReportBuildAdmin)
admin.site.register(ReportProject, ReportProjectAdmin)
