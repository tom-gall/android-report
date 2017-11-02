# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

# Create your models here.
class TestCase(models.Model):
    name = models.CharField(max_length=128)
    result = models.CharField(max_length=16)
    measurement = models.DecimalField( max_digits=11, decimal_places=2, null=True)
    unit = models.CharField(max_length=128, null=True)
    suite = models.CharField(max_length=16)
    job_id = models.CharField(max_length=16)
    lava_nick = models.CharField(max_length=64)

    def __unicode__(self):
        if self.measurement:
            return "%s %s %s %s" % (self.name, self.result, self.measurement, self.unit)
        else:
            return "%s %s" % (self.name, self.result)


class JobCache(models.Model):
    lava_nick = models.CharField(max_length=16)
    job_id = models.CharField(max_length=16)
    cached = models.BooleanField(default=False)

    def __str__(self):
        return "%s_%s %s" % (self.lava_nick, self.job_id, self.cached)
