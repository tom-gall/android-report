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
    #job_name = models.CharField(max_length=64)
    cached = models.BooleanField(default=False)

    def __str__(self):
        return "%s_%s %s" % (self.lava_nick, self.job_id, self.cached)

#class Bugs(models.Model):
#    job_name = models.CharField(max_length=16)
#    job_id = models.CharField(max_length=16)
#    test_suite = models.CharField(max_length=64)
#    test_case = models.CharField(max_length=64)
#    bug_id = models.CharField(max_length=64)
#    bug_links = models.CharField(max_length=64)
#    hardware = models.CharField(max_length=64)
#
#    def __str__(self):
#        return "%s_%s %s" % (self.bug_id, self.hardware, self.test_suite)

class BaseResults(models.Model):
    build_name = models.CharField(max_length=64)
    build_no = models.CharField(max_length=8)
    #lava_nick = models.CharField(max_length=16)
    #job_id = models.CharField(max_length=16)

    # for cts, test plan
    # for vts, test plan, job_name
    # for basic, test suite
    # for benchmarks, test suite
    plan_suite = models.CharField(max_length=32)
    # for cts, test module
    # for vts, same as plan
    # for basic test, same as test suite
    # for benchmarks, test case
    module_testcase = models.CharField(max_length=128)

    # for cts/vts/basic tests
    number_pass = models.IntegerField(default=0)
    number_fail = models.IntegerField(default=0)
    number_total = models.IntegerField(default=0)
    # for basic, caculate as well, but not used
    number_passrate = models.DecimalField( max_digits=11, decimal_places=2, null=True)

    unit = models.CharField(max_length=16, default='points')
    measurement = models.DecimalField(max_digits=11, decimal_places=2, null=True, default=0)

    def __str__(self):
        return "%s %d %d %f %s %s-%s" % (self.module_testcase, self.number_pass, self.number_fail, self.measurement, self.unit, self.build_name, self.build_no)

#class Bases(models.Model):
#    build_name = models.CharField(max_length=64)
#    base_build_no = models.CharField(max_length=16)
    #base_lava_nick = models.CharField(max_length=8)
