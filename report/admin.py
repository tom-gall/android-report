# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin

# Register your models here.
from .models import TestCase
from .models import JobCache
from .models import BaseResults
from .models import Bug
from .models import BuildSummary

class TestCaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'result', 'measurement', 'unit', 'suite', 'job_id')
    search_fields = ('name', 'suite')
    list_filter = ('name', 'suite')

admin.site.register(TestCase, TestCaseAdmin)
admin.site.register(JobCache)
admin.site.register(BaseResults)
admin.site.register(Bug)
admin.site.register(BuildSummary)
