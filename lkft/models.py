# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

class KernelChangeManager(models.Manager):
    def get_queryset(self):
        return super(KernelChangeManager, self).get_queryset().filter(reported=False)

class KernelChange(models.Model):
    branch = models.CharField(max_length=255)
    describe = models.CharField(max_length=255)
    reported = models.BooleanField()
    trigger_name = models.CharField(max_length=255)
    trigger_number = models.IntegerField()

    result = models.CharField(max_length=100, null=True, default="NOINFO")
    timestamp = models.DateTimeField(null=True)
    duration = models.IntegerField(default=0) # total_seconds

    number_passed = models.IntegerField(default=0)
    number_failed = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    modules_done = models.IntegerField(default=0)
    modules_total = models.IntegerField(default=0)


    def __str__(self):
        return "%s-%s" % (self.branch, self.describe)

    def __unicode__(self):
        return "%s-%s" % (self.branch, self.describe)

    objects = models.Manager() # The default manager
    objects_needs_report = KernelChangeManager() # custom managerKernelChangeManager()


class CiBuildKernelChangeManager(models.Manager):
    def get_builds_per_kernel_change(self, kernel_change=None):
        return super(CiBuildKernelChangeManager, self).get_queryset().filter(kernel_change=kernel_change)


class CiBuild(models.Model):
    name = models.CharField(max_length=255)
    number = models.IntegerField()
    kernel_change = models.ForeignKey(KernelChange, null=True, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(null=True)
    duration = models.IntegerField(default=0) # total_seconds
    result = models.CharField(max_length=100, null=True, default="NOINFO")

    def __str__(self):
        return "%s#%s" % (self.name, self.number)

    def __unicode__(self):
        return "%s#%s" % (self.name, self.number)

    objects = models.Manager()
    objects_kernel_change = CiBuildKernelChangeManager()


class ReportBuild(models.Model):
    # the group that this build belongs to
    group = models.CharField(max_length=100)
    # the name of the qareport project
    name = models.CharField(max_length=100)
    # the version of the qareport build
    version = models.CharField(max_length=100)

    kernel_change = models.ForeignKey(KernelChange, on_delete=models.CASCADE)
    ci_build = models.ForeignKey(CiBuild, on_delete=models.CASCADE, related_name="ci_build")
    ci_trigger_build = models.ForeignKey(CiBuild, on_delete=models.CASCADE, related_name='trigger_build')

    number_passed = models.IntegerField(default=0)
    number_failed = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    modules_done = models.IntegerField(default=0)
    modules_total = models.IntegerField(default=0)

    # the time the trigger build was started
    started_at = models.DateTimeField(null=True)
    # the time the last job was fetched
    fetched_at = models.DateTimeField(null=True)


    def __str__(self):
        return "%s#%s#%s" % (self.group, self.name, self.version)

    def __unicode__(self):
        return "%s#%s#%s" % (self.group, self.name, self.version)

    objects = models.Manager()