# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin

# Register your models here.
from .models import TestCase
from .models import JobCache
from .models import BaseResults
from .models import Bug
from .models import BuildSummary, LAVAUser, BuildBugzilla, BuildConfig, LAVA, Comment
from django.contrib.auth.models import Permission

admin.site.register(Permission)

class TestCaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'result', 'measurement', 'unit', 'suite', 'job_id')
    search_fields = ('name', 'suite', 'job_id')
    list_filter = ('name', 'suite', 'job_id')
    list_per_page = 500

admin.site.register(TestCase, TestCaseAdmin)

class JobCacheAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'job_name', 'lava_nick', 'status', 'duration', 'build_name', 'build_no')
    search_fields = ('job_id', 'job_name', 'build_name', 'build_no')

admin.site.register(JobCache, JobCacheAdmin)

class BugAdmin(admin.ModelAdmin):
    search_fields = ('bug_id', 'build_name', 'plan_suite', 'module_testcase')

admin.site.register(Bug, BugAdmin)

class CommentAdmin(admin.ModelAdmin):
    search_fields = ('build_name', 'plan_suite', 'module_testcase', 'comment')

admin.site.register(Comment, CommentAdmin)



admin.site.register(BaseResults)
admin.site.register(BuildSummary)
admin.site.register(LAVAUser)
admin.site.register(BuildBugzilla)
admin.site.register(BuildConfig)
admin.site.register(LAVA)
