# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

# Create your models here.
class TestCase(models.Model):
    name = models.CharField(max_length=256)
    result = models.CharField(max_length=16)
    measurement = models.DecimalField( max_digits=20, decimal_places=2, null=True)
    unit = models.CharField(max_length=128, null=True)
    suite = models.CharField(max_length=64)
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
    duration = models.DurationField()
    cached = models.BooleanField(default=False)

    def __str__(self):
        return "%s_%s %s %s#%s %s %s %s" % (self.lava_nick, self.job_id, self.job_name, self.build_name, self.build_no, self.status, self.duration, self.cached)


class Comment(models.Model):
    build_name = models.CharField(max_length=64)
    # The build that this comment is started
    build_no = models.CharField(max_length=8, default='', blank=True)
    # The build that this comment is not work any more
    build_no_fixed = models.CharField(max_length=8, default='', blank=True)
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
    comment = models.TextField()

    def __str__(self):
        return "%s %s %s %s %s" % (self.build_name, self.build_no, self.plan_suite, self.module_testcase, self.comment)


BUG_STATUS_CHOICES = (
                      ("unconfirmed", "Unconfirmed"),
                      ("confirmed", "Confirmed"),
                      ("inprogress", "InProgress"),
                      ("resolved", "Resolved"),
                     )

class Bug(models.Model):
    build_name = models.CharField(max_length=64)
    # the build no that this bug is report
    build_no = models.CharField(max_length=8, default='', blank=True)
    # the build no that this bug is fixed
    build_no_fixed = models.CharField(max_length=8, default='', blank=True)
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
    vts_pkg_url = models.CharField(max_length=256, default='')
    cts_pkg_url = models.CharField(max_length=256, default='')

    def __str__(self):
        return "%s %s %s %s" % (self.build_name, self.build_no, self.android_version, self.kernel_version)


class BuildBugzilla(models.Model):
    build_name = models.CharField(max_length=64)
    new_bug_url = models.URLField()
    product = models.CharField(max_length=64)
    op_sys = models.CharField(max_length=32)
    bug_severity = models.CharField(max_length=32)
    component = models.CharField(max_length=64)
    keywords = models.CharField(max_length=16, default='', null=True, blank=True)
    rep_platform = models.CharField(max_length=16)
    short_desc_prefix = models.CharField(max_length=16, default='', blank=True)

    def __str__(self):
        return "%s %s %s" % (self.build_name, self.product, self.component)


class LAVA(models.Model):
    nick = models.CharField(max_length=64)
    domain = models.CharField(max_length=64)

    def __str__(self):
        return "%s %s" % (self.nick, self.domain)


class LAVAUser(models.Model):
    user_name = models.CharField(max_length=32)
    token = models.CharField(max_length=128)
    lava = models.ForeignKey(LAVA, null=True)

    def __str__(self):
        return "%s %s" % (self.lava, self.user_name)


class BuildConfig(models.Model):
    build_name = models.CharField(max_length=64)
    img_ext = models.CharField(max_length=16)
    base_build_name = models.CharField(max_length=64)
    base_build_no = models.CharField(max_length=8)
    template_dir = models.CharField(max_length=8, blank=True, default='')

    bugzilla = models.ForeignKey(BuildBugzilla)
    lava = models.ForeignKey(LAVA, null=True)

    def __str__(self):
        return "%s %s %s" % (self.build_name, self.base_build_name, self.base_build_no)
