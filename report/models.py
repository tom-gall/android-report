# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

# Create your models here.
class TestCase(models.Model):
    name = models.CharField(max_length=128)
    result = models.CharField(max_length=16)
    measurement = models.DecimalField( max_digits=20, decimal_places=2, null=True)
    unit = models.CharField(max_length=128, null=True)
    suite = models.CharField(max_length=16)
    job_id = models.CharField(max_length=16)
    lava_nick = models.CharField(max_length=64)

    def __unicode__(self):
        if self.measurement:
            return "%s %s %s %s" % (self.name, self.result, self.measurement, self.unit)
        else:
            return "%s %s" % (self.name, self.result)


JOB_STATUS_CHOICE = (
                     (0, "Submitted"),
                     (1, "Running"),
                     (2, "Complete"),
                     (3, "Incomplete"),
                     (4, "Canceled"),
                    )

class JobCache(models.Model):
    build_name = models.CharField(max_length=64)
    build_no = models.CharField(max_length=8)
    lava_nick = models.CharField(max_length=16)
    job_id = models.CharField(max_length=16)
    job_name = models.CharField(max_length=64)
    status = models.IntegerField(choices=JOB_STATUS_CHOICE)
    duration = models.FloatField()
    cached = models.BooleanField(default=False)

    def __str__(self):
        return "%s_%s %s %s#%s %s %.2f" % (self.lava_nick, self.job_id, self.job_name, self.build_name, self.build_no, self.status, self.duration/3600)


BUG_STATUS_CHOICES = (
                      ("unconfirmed", "Unconfirmed"),
                      ("confirmed", "Confirmed"),
                      ("inprogress", "InProgress"),
                      ("resolved", "Resolved"),
                     )

class Bug(models.Model):
    build_name = models.CharField(max_length=64)
    bug_id = models.CharField(max_length=16)
    link = models.CharField(max_length=128)
    subject = models.CharField(max_length=256)
    ## Unconfirmed, Confirmed, InProgress, Resolved
    status = models.CharField(max_length=64, choices=BUG_STATUS_CHOICES)
    # for cts, test plan
    # for vts, test plan, job_name
    # for basic, test suite
    # for benchmarks, test suite
    plan_suite = models.CharField(max_length=64)
    # for cts, test module
    # for vts, same as plan
    # for basic test, same as test suite
    # for benchmarks, test case
    module_testcase = models.CharField(max_length=128)

    def __str__(self):
        return "%s %s %s %s %s" % (self.bug_id, self.plan_suite, self.module_testcase, self.status, self.build_name)

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
    number_passrate = models.DecimalField( max_digits=11, decimal_places=2, default=100)

    unit = models.CharField(max_length=16, default='points')
    measurement = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=0)


    lava_nick = models.CharField(max_length=16, default='')
    job_id = models.CharField(max_length=16, default='')
    job_name = models.CharField(max_length=64, default='' )

    def __str__(self):
        return "%s %d %d %f %s %s-%s" % (self.module_testcase, self.number_pass, self.number_fail, self.measurement, self.unit, self.build_name, self.build_no)


class BuildSummary(models.Model):
    build_name = models.CharField(max_length=64)
    build_no = models.CharField(max_length=8)
    build_config  = models.CharField(max_length=64)
    build_commit  = models.CharField(max_length=64)
    android_version = models.CharField(max_length=32)
    kernel_version = models.CharField(max_length=16)
    kernel_url = models.CharField(max_length=256)
    firmware_url = models.CharField(max_length=256)
    firmware_version = models.CharField(max_length=64)
    toolchain_info = models.CharField(max_length=256)
    images_url = models.CharField(max_length=256)
    def __str__(self):
        return "%s %s %s %s" % (self.build_name, self.build_no, self.android_version, self.kernel_version)

class LAVAUser(models.Model):
    lava_nick = models.CharField(max_length=64)
    user_name = models.CharField(max_length=32)
    token = models.CharField(max_length=128)

    def __str__(self):
        return "%s %s" % (self.lava_nick, self.user_name)
