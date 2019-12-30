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
    kernel_change = models.ForeignKey(KernelChange, on_delete=None)

    def __str__(self):
        return "%s#%s" % (self.name, self.number)

    def __unicode__(self):
        return "%s#%s" % (self.name, self.number)

    objects = models.Manager()
    objects_kernel_change = CiBuildKernelChangeManager()
