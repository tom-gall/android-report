# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django import forms
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required, permission_required

import collections
import datetime
import re
import sys
import urllib
import urllib2
import xmlrpclib
import yaml
import logging
import tempfile
import os
import tarfile
import zipfile
import xml.etree.ElementTree as ET
import bugzilla

logger = logging.getLogger(__name__)

from lava_tool.authtoken import AuthenticatingServerProxy, KeyringAuthBackend

# Create your views here.
from models import TestCase, JobCache, BaseResults, Bug, BuildSummary, LAVA, LAVAUser, BuildBugzilla, BuildConfig, Comment

from lcr.settings import FILES_DIR, BUGZILLA_API_KEY

basic_weekly = { # job_name: ['test_suite', ],
                        #"basic": [ "meminfo", 'meminfo-first', 'meminfo-second', "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "basic": [ "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "weekly": [ 'media-codecs', 'piglit-gles2', 'piglit-gles3', 'piglit-glslparser', 'piglit-shader-runner', 'stringbench', 'libc-bench'],
                     }

optee = { # job_name: ['test_suite', ],
          "optee-xtest": [ "optee-xtest"],
        }

benchmarks_common = {  # job_name: {'test_suite':['test_case',]},
                "boottime": {
                              #'boottime-analyze': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                              'boottime-first-analyze': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                              'boottime-second-analyze': ['KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg' ],
                            },
                "basic": {
                            "meminfo-first": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                            #"meminfo": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                            "meminfo-second": [ 'MemTotal', 'MemFree', 'MemAvailable'],
                         },

                'monkey': { 'monkey': ['monkey-network-stats'] },
                #'andebenchpro2015': {'andebenchpro2015':[] },
                'antutu6': { 'antutu6': ['antutu6-sum-mean'] },
                #'applications': {},
                'benchmarkpi': {'benchmarkpi': ['benchmarkpi-mean',]},
                'caffeinemark': {'caffeinemark': ['Caffeinemark-Collect-score-mean', 'Caffeinemark-Float-score-mean', 'Caffeinemark-Loop-score-mean',
                                      'Caffeinemark-Method-score-mean', 'Caffeinemark-score-mean', 'Caffeinemark-Sieve-score-mean', 'Caffeinemark-String-score-mean']},
                'cf-bench': {'cf-bench': ['cfbench-Overall-Score-mean', 'cfbench-Java-Score-mean', 'cfbench-Native-Score-mean']},
                'gearses2eclair': {'gearses2eclair': ['gearses2eclair-mean',]},
                'geekbench4': {'geekbench4': ['Geekbench4-Multi-Core-mean', 'Geekbench4-Single-Core-mean']},
                #'geekbench3': {'geekbench3': ['geekbench-multi-core-mean', 'geekbench-single-core-mean']},
                'javawhetstone': {'javawhetstone': ['javawhetstone-MWIPS-mean', 'javawhetstone-N1-float-mean', 'javawhetstone-N2-float-mean', 'javawhetstone-N3-if-mean', 'javawhetstone-N4-fixpt-mean',
                                       'javawhetstone-N5-cos-mean', 'javawhetstone-N6-float-mean', 'javawhetstone-N7-equal-mean', 'javawhetstone-N8-exp-mean',]},
                'jbench': {'jbench': ['jbench-mean',]},
                'linpack': {'linpack': ['Linpack-MFLOPSSingleScore-mean', 'Linpack-MFLOPSMultiScore-mean', 'Linpack-TimeSingleScore-mean', 'Linpack-TimeMultiScore-mean']},
                'quadrantpro': {'quadrantpro': ['quadrandpro-benchmark-memory-mean', 'quadrandpro-benchmark-mean', 'quadrandpro-benchmark-g2d-mean', 'quadrandpro-benchmark-io-mean',
                                     'quadrandpro-benchmark-cpu-mean', 'quadrandpro-benchmark-g3d-mean',]},
                'rl-sqlite': {'rl-sqlite': ['RL-sqlite-Overall-mean',]},
                'scimark': {'scimark': ['scimark-FFT-1024-mean', 'scimark-LU-100x100-mean', 'scimark-SOR-100x100-mean', 'scimark-Monte-Carlo-mean', 'scimark-Composite-Score-mean',]},
                'vellamo3': {'vellamo3': ['vellamo3-Browser-total-mean', 'vellamo3-Metal-total-mean', 'vellamo3-Multi-total-mean', 'vellamo3-total-score-mean',]},
             }
less_is_better_measurement = [
                              'KERNEL_BOOT_TIME_avg', 'ANDROID_BOOT_TIME_avg', 'TOTAL_BOOT_TIME_avg',
                              'benchmarkpi-mean',
                              'Linpack-TimeSingleScore-mean', 'Linpack-TimeMultiScore-mean', 'RL-sqlite-Overall-mean'
                             ]

glbenchmark25 = {
                'glbenchmark25': {'glbenchmark25': ['Fill-rate-C24Z16-mean', 'Fill-rate-C24Z16-Offscreen-mean',
                                                    'GLBenchmark-2.1-Egypt-Classic-C16Z16-mean', 'GLBenchmark-2.1-Egypt-Classic-C16Z16-Offscreen-mean',
                                                    'GLBenchmark-2.5-Egypt-HD-C24Z16-Fixed-timestep-mean', 'GLBenchmark-2.5-Egypt-HD-C24Z16-Fixed-timestep-Offscreen-mean',
                                                    'GLBenchmark-2.5-Egypt-HD-C24Z16-mean', 'GLBenchmark-2.5-Egypt-HD-C24Z16-Offscreen-mean',
                                                    'Triangle-throughput-Textured-C24Z16-Fragment-lit-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-Fragment-lit-mean',
                                                    'Triangle-throughput-Textured-C24Z16-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-mean',
                                                    'Triangle-throughput-Textured-C24Z16-Vertex-lit-mean', 'Triangle-throughput-Textured-C24Z16-Offscreen-Vertex-lit-mean',
                                                   ],},
              }

# test_suite is "vts-test"
vts = [
        'vts-hal',
        'vts-kernel-kselftest',
        'vts-kernel-ltp',
        'vts-kernel-part1',
        'vts-library',
        'vts-performance',
      ]

# test_suite is the same as job name
cts_v7a = [ 'cts-focused1-armeabi-v7a',
            'cts-focused2-armeabi-v7a',
            'cts-media-armeabi-v7a',
            'cts-media2-armeabi-v7a',
            'cts-opengl-armeabi-v7a',
            'cts-part1-armeabi-v7a',
            'cts-part2-armeabi-v7a',
            'cts-part3-armeabi-v7a',
            'cts-part4-armeabi-v7a',
            'cts-part5-armeabi-v7a',
          ]

# test_suite is the same as job name
cts_v8a = [ 'cts-focused1-arm64-v8a',
            'cts-focused2-arm64-v8a',
            'cts-media-arm64-v8a',
            'cts-media2-arm64-v8a',
            'cts-opengl-arm64-v8a',
            'cts-part1-arm64-v8a',
            'cts-part2-arm64-v8a',
            'cts-part3-arm64-v8a',
            'cts-part4-arm64-v8a',
            'cts-part5-arm64-v8a',
          ]

jobs_to_be_checked_array = [
    "basic", "boottime", "optee-xtest", "weekly", 'monkey',
    "antutu6", "andebenchpro2015", "benchmarkpi", "caffeinemark", "cf-bench", "gearses2eclair", "geekbench4", "glbenchmark25", "javawhetstone", "jbench", "linpack", "quadrantpro", "rl-sqlite", "scimark", "vellamo3",
    ]
jobs_to_be_checked_array = jobs_to_be_checked_array + cts_v8a + cts_v7a + vts

android_snapshot_url_base = "https://snapshots.linaro.org/android"
ci_job_url_base = 'https://ci.linaro.org/job'
android_build_config_url_base = "https://android-git.linaro.org/android-build-configs.git/plain"
template_url_prefix = "https://git.linaro.org/qa/test-plans.git/plain/android/"

TEST_RESULT_XML_NAME = 'test_result.xml'

pat_ignore = re.compile(".*("
                        "-stderr"
                        "|-sigma"
                        "|-max"
                        "|-min"
                        "|-itr\d+"
                        ")$")

                        #"|regression_\d+"

names_ignore = ["test-attachment",
                "test-skipped",
                'install-fastboot', 'install-adb',
                "subtests-fail-rate", 'test-cases-fail-rate', # "regression_4003_XTS", "regression_4003_NO_XTS",
                "tradefed-test-run", "check-adb-connectivity",
                "3D-mean","Overall_Score-mean", "Memory_Bandwidth_Add_Multi_Core-mean", "Platform-mean", "Memory_Bandwidth-mean", "Memory_Bandwidth_Copy_Single_Core-mean", "Memory_Latency_64M_range-mean", "Memory_Bandwidth_Scale_Single_Core-mean", "Memory_Bandwidth_Copy_Multi_Core-mean", "Storage-mean", "Memory_Bandwidth_Triad_Single_Core-mean", "CoreMark-PRO_Base-mean", "Memory_Bandwidth_Add_Single_Core-mean", "CoreMark-PRO_Peak-mean", "Memory_Bandwidth_Scale_Multi_Core-mean", "Memory_Latency-mean", "Memory_Bandwidth_Triad_Multi_Core-mean",
                "BOOTTIME_LOGCAT_ALL_COLLECT", "BOOTTIME_LOGCAT_EVENTS_COLLECT", "SERVICE_STARTED_ONCE", "BOOTTIME_ANALYZE", "BOOTTIME_DMESG_COLLECT", 'BOOTANIM_TIME', 'FS_MOUNT_DURATION', 'FS_MOUNT_TIME', 'KERNEL_BOOT_TIME', 'TOTAL_BOOT_TIME', 'ANDROID_SERVICE_START_TIME', 'ANDROID_BOOT_TIME', 'ANDROID_UI_SHOWN', 'SURFACEFLINGER_BOOT_TIME', 'INIT_TO_SURFACEFLINGER_START_TIME',
                "start_bootchart", "enabled_bootchart", "stop_bootchart", "rm_start_file", "generate-bootchart-graphic",
               ]

job_status_dict = {0: "Submitted",
                   1: "Running",
                   2: "Complete",
                   3: "Incomplete",
                   4: "Canceled",
                   5: "NoPermission",
                  }

job_status_string_int = dict((v,k) for k,v in job_status_dict.iteritems())
job_priority_list = ['high', 'medium', 'low']

class LavaInstance(object):
    def __init__(self, nick=None, user=None):
        self.nick = nick
        self.lava = LAVA.objects.get(nick=self.nick)
        self.domain = self.lava.domain
        self.lava_user = LAVAUser.objects.get(lava=self.lava, user_name=user)
        self.url = "https://%s:%s@%s/RPC2/" % (self.lava_user.user_name, self.lava_user.token, self.domain)
        self.job_url_prefix = "https://%s/scheduler/job" % self.domain
        self.server = AuthenticatingServerProxy(self.url, auth_backend=KeyringAuthBackend())

    def __str__(self):
        return self.url

DEFAULT_USER = "yongqin.liu"
LAVAS = {}
def initialize_all_lavas():
    global LAVAS
    if len(LAVAS) > 0:
        return LAVAS
    for lava in LAVA.objects.all():
        LAVAS[lava.nick] = LavaInstance(nick=lava.nick, user=DEFAULT_USER)


BUILD_CONFIGS = {}
BUILD_NAMES = []
def get_all_build_configs():
    global BUILD_NAMES
    global BUILD_CONFIGS

    if len(BUILD_CONFIGS) > 0:
        return BUILD_CONFIGS

    initialize_all_lavas()
    for build in BuildConfig.objects.all():
        build_bugzilla = BuildBugzilla.objects.get(build_name=build.build_name.replace('-premerge-ci', ''))
        new_bug_url = build_bugzilla.new_bug_url
        bugzilla_api_url = "%s/rest" % new_bug_url.replace('/enter_bug.cgi', '')

        build_config = {
                        'lava_server': LAVAS[build.lava.nick],
                        'img_ext': build.img_ext,
                        'template_dir': build.template_dir,
                        'base_build': {
                                        'build_name': build.base_build_name,
                                        'build_no': build.base_build_no,
                                       },
                        'build_bugzilla': build_bugzilla,
                        'bugzilla_instance': bugzilla.Bugzilla(url=bugzilla_api_url, api_key=BUGZILLA_API_KEY),
                       }
        BUILD_CONFIGS[build.build_name] = build_config
        BUILD_NAMES.append(build.build_name)

    BUILD_NAMES = sorted(BUILD_NAMES)
    return BUILD_CONFIGS


def get_all_build_names():
    if len(BUILD_NAMES) == 0:
        get_all_build_configs()

    return BUILD_NAMES


DEFAULT_BUILD_NAME = "android-lcr-reference-hikey-o"
def get_possible_builds(build_name=DEFAULT_BUILD_NAME):
    url = '%s/%s/' % (android_snapshot_url_base, build_name)
    response = urllib2.urlopen(url)
    html = response.read()

    pat = re.compile('<a href="/android/%s/(?P<build_no>\d+)/"' % build_name)
    all_builds = pat.findall(html)
    all_builds.reverse()
    return all_builds

def read_kernel_version(makefile_url):
    try:
        hdr = {
                'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:67.0) Gecko/20100101 Firefox/67.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
        req = urllib2.Request(makefile_url, headers=hdr)
        response = urllib2.urlopen(req)
    except urllib2.HTTPError as e:
        logger.info("makefile_url:%s error:%s" % (makefile_url, e))
        return "--"

    content = response.read()
    #VERSION = 4
    #PATCHLEVEL = 14
    #SUBLEVEL = 40
    pat_version = re.compile("\nVERSION = (?P<version_no>\d+)\n")
    version_vals = pat_version.findall(content)
    if len(version_vals) > 0:
        version_val = version_vals[0]
    else:
        version_val = 'X'

    pat_patchlevel = re.compile("\nPATCHLEVEL = (?P<patchlevel>\d+)\n")
    patchlevel_vals = pat_patchlevel.findall(content)
    if len(patchlevel_vals) > 0:
        patchlevel_val = patchlevel_vals[0]
    else:
        patchlevel_val = 'X'

    pat_sublevel = re.compile("\nSUBLEVEL = (?P<sublevel>\d+)\n")
    sublevel_vals = pat_sublevel.findall(content)
    if len(sublevel_vals) > 0:
        sublevel_val = sublevel_vals[0]
    else:
        sublevel_val = 'X'

    return "%s.%s.%s" % (version_val, patchlevel_val, sublevel_val)


def get_possible_templates(build_name=DEFAULT_BUILD_NAME):
    url = 'https://git.linaro.org/qa/test-plans.git/tree/android/%s' % get_all_build_configs()[build_name]['template_dir']
    try:
        response = urllib2.urlopen(url)
    except urllib2.HTTPError:
        return []
    html = response.read()

    pat = re.compile("'>(?P<template_name>template\S*.yaml)</a>")
    template_names = pat.findall(html)
    if len(template_names) == 0:
        pat = re.compile("'>(?P<template_name>template\S*.json)</a>")
        template_names = pat.findall(html)
    return sorted(template_names)

def get_possible_job_names(build_name=DEFAULT_BUILD_NAME):
    templates = get_possible_templates(build_name)
    pat = re.compile('job_name: "%%JOB_NAME%%-%%ANDROID_META_BUILD%%-(\S+)"')
    pat_json = re.compile('"job_name": "%%JOB_NAME%%-%%ANDROID_META_BUILD%%-(\S+)"')
    job_name_template_name_hash = {}
    for template in templates:
        url = '%s/%s/%s' % (template_url_prefix, get_all_build_configs()[build_name]['template_dir'], template)
        response = urllib2.urlopen(url)
        html = response.read()
        job_names = pat.findall(html)
        if len(job_names) == 0:
            job_names = pat_json.findall(html)

        job_name_template_name_hash[job_names[0]] = template

    sorted(job_name_template_name_hash.items())
    return job_name_template_name_hash


def get_jobs(build_name, build_no, lava, job_name_list=[]):
    ## TODO: have the same build tested on 2 different lava instances, and saved as base
    count_in_base = BaseResults.objects.filter(build_name=build_name, build_no=build_no).count()
    if count_in_base > 0:
        cached_in_base = True
    else:
        cached_in_base = False

    if not cached_in_base:
        ##jobs_to_be_checked = get_possible_job_names(build_name=build_name).keys()
        jobs_to_be_checked = jobs_to_be_checked_array
        if job_name_list is None or len(job_name_list) == 0 or len(job_name_list) > 1:
            search_condition = "description__icontains__%s-%s" % (build_name, build_no)
        elif len(job_name_list) == 1:
            search_condition = "description__icontains__%s-%s-%s" % (build_name, build_no, job_name_list[0])
        jobs_raw = lava.server.results.make_custom_query("testjob", search_condition)
    else:
        jobs_raw = JobCache.objects.filter(build_name=build_name, build_no=build_no, lava_nick=lava.nick)
        ## TODO include the lava_nick information in the result?
        #jobs_raw = JobCache.objects.filter(build_name=build_name, build_no=build_no)

    jobs = { }
    for job in jobs_raw:
        if not cached_in_base:
            logger.debug("%s %s", job.get("id"), job.get("description"))
            job_id = job.get("id")
            job_status = job.get("status")
            if job_status is None:
                ## https://staging.validation.linaro.org/static/docs/v2/scheduler.html
                job_state = job.get('state')
                job_health = job.get('health')
                if job_state == 0 or job_state ==1 or job_state == 2:
                    job_status = 0
                elif job_state == 3 or job_state == 4:
                    job_status = 1
                elif job_state == 5:
                    if job_health == 0 or job_health == 2:
                        job_status = 3
                    elif job_health == 1:
                        job_status = 2
                    elif job_health == 3:
                        job_status = 4
                    else:
                        ## not possible
                        pass
                else:
                    ## not possible
                    pass

            if job['start_time'] is None or job['end_time'] is None:
                job_duration = datetime.timedelta(seconds=0)
            else:
                job_start_time = datetime.datetime.strptime(str(job['start_time']), '%Y%m%dT%H:%M:%S')
                job_end_time =  datetime.datetime.strptime(str(job['end_time']), '%Y%m%dT%H:%M:%S')
                job_duration = job_end_time - job_start_time

            job_description = job.get("description")
            if job_name_list is None or len(job_name_list) == 0 or len(job_name_list) > 1:
                local_job_name = job_description.replace("%s-%s-" % (build_name, build_no), "")

                if local_job_name not in jobs_to_be_checked:
                    continue
                if len(job_name_list) > 1 and local_job_name not in job_name_list:
                    continue
            else:
                local_job_name = job_name_list[0]

            try:
                if not JobCache.objects.get(job_id=job_id, lava_nick=lava.nick).cached:
                    JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id).update(
                                        build_name=build_name, build_no=build_no,
                                        lava_nick=lava.nick, job_id=job_id, job_name=local_job_name, status=job_status,
                                        duration=job_duration, cached=False)
            except JobCache.DoesNotExist:
                JobCache.objects.create(
                                        build_name=build_name, build_no=build_no,
                                        lava_nick=lava.nick, job_id=job_id, job_name=local_job_name, status=job_status,
                                        duration=job_duration, cached=False)

        else:
            job_id = job.job_id
            job_status = job.status
            local_job_name = job.job_name
            job_duration = job.duration

        job_exist = jobs.get(local_job_name)
        if job_exist is not None:
            job_exist.get("id_status_list").append((job_id, job_status_dict[job_status]))
        else:
            jobs[local_job_name] = {
                                'name': local_job_name,
                                "id_status_list": [(job_id, job_status_dict[job_status])],
                             }
    return jobs


def get_job_name(job_dict):
    return  job_dict.get("name")


def get_yaml_result(job_id, lava):
    tests_res = {}
    for test_case in TestCase.objects.filter(job_id=job_id, lava_nick=lava.nick):
        tests_res[test_case.name] = {"name": test_case.name,
                                     "result": test_case.result,
                                     "measurement": test_case.measurement,
                                     "unit": test_case.unit,
                                     "suite": test_case.suite,
                                     "job_id": job_id,
                                     "lava_nick": lava.nick,
                                    }
    return tests_res

def cache_job_result_to_db(job_id, lava, job_status):
    total_res = []
    limit_number = 5000
    try:
        # res = lava.server.results.get_testjob_results_yaml(job_id)
        suite_list = yaml.load(lava.server.results.get_testjob_suites_list_yaml(job_id))
        for suite in suite_list:
            if suite['name'] == "lava":
                continue
            total_count = 0
            fetch_number = 0
            while True:
                suite_testcase_list = lava.server.results.get_testsuite_results_yaml(job_id,
                                                 suite['name'], limit_number, total_count)
                res_part = yaml.load(suite_testcase_list)
                total_res = total_res + res_part
                total_count = len(total_res)
                if len(res_part) < limit_number:
                    break

        for test in total_res:
            if test.get("suite") == "lava":
                continue
            if pat_ignore.match(test.get("name")):
                continue

            if test.get("name") in names_ignore:
                continue
            if test.get("measurement") and test.get("measurement") == "None":
                test["measurement"] = None
            else:
                test["measurement"] = "{:.2f}".format(float(test.get("measurement")))

            need_cache = False
            try:
                # not set again if already cached
                TestCase.objects.get(name=test.get("name"),
                                     suite=test.get("suite"),
                                     lava_nick=lava.nick,
                                     job_id=job_id)
            except TestCase.DoesNotExist:
                need_cache = True
            except TestCase.MultipleObjectsReturned:
                TestCase.objects.filter(name=test.get("name"),
                                        suite=test.get("suite"),
                                        lava_nick=lava.nick,
                                        job_id=job_id).delete()
                need_cache = True

            if need_cache:
                TestCase.objects.create(name=test.get("name"),
                                        result=test.get("result"),
                                        measurement=test.get("measurement"),
                                        unit=test.get("unit"),
                                        suite=test.get("suite"),
                                        lava_nick=lava.nick,
                                        job_id=job_id)

        JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id).update(cached=True,
                                                                           status=job_status_string_int[job_status])
    except xmlrpclib.ProtocolError as e:
        logger.info("Got error in cache_job_result_to_db for job_id=%s, lava_nick=%s: %s" % (job_id, lava.nick, str(e)))
        # for cases that no permission to check result submitted by others
        JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id).update(cached=False,
                                                                           status=5)

    except xmlrpclib.Fault as e:
        raise e
    except:
        raise

@login_required
def resubmit_job(request):
    job_ids = request.POST.getlist("job_ids")
    if len(job_ids) == 0:
        job_id = request.GET.get("job_id", "")
        build_name = request.GET.get("build_name", "")
        if not job_id:
            return render(request, 'job-resubmit.html',
                          {
                            'errors': True,
                          })
        job_ids = [job_id]
    else:
        build_name = request.POST.get("build_name", None)

    if len(job_ids) == 0:
        return render(request, 'job-resubmit.html',
                      {
                        'errors': True,
                      })

    lava = get_all_build_configs()[build_name]['lava_server']

    new_job_ids = []
    for job_id in job_ids:
        new_job_id = lava.server.scheduler.jobs.resubmit(job_id)
        if new_job_id:
            new_job_ids.append((job_id, new_job_id))
        else:
            new_job_ids.append((job_id, "--"))
    return render(request, 'job-resubmit.html',
                  {
                   'new_job_ids': new_job_ids,
                   'lava_server_job_prefix': lava.job_url_prefix,
                  }
        )

def get_default_build_no(all_build_numbers=[], defaut_build_no=None):
    if len(all_build_numbers) > 0:
        return  all_build_numbers[-1]
    elif defaut_build_no:
        return defaut_build_no
    else:
        return 0


def is_job_cached(job_id, lava):
    try:
        JobCache.objects.get(job_id=job_id, lava_nick=lava.nick, cached=True)
    except JobCache.DoesNotExist:
        return False

    return True

def get_test_results_for_build(build_name, build_no, job_name_list=[]):
    jobs_failed = []
    total_tests_res = {}
    lava = get_all_build_configs()[build_name]['lava_server']

    jobs = get_jobs(build_name, build_no, lava, job_name_list=job_name_list)
    for job_name, job_details in jobs.items():
        id_status_list = job_details.get("id_status_list")
        id_status_list.sort(reverse=True)
        job_total_res = {}
        result_job_id_status = None
        for job_id, job_status in id_status_list:
            if job_status != job_status_dict[2]:
                continue
            if not is_job_cached(job_id, lava):
                cache_job_result_to_db(job_id, lava, job_status)

            tests_res = get_yaml_result(job_id=job_id, lava=lava)
            if len(tests_res) != 0:
                # use the last to replace the first
                # might be better to change to use the better one
                # compare the 2 results
                job_total_res.update(tests_res)
                result_job_id_status = (job_id, job_status)
                break

        if len(job_total_res) == 0:
            jobs_failed.append(job_details)
        else:
            total_tests_res[job_name] = {
                                     "job_name": job_name,
                                     "id_status_list": id_status_list,
                                     "result_job_id_status": result_job_id_status,
                                     "build_no": build_no,
                                     "results": job_total_res}

    return (jobs_failed, total_tests_res)

def get_build_config_value(build_config_url, key="MANIFEST_BRANCH"):
    response = urllib2.urlopen(build_config_url)
    html = response.read()

    pat = re.compile('%s=(?P<value>android-.+)' % key)
    all_builds = pat.findall(html)
    if len(all_builds) > 0:
        return all_builds[0]
    else:
        return None

def get_commit_from_pinned_manifest(snapshot_url, path):
    response = urllib2.urlopen(snapshot_url)
    html = response.read()
    # <project groups="device,ti" name="android/kernel.git" path="kernel/ti/x15" remote="git-ti-com" revision="1f7e74a78f44783eeab13c9f39f9fda6ded0a593" upstream="p-ti-android-linux-4.4.y"/>
    # <project name="android-build-configs" remote="linaro-android" revision="aa9fdabaaf151224c63ed9110e1e32d474e6aaba" upstream="master"/>
    pat_path = re.compile('path="%s".* revision="(?P<commit_id>[\da-z]+)" ' % path)
    pat_name = re.compile('name="%s".* revision="(?P<commit_id>[\da-z]+)" ' % path)

    matches = pat_path.findall(html)
    if len(matches) > 0:
        return matches[0]
    else:
        matches = pat_name.findall(html)
        if len(matches) > 0:
            return matches[0]
        return None


@login_required
@permission_required('report.add_testcase', login_url='/report/accounts/no_permission/')
def jobs(request):
    build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)

    all_build_numbers = get_possible_builds(build_name)
    build_no = request.GET.get("build_no", get_default_build_no(all_build_numbers))

    (jobs_failed, total_tests_res) = get_test_results_for_build(build_name, build_no)

    build_config_url = "%s/%s" % (android_build_config_url_base, build_name.replace("android-", "").replace('-premerge-ci', ''))
    build_android_tag = get_build_config_value(build_config_url, key="MANIFEST_BRANCH")
    build_info = {
                    "build_name": build_name,
                    "build_no": build_no,
                    "ci_url_base": ci_job_url_base,
                    "snapshot_url_base": android_snapshot_url_base,
                    "android_tag": build_android_tag,
                    "build_config_url": build_config_url,
                    "build_numbers": get_possible_builds(build_name),
                 }

    return render(request, 'jobs.html',
                  {
                   'jobs_failed': jobs_failed,
                   'jobs_result': sorted(total_tests_res.items()),
                   'lava_server_job_prefix': get_all_build_configs()[build_name]['lava_server'].job_url_prefix,
                   'build_info': build_info,
                  }
        )


def compare_results_func(tests_result_1, tests_result_2):
    compare_results = {}
    for job_name, job_results in tests_result_1.items():
        compare_results[job_name] = {"result_1": job_results.get("results")}
    for job_name, job_results in tests_result_2.items():
        if compare_results.get(job_name):
            compare_results[job_name].update({"result_2": job_results.get("results")})
        else:
            compare_results[job_name] = {"result_2": job_results.get("results")}

    for job_name, result in compare_results.items():
        result_1 = result.get("result_1")
        result_2 = result.get("result_2")
        diff_result = {}
        if result_1 is None and result_2 is not None:
            for test_name, testcase_2 in result_2.items():
                result_measurement_2 = testcase_2.get("result")
                if testcase_2.get("measurement"):
                   result_measurement_2 = testcase_2.get("measurement")
                diff_result[test_name] = {"difference": "--",
                                          "percentage": 100,
                                          "result_measurement_1": None,
                                          "result_measurement_2": result_measurement_2,
                                          "unit": testcase_2.get("unit")
                                          }
        elif result_1 is not None and result_2 is None:
            for test_name, testcase_1 in result_1.items():
                result_measurement_1 = testcase_1.get("result")
                if testcase_1.get("measurement"):
                   result_measurement_1 = testcase_1.get("measurement")
                diff_result[test_name] = {"difference": "--",
                                          "percentage": -100,
                                          "result_measurement_1": result_measurement_1,
                                          "result_measurement_2": None,
                                          "unit": testcase_1.get("unit")
                                          }
        elif result_1 is not None and result_2 is not None:
            for test_name, testcase_1 in result_1.items():
                if result_2.get(test_name) is None:
                    result_measurement_1 = testcase_1.get("result")
                    if testcase_1.get("measurement"):
                        result_measurement_1 = testcase_1.get("measurement")
                    diff_result[test_name] = {"difference": "--",
                                              "percentage": -100,
                                              "result_measurement_1": result_measurement_1,
                                              "result_measurement_2": None,
                                              "unit": testcase_1.get("unit")
                                             }
                else:
                    testcase_2 = result_2.get(test_name)

                    result_measurement_1 = testcase_1.get("result")
                    if testcase_1.get("measurement"):
                        result_measurement_1 = testcase_1.get("measurement")
                    result_measurement_2 = testcase_2.get("result")
                    if testcase_2.get("measurement"):
                        result_measurement_2 = testcase_2.get("measurement")

                    if testcase_1.get("result") == "pass" and testcase_2.get("result") != "pass":
                        diff_result[test_name] = {"difference": "--", "percentage": -100}
                    elif testcase_1.get("result") != "pass" and testcase_2.get("result") == "pass":
                        diff_result[test_name] = {"difference": "--", "percentage": 100}
                    elif testcase_1.get("result") == "pass" and testcase_2.get("result") == "pass":
                        if testcase_1.get("measurement") is not None and testcase_2.get("measurement") is None:
                            diff_result[test_name] = {"difference": "--", "percentage": -100}
                        elif testcase_1.get("measurement") is None and testcase_2.get("measurement") is not None:
                            diff_result[test_name] = {"difference": "--", "percentage": 100}
                        elif testcase_1.get("measurement") is not None and testcase_2.get("measurement") is not None:
                            difference = float(testcase_2.get("measurement")) - float(testcase_1.get("measurement"))
                            if difference == 0:
                                percentage = 0
                            elif float(testcase_1.get("measurement")) == 0:
                                percentage = 100
                            else:
                                percentage = difference * 100 / float(testcase_1.get("measurement"))
                            diff_result[test_name] = {"difference": difference, "percentage": percentage}
                        else:
                            diff_result[test_name] = {"difference": 0, "percentage": 0}
                    else:
                        diff_result[test_name] = {"difference": 0, "percentage": 0}

                    diff_result[test_name].update({"result_measurement_1": result_measurement_1,
                                                   "result_measurement_2": result_measurement_2,
                                                   "unit": testcase_1.get("unit"),
                                                  })
            for test_name, testcase_2 in result_2.items():
                if diff_result.get(test_name) is None:
                    result_measurement_2 = testcase_2.get("result")
                    if testcase_2.get("measurement"):
                        result_measurement_2 = testcase_2.get("measurement")
                    diff_result[test_name] = {"difference": "--",
                                              "percentage": -100,
                                              "result_measurement_1": None,
                                              "result_measurement_2": result_measurement_1,
                                              "unit": testcase_2.get("unit")
                                             }
        else:
            # should be not possiblem here for both result_1 and result_2 are None
            pass

        result["result_diff"] = sorted(diff_result.items())

    return sorted(compare_results.items())


@login_required
@permission_required('report.add_testcase', login_url='/report/accounts/no_permission/')
def compare(request):
    compare_results = {}
    if request.method == 'POST':
        build_name = request.POST.get("build_name", DEFAULT_BUILD_NAME)
        all_build_numbers = get_possible_builds(build_name)
        build_no_1 = request.POST.get("build_no_1", "0")
        build_no_2 = request.POST.get("build_no_2", "0")
        (failed_jobs_1, tests_result_1) = get_test_results_for_build(build_name, build_no_1)
        (failed_jobs_2, tests_result_2) = get_test_results_for_build(build_name, build_no_2)
        compare_results = compare_results_func(tests_result_1, tests_result_2)
    else:
        build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
        all_build_numbers = get_possible_builds(build_name)
        build_no_1 = request.GET.get("build_no_1", "0")
        build_no_2 = request.GET.get("build_no_2", "0")


    form = {
                 "build_name": build_name,
                 "build_no_1": build_no_1,
                 "build_no_2": build_no_2,
                 "possible_numbers": all_build_numbers,
           }

    build_info = {
                    "build_name": build_name,
                 }
    return render(request, 'result-comparison.html',
                  {
                   "build_info": build_info,
                   'lava_server_job_prefix': get_all_build_configs()[build_name]['lava_server'].job_url_prefix,
                   'form': form,
                   'compare_results': compare_results,
                  }
        )


def get_test_results_for_job(build_name, lava, jobs=[]):
    all_build_numbers = get_possible_builds(build_name)
    checklist_results = {}
    for build_no in all_build_numbers:
        (failed_jobs, total_test_res) = get_test_results_for_build(build_name, build_no, job_name_list=jobs)
        if len(total_test_res) > 0:
            for job_name in jobs:
                checklist_for_one_job = checklist_results.get(job_name)
                if checklist_for_one_job is None:
                    checklist_for_one_job = {}
                    checklist_results[job_name] = checklist_for_one_job

                for testcase, testcase_result in total_test_res.get(job_name).get("results").items():
                    if checklist_for_one_job.get(testcase):
                        builds_res = checklist_for_one_job[testcase]["builds_res"]
                        builds_res.update({ build_no: testcase_result})
                    else:
                        builds_res = {build_no: testcase_result}
                        checklist_for_one_job[testcase] = { "name": testcase,
                                                            "builds_res": builds_res,
                                                            "job_name": job_name,
                                                          }

    checklist_results.items().sort()
    for job_name, checklist_for_one_job in checklist_results.items():
        checklist_for_one_job.items().sort()
    return (all_build_numbers, checklist_results)

@login_required
@permission_required('report.add_testcase', login_url='/report/accounts/no_permission/')
def checklist(request):
    checklist_results = {}
    all_build_numbers= []
    #form = CompareForm(request)
    if request.method == 'POST':
        build_name = request.POST.get("build_name", DEFAULT_BUILD_NAME)
        job_name = request.POST.get("job_name", "basic")
        (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, lava, jobs=[job_name])
        #(all_build_numbers, checklist_results) = get_test_results_for_job(build_name, lava_server, jobs=[])
    else:
        build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
        job_name = request.GET.get("job_name", "basic")

    job_template = get_possible_job_names(build_name=build_name)
    jobs_to_be_checked = job_template.keys()
    jobs_to_be_checked.sort()

    form = {
                 "build_name": build_name,
                 "job_name": job_name,
                 "possible_jobs": jobs_to_be_checked,
           }

    build_info = {
                    "build_name": build_name,
                 }
    return render(request, 'checklist.html',
                  {
                   "build_info": build_info,
                   'lava_server_job_prefix': get_all_build_configs()[build_name]['lava_server'].job_url_prefix,
                   'form': form,
                   'checklist_results': checklist_results,
                   'all_build_numbers': all_build_numbers,
                  }
        )



class JobSubmissionForm(forms.Form):
    initialize_all_lavas();
    nicks = sorted(LAVAS.keys())
    build_name = forms.ChoiceField(label='Build Name')
    build_no = forms.ChoiceField(label='Build No.')
    lava_nick= forms.ChoiceField(label='LAVA Instance', choices=(zip(nicks, nicks)))
    job_priority = forms.ChoiceField(label='Priority', choices=zip(job_priority_list, job_priority_list))
    jobs = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple)


@login_required
def submit_lava_jobs(request):
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        job_template = get_possible_job_names(build_name=build_name)
        jobs = job_template.keys()
        jobs.sort()
        all_build_numbers = get_possible_builds(build_name)
        all_build_numbers.reverse()

        form = JobSubmissionForm(request.POST)
        form.fields["build_name"].choices = zip(get_all_build_names(), get_all_build_names())
        form.fields["build_no"].choices = zip(all_build_numbers, all_build_numbers)
        form.fields["jobs"].choices = zip(jobs, jobs)
        if form.is_valid():
            cd = form.cleaned_data
            build_name = cd['build_name']
            build_no = cd['build_no']
            jobs = cd['jobs']
            job_priority = cd['job_priority']
            lava_nick = cd['lava_nick']
            ##lava = get_all_build_configs()[build_name]['lava_server']
            lava = LAVAS[lava_nick]

            submit_result = []
            for job_name in jobs:
                template = job_template[job_name]
                url = '%s/%s/%s' % (template_url_prefix, get_all_build_configs()[build_name]['template_dir'], template)
                response = urllib2.urlopen(url)
                html = response.read()

                meta_url = "%s/%s/%s" % (ci_job_url_base, build_name, build_no)
                download_url = "%s/%s/%s" % (android_snapshot_url_base, build_name, build_no)
                img_ext = get_all_build_configs()[build_name]['img_ext']
                job_definition = html.replace("%%JOB_NAME%%", build_name)\
                                     .replace("%%ANDROID_META_BUILD%%", build_no)\
                                     .replace("%%ANDROID_META_NAME%%", build_name)\
                                     .replace("%%ANDROID_META_URL%%", meta_url)\
                                     .replace("%%DOWNLOAD_URL%%", download_url)\
                                     .replace("%%ANDROID_BOOT%%", "%s/boot%s" % (download_url, img_ext))\
                                     .replace("%%ANDROID_SYSTEM%%", "%s/system%s" % (download_url, img_ext))\
                                     .replace("%%ANDROID_DATA%%", "%s/userdata%s" % (download_url, img_ext))\
                                     .replace("%%ANDROID_CACHE%%", "%s/cache%s" % (download_url, img_ext))\
                                     .replace("priority: medium", "priority: %s" % job_priority)
                try:
                    job_id = lava.server.scheduler.submit_job(job_definition)
                    submit_result.append({
                                           "job_name": job_name,
                                           "template": template,
                                           "template_url": url,
                                           "lava_server_job_prefix": lava.job_url_prefix,
                                           "job_id": job_id,
                                         })
                except xmlrpclib.Fault as e:
                    submit_result.append({
                                           "job_name": job_name,
                                           "template": template,
                                           "template_url": url,
                                           "lava_server_job_prefix": lava.job_url_prefix,
                                           "job_id": None,
                                           "error": str(e),
                                          })
            return render(request, 'submit_jobs.html',
                          {
                            "submit_result": submit_result,
                          })

        else:
            # not possible here since all are selectable elements
            return render(request, 'submit_jobs.html',
                      {
                        "form": form,
                      })
            #pass
    else:
        build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
        jobs = get_possible_job_names(build_name=build_name).keys()
        jobs.sort()
        all_build_numbers = get_possible_builds(build_name)
        all_build_numbers.reverse()
        defaut_build_no = all_build_numbers[0]
        defaut_build_no = request.POST.get("build_no", defaut_build_no)
        form_initial = {"build_name": build_name,
                        "build_no": defaut_build_no,
                        "job_priority": 'low',
                        'lava_nick': 'lkft',
                       }
        form = JobSubmissionForm(initial=form_initial)
        form.fields["build_name"].choices = zip(get_all_build_names(), get_all_build_names())
        form.fields["build_no"].choices = zip(all_build_numbers, all_build_numbers)
        form.fields["jobs"].choices = zip(jobs, jobs)

    return render(request, 'submit_jobs.html',
                      {
                        "form": form,
                      })

@login_required
def index(request):
    builds = {}
    for build_name in get_all_build_names():
        build_config_url = "%s/%s" % (android_build_config_url_base, build_name.replace("android-", "").replace('-premerge-ci', ''))
        build_android_tag = get_build_config_value(build_config_url, key="MANIFEST_BRANCH")
        builds[build_name] = {
                                "build_name": build_name,
                                "android_version": build_android_tag,
                                "kernel_version": "4.9",
                                "ci_link": "%s/%s" % (ci_job_url_base, build_name),
                                "android_build_config_link": build_config_url,
                                "snapshot_url": '%s/%s/' % (android_snapshot_url_base, build_name),
                                "job_status": "--",
                             }

    builds = collections.OrderedDict(sorted(builds.items()))
    return render(request, 'index.html',
                  {
                    "builds": builds,
                  })

@login_required
@permission_required('report.add_testcase', login_url='/report/accounts/no_permission/')
def test_report(request):
    build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
    all_build_numbers = get_possible_builds(build_name)
    build_no = request.GET.get("build_no", get_default_build_no(all_build_numbers))

    cache_to_base_request = request.GET.get("cache_to_base", None)
    count_in_base = BaseResults.objects.filter(build_name=build_name, build_no=build_no).count()
    if count_in_base > 0:
        ## already cached in base
        if cache_to_base_request == 'false':
            ## request from client that to delete the cache from base
            count_in_base = BaseResults.objects.filter(build_name=build_name, build_no=build_no).delete()
        else:
            ## no need to cache it again
            pass
        ## set to false to not cache it again in the following lines
        cache_to_base = False
    else:
        ## not cached in base yet
        if cache_to_base_request == 'true':
            ## cache will be done in the following lines
            cache_to_base = True
        else:
            ## no need to clean cache from base since there is no cache yet
            cache_to_base = False

    base_build_name = get_all_build_configs()[build_name]['base_build']['build_name']
    base_build_no = get_all_build_configs()[build_name]['base_build']['build_no']

    bugs_total = get_bugs_for_build(build_name=build_name)
    (jobs_failed, total_tests_res) = get_test_results_for_build(build_name, build_no)

    for failed_job in jobs_failed:
        job_name = failed_job.get('name')
        bugs = []
        for bug in bugs_total:
            if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                continue
            if bug.summary.find(' %s ' % job_name) >= 0:
                bugs.append(bug)
        failed_job['bugs'] = bugs

    lava_nick = get_all_build_configs()[build_name]['lava_server'].nick
    successful_job_ids = []
    #######################################################
    ## Get result for basic/optee/weekly tests
    #######################################################
    basic_optee_weekly = basic_weekly.copy()
    if build_name.find("hikey") >= 0:
        basic_optee_weekly.update(optee)
    basic_optee_weekly_res = []
    for job_name in sorted(basic_optee_weekly.keys()):
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            job_id = None
        else:
            job_id = job_res['result_job_id_status'][0]
            if job_id not in successful_job_ids:
                successful_job_ids.append(job_id)
        for test_suite in basic_optee_weekly[job_name]:
            if job_id is None:
                number_pass = 0
                number_fail = 0
                number_skip = 0
            else:
                number_pass = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_suite, result='pass'))
                number_fail = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_suite, result='fail'))
                number_skip = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_suite, result='skip'))

            try:
                base = BaseResults.objects.get(build_name=base_build_name, build_no=base_build_no, plan_suite=test_suite, module_testcase=test_suite)
            except BaseResults.DoesNotExist:
                base = None

            bugs = []
            for bug in bugs_total:
                if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                    continue
                if bug.summary.find(test_suite) >= 0:
                    bugs.append(bug)

            comments = Comment.objects.filter(build_name=build_name, plan_suite=test_suite, module_testcase=test_suite)

            number_total = number_pass + number_fail + number_skip
            number_passrate = 0
            if  number_total != 0:
                number_passrate = float(number_pass * 100 / number_total)
            basic_optee_weekly_res.append({'job_name': job_name,
                                           'job_id': job_id,
                                           'test_suite': test_suite,
                                           'number_pass': number_pass,
                                           'number_fail': number_fail,
                                           'number_skip': number_skip,
                                           'number_total': number_total,
                                           'number_passrate': number_passrate,
                                           'base': base,
                                           'bugs': bugs,
                                           'comments': comments,
                                          })

            if cache_to_base and ( job_id is not None):
                BaseResults.objects.create(build_name=build_name, build_no=build_no, job_name=job_name, job_id=job_id, lava_nick=lava_nick,
                                           number_pass=number_pass, number_fail=number_fail, number_total=number_total, number_passrate=number_passrate,
                                           plan_suite=test_suite, module_testcase=test_suite)


    #######################################################
    ## Get result for benchmark tests
    #######################################################
    benchmarks = benchmarks_common.copy()
    ## enable glbenchmark25 for both hikey and x15 builds
    ## if build_name.find("x15") >= 0:
    benchmarks.update(glbenchmark25)

    benchmarks_res = []
    for job_name in sorted(benchmarks.keys()):
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            job_id = None
        else:
            job_id = job_res['result_job_id_status'][0]
            if job_id not in successful_job_ids:
                successful_job_ids.append(job_id)
        for test_suite in sorted(benchmarks[job_name].keys()):
            test_cases = benchmarks[job_name][test_suite]
            for test_case in test_cases:
                if job_id is None:
                    unit = '--'
                    measurement = '--'
                else:
                    try:
                        test_case_res = TestCase.objects.get(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_suite, name=test_case)
                        unit = test_case_res.unit
                        measurement = test_case_res.measurement
                    except TestCase.DoesNotExist:
                        unit = '--'
                        measurement = '--'

                try:
                    base = BaseResults.objects.get(build_name=base_build_name, build_no=base_build_no, plan_suite=test_suite, module_testcase=test_case)
                except BaseResults.DoesNotExist:
                    base = None

                bugs = []
                for bug in bugs_total:
                    if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                        continue
                    if bug.summary.find(test_case) >= 0:
                        bugs.append(bug)
                    elif bug.summary.find(test_suite) >= 0:
                        bugs.append(bug)

                if len(bugs) == 0:
                    # if no bugs on the test suite/test cases,
                    # then check if there is any bug related to the job name
                    for bug in bugs_total:
                        if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                            continue
                        if bug.summary.find(job_name) >= 0:
                            if bug.summary.endswith(' %s' % job_name) or bug.summary.find(' %s ' % job_name) >=0 :
                                bugs.append(bug)

                comments = Comment.objects.filter(build_name=build_name, plan_suite=test_suite, module_testcase=test_case)

                if measurement == '--':
                    difference = -100
                elif base is None:
                    difference = 100
                else:
                    difference = (measurement - base.measurement ) * 100 / base.measurement
                    if test_case in less_is_better_measurement:
                        difference = difference * -1

                benchmarks_res.append({'job_name': job_name,
                                       'job_id': job_id,
                                       'test_case': test_case,
                                       'test_suite': test_suite,
                                       'unit': unit,
                                       'measurement': measurement,
                                       'base': base,
                                       'bugs': bugs,
                                       'comments': comments,
                                       'difference': difference,
                                      })
                if cache_to_base and job_id is not None:
                    if measurement == '--':
                        cache_measurement = -1
                    else:
                        cache_measurement = measurement
                    BaseResults.objects.create(build_name=build_name, build_no=build_no, job_name=job_name, job_id=job_id, lava_nick=lava_nick,
                                               unit=unit, measurement=cache_measurement,
                                               plan_suite=test_suite, module_testcase=test_case)


    def get_modules_hash_for_one_job(job_id=None, lava_nick=None, suite_name=None):
        modules_res = TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % suite_name)
        cts_one_job_hash = {}
        for module  in modules_res:
            temp_hash = {}
            module_name = None
            if not module.name.endswith('_done'):
                number = int(module.measurement)
                if module.name.endswith('_executed'):
                    module_name = module.name.replace('_executed', '')
                    temp_hash['total'] = number
                elif module.name.endswith('_passed'):
                    module_name = module.name.replace('_passed', '')
                    temp_hash['pass'] = number
                elif module.name.endswith('_failed'):
                    module_name = module.name.replace('_failed', '')
                    temp_hash['fail'] = number
                else:
                    # there should be no such case
                    pass
            else:
                # No need to deal with _done result here
                module_name = module.name.replace('_done', '')
                temp_hash['done'] = module.result
                pass

            # modules should not be None here
            if cts_one_job_hash.get(module_name) is None:
                cts_one_job_hash[module_name] = temp_hash
            else:
                cts_one_job_hash[module_name].update(temp_hash)
        return cts_one_job_hash

    def get_cts_vts_res(total_tests_res={}, cts_vts=[], successful_job_ids=[],
                        lava_nick=None, bugs_total=[],
                        base_build_name=None, base_build_no=None,
                        build_name=None, build_no=None):
        cts_vts_job_ids = []
        cts_vts_res = []
        summary = {
                    'pass': 0,
                    'fail': 0,
                    'total': 0,
                   }
        for job_name in sorted(cts_vts):
            job_res = total_tests_res.get(job_name)
            if job_res is None:
                cts_vts_res.append({'job_name': job_name,
                                'job_id': None,
                                'module_name': '--',
                                'number_pass': 0,
                                'number_fail': 0,
                                'number_total': 0,
                                'number_passrate': 0,
                               })
            else:
                job_id = job_res['result_job_id_status'][0]
                if job_id not in successful_job_ids:
                    successful_job_ids.append(job_id)

                cts_one_job_hash = get_modules_hash_for_one_job(job_id=job_id, lava_nick=lava_nick, suite_name=job_name)
                for module_name in sorted(cts_one_job_hash.keys()):
                    module_res = cts_one_job_hash[module_name]
                    number_pass = module_res.get('pass')
                    number_fail = module_res.get('fail')
                    number_total = module_res.get('total')
                    module_done = module_res.get('done', 'pass')
                    if number_total == 0:
                        number_passrate = 0
                    else:
                        number_passrate = float(number_pass * 100 / number_total )

                    try:
                        base = BaseResults.objects.get(build_name=base_build_name, build_no=base_build_no, plan_suite=job_name, module_testcase=module_name)
                    except BaseResults.DoesNotExist:
                        base = None

                    bugs = []
                    for bug in bugs_total:
                        if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                            continue
                        if bug.summary.find('arm64-v8a') >= 0 or bug.summary.find('armeabi-v7a') >=0:
                            if bug.summary.find(module_name.split('.')[0]) < 0:
                                continue
                        ## vts module_name=armeabi-v7a.BinderPerformanceTest
                        if bug.summary.endswith('%s' % module_name.split('.')[1]) \
                            or bug.summary.find('%s ' % module_name.split('.')[1]) >=0 \
                            or bug.summary.find(' %s#' % module_name.split('.')[1]) >=0:
                                bugs.append(bug)

                    if len(bugs) == 0 and (module_done == 'fail' or number_passrate < 100):
                        # if no bugs on the test suite/test cases reported,
                        # then check if there is any bug related to the job name if there is any failures with this
                        for bug in bugs_total:
                            if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                                continue
                            if bug.summary.find('#') < 0:
                                if bug.summary.endswith(' %s' % job_name) or bug.summary.find(' %s ' % job_name) >=0 :
                                    bugs.append(bug)

                    comments = list(Comment.objects.filter(build_name=build_name, plan_suite=job_name, module_testcase=module_name))

                    cts_vts_res.append({'job_name': job_name,
                                    'job_id': job_id,
                                    'module_name': module_name,
                                    'module_abi': module_name.split('.')[0],
                                    'module_name_noabi': module_name.split('.')[1],
                                    'number_pass': number_pass,
                                    'number_fail': number_fail,
                                    'number_total': number_total,
                                    'number_passrate': number_passrate,
                                    'module_done': module_done,
                                    'base': base,
                                    'bugs': bugs,
                                    'comments': comments,
                                   })
                    if job_id and str(job_id) not in cts_vts_job_ids:
                        cts_vts_job_ids.append(str(job_id))
                    if cache_to_base:
                        BaseResults.objects.create(build_name=build_name, build_no=build_no, job_name=job_name, job_id=job_id, lava_nick=lava_nick,
                                                   number_pass=number_pass, number_fail=number_fail, number_total=number_total, number_passrate=number_passrate,
                                                   plan_suite=job_name, module_testcase=module_name)

                    summary['pass'] = summary['pass'] + number_pass
                    summary['fail'] = summary['fail'] + number_fail
                    summary['total'] = summary['total'] + number_total


        pass_rate = 0
        if  summary['total'] != 0:
            pass_rate = float(summary['pass'] * 100 / summary['total'])
        cts_vts_res.append({'job_name': "Summary",
                        'job_id': None,
                        'module_name': 'Total',
                        'number_pass': summary['pass'],
                        'number_fail': summary['fail'],
                        'number_total': summary['total'],
                        'number_passrate': pass_rate,
                       })
        return (cts_vts_res, cts_vts_job_ids)

    #########################################################
    ########### result for cts ##############################
    #########################################################
    cts = cts_v7a + []
    if build_name.find("x15") < 0:
        cts = cts_v7a + cts_v8a
    (cts_res, cts_job_ids) = get_cts_vts_res(cts_vts=cts,
                              total_tests_res=total_tests_res,
                              successful_job_ids=successful_job_ids,
                              lava_nick=lava_nick,
                              base_build_name=base_build_name,
                              base_build_no=base_build_no,
                              bugs_total=bugs_total,
                              build_name=build_name,
                              build_no=build_no)

    (vts_res, vts_job_ids) = get_cts_vts_res(cts_vts=vts,
                              total_tests_res=total_tests_res,
                              successful_job_ids=successful_job_ids,
                              lava_nick=lava_nick,
                              base_build_name=base_build_name,
                              base_build_no=base_build_no,
                              bugs_total=bugs_total,
                              build_name=build_name,
                              build_no=build_no)
    ##############################################################
    ## get job duration information from JobCache
    ##############################################################
    jobs_duration = []
    total_duration = datetime.timedelta(seconds=0)
    for job_id in successful_job_ids:
        try:
            job_cache_info = JobCache.objects.get(job_id=job_id, lava_nick=lava_nick)
            jobs_duration.append(job_cache_info)
            total_duration = total_duration + job_cache_info.duration
        except JobCache.DoesNotExist:
           pass

    ##############################################################
    try:
        build_summary = BuildSummary.objects.get(build_name=build_name, build_no=build_no)
        build_config_url = "%s/%s?id=%s" % (android_build_config_url_base, build_summary.build_config, build_summary.build_commit)
        kernel_version = build_summary.kernel_version
        kernel_url = build_summary.kernel_url
        build_android_tag = build_summary.android_version
        firmware_url = build_summary.firmware_url
        firmware_version = build_summary.firmware_version
        images_url = build_summary.images_url
        toolchain_info = build_summary.toolchain_info
    except BuildSummary.DoesNotExist:
        images_url = '%s/%s/%s' % (android_snapshot_url_base, build_name, build_no)
        pinned_manifest_url = '%s/pinned-manifest.xml' % images_url
        if build_name.find('x15') >= 0 or build_name.find('am65x') >= 0 :
            kernel_commit = get_commit_from_pinned_manifest(pinned_manifest_url, 'kernel/ti/4.19')
            kernel_url = "http://git.ti.com/ti-linux-kernel/ti-linux-kernel/blobs/raw/%s/Makefile" % kernel_commit
            kernel_version = read_kernel_version(kernel_url)
            logger.info("kernel_url=%s kernel_version=%s" % (kernel_url, kernel_version))
        elif build_name.find('hikey') >= 0:
            kernel_commit = get_commit_from_pinned_manifest(pinned_manifest_url, 'kernel/linaro/hisilicon-4.14')
            kernel_url = "https://android-git.linaro.org/kernel/hikey-linaro.git/plain/Makefile?id=%s" % kernel_commit
            kernel_version = read_kernel_version(kernel_url)
        else:
            kernel_url = '--'
            kernel_version = '--'

        android_build_config_commit = get_commit_from_pinned_manifest(pinned_manifest_url, 'android-build-configs')
        build_config_url = "%s/%s?id=%s" % (android_build_config_url_base, build_name.replace("android-", "").replace('-premerge-ci', ''), android_build_config_commit)
        build_android_tag = get_build_config_value(build_config_url, key="MANIFEST_BRANCH")
        toolchain_info = '--'
        firmware_version = '--'
        firmware_url = '--'

    ## bugzilla related information
    build_bugzilla = BuildBugzilla.objects.get(build_name=build_name.replace('-premerge-ci', ''))
    build_new_bug_url_prefix = '%s?product=%s&op_sys=%s&bug_severity=%s&component=%s&keywords=%s&rep_platform=%s&version=%s&short_desc=%s: ' % ( build_bugzilla.new_bug_url,
                                                                                                                                      build_bugzilla.product,
                                                                                                                                      build_bugzilla.op_sys,
                                                                                                                                      build_bugzilla.bug_severity,
                                                                                                                                      build_bugzilla.component,
                                                                                                                                      build_bugzilla.keywords,
                                                                                                                                      build_bugzilla.rep_platform,
                                                                                                                                      get_bug_version_from_build_name(build_name.replace('-premerge-ci', '')),
                                                                                                                                      build_bugzilla.short_desc_prefix,
                                                                                                                                     )

    count_in_base = BaseResults.objects.filter(build_name=build_name, build_no=build_no).count()
    if count_in_base > 0:
        cached_in_base = True
    else:
        cached_in_base = False

    build_info = {
                    'build_name': build_name,
                    'build_no': build_no,
                    'build_numbers': all_build_numbers,
                    'build_config_url': build_config_url,
                    'build_config_name': build_name.replace("android-", ""),
                    'android_version': build_android_tag,
                    'kernel_version': kernel_version,
                    'kernel_url': kernel_url,
                    'ci_link': '%s/%s/%s' % (ci_job_url_base, build_name, build_no),
                    'base_build_no': base_build_no,
                    'new_bug_url_prefix': build_new_bug_url_prefix,
                    'bugzilla_show_bug_prefix': '%s/show_bug.cgi?id=' % build_bugzilla.new_bug_url.replace('/enter_bug.cgi', ''),
                    'firmware_url': firmware_url,
                    'firmware_version': firmware_version,
                    'toolchain_info': toolchain_info,
                    'images_url': images_url,
                    'cached_in_base': cached_in_base,
                 }

    no_resolved_bugs = []
    for bug in bugs_total:
        if bug.status == 'RESOLVED':
            continue
        no_resolved_bugs.append(bug)

    return render(request, 'test_report.html',
                  {
                   'lava_server_job_prefix': get_all_build_configs()[build_name]['lava_server'].job_url_prefix,
                   'build_info': build_info,
                   'basic_optee_weekly_res': basic_optee_weekly_res,
                   'benchmarks_res': benchmarks_res,
                   'vts_res': vts_res,
                   'vts_job_ids': ','.join(vts_job_ids),
                   'cts_res': cts_res,
                   'cts_job_ids': ','.join(cts_job_ids),
                   'build_bugs': no_resolved_bugs,
                   'jobs_failed': jobs_failed,
                   'jobs_duration': jobs_duration,
                   'total_duration': total_duration,
                  }
        )

class BugForm(forms.ModelForm):
    class Meta:
        model = Bug
        fields = ['build_name', 'build_no', 'bug_id', 'link', 'subject', 'status', 'plan_suite', 'module_testcase']


@login_required
def add_bug(request):
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        build_no = request.POST.get("build_no")
        form = BugForm(request.POST)
        form.save()

        build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                      'message': 'Added bug successfully',
                     }
    else: # GET
        build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
        build_no = request.GET.get("build_no", '')
        plan_suite = request.GET.get("plan_suite", '')
        module_testcase = request.GET.get("module_testcase", '')
        form_initial = {"build_name": build_name,
                        "build_no": build_no,
                        "plan_suite": plan_suite,
                        "status": 'unconfirmed',
                        "module_testcase": module_testcase,
                       }
        form = BugForm(initial=form_initial)

        build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                     }

    return render(request, 'add_bug.html',
                      {
                        "form": form,
                        "build_info": build_info,
                      })


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['build_name', 'build_no', 'plan_suite', 'module_testcase', 'comment']


@login_required
def add_comment(request):
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        build_no = request.POST.get("build_no")
        form = CommentForm(request.POST)
        form.save()

        build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                      'message': 'Added comment successfully',
                     }
    else: # GET
        build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)
        build_no = request.GET.get("build_no", '')
        plan_suite = request.GET.get("plan_suite", '')
        module_testcase = request.GET.get("module_testcase", '')
        form_initial = {"build_name": build_name,
                        "build_no": build_no,
                        "plan_suite": plan_suite,
                        "status": 'unconfirmed',
                        "module_testcase": module_testcase,
                       }
        form = CommentForm(initial=form_initial)

        build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                     }

    return render(request, 'add_comment.html',
                      {
                        "form": form,
                        "build_info": build_info,
                      })


@login_required
def show_trend(request):
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        job_name = request.POST.get("job_name")
        test_suite = request.POST.get("test_suite", '')
        test_case = request.POST.get("test_case", '')
        category = request.POST.get("category", 'benchmark')
    else: # GET
        build_name = request.GET.get("build_name")
        job_name = request.GET.get("job_name")
        test_suite = request.GET.get("test_suite", '')
        test_case = request.GET.get("test_case" , '')
        category = request.GET.get("category", 'benchmark')

    chart_title = test_suite

    if category == 'cts':
        if test_case: # only module specified
            test_cases = [
                            '%s_passed' % test_case,
                            '%s_failed' % test_case,
                            '%s_executed' % test_case,
                         ]
            chart_title = '%s %s' % (chart_title, test_case)
        else:
            #TODO when job specified
            test_cases = []
    elif category == 'vts':
        # TODO
        test_cases = []
    elif category == 'basic':
        test_cases = []
        basic_optee_weekly = basic_weekly.copy()
        if build_name.find("hikey") >= 0:
            basic_optee_weekly.update(optee)
        if job_name:
            test_cases.extend(basic_optee_weekly[job_name])
        else:
            for job in basic_optee_weekly:
                test_cases.extend(basic_optee_weekly[job])

    else:
        # benchmark
        if test_case: # testcase specified
            test_cases = [ test_case ]
            chart_title = '%s %s' % (chart_title, test_case)
        else: # both test suite and test case specified
            test_cases = benchmarks_common.get(job_name).get(test_suite)

    if category == 'basic':
        if job_name:
            jobs_raw = list(JobCache.objects.filter(build_name=build_name, cached=True, job_name=job_name))
        else:
            basic_optee_weekly = basic_weekly.copy()
            if build_name.find("hikey") >= 0:
                basic_optee_weekly.update(optee)
            jobs_raw = []
            for job in basic_optee_weekly:
                jobs_raw = jobs_raw + list(JobCache.objects.filter(build_name=build_name, cached=True, job_name=job))
    else:
        jobs_raw = list(JobCache.objects.filter(build_name=build_name, cached=True, job_name=job_name))

    trend_data = []
    for job in jobs_raw:
        job_id = job.job_id
        lava_nick = job.lava_nick
        build_no = job.build_no
        one_build = { "build_no": build_no,
                      "build_name": build_name,
                      "job_id": job_id,
                      "lava_nick": lava_nick
                    }
        test_cases_res = []
        for test_case in test_cases:
            if category == 'basic':
                number_pass = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_case, result='pass'))
                #number_fail = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_case, result='fail'))
                #number_skip = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % test_case, result='skip'))
                test_cases_res.append({
                                         "test_case": test_case,
                                         "measurement": number_pass,
                                         "unit": '--',
                                         "suite": test_case
                                        })
                #logger.info( "%s : %s" % (test_case, str(test_cases_res)))
            else:
                try:
                    #test_result = TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith=test_suite, name=test_case)[0]
                    test_result = TestCase.objects.get(job_id=job_id, lava_nick=lava_nick, suite__endswith=test_suite, name=test_case)
                    test_cases_res.append({
                                             "test_case": test_case,
                                             "measurement": test_result.measurement,
                                             "unit": test_result.unit,
                                             "suite": test_suite
                                            })
                except TestCase.DoesNotExist:
                    test_cases_res.append({
                                         "test_case": test_case,
                                         "measurement": 0,
                                         "unit": '--',
                                         "suite": test_suite,
                                        })

        one_build['test_cases_res'] = test_cases_res
        trend_data.append(one_build)

    def get_buildno(item):
        return int(item.get('build_no'))

    sorted_trend_data = sorted(trend_data, key=get_buildno, reverse=True)
    return render(request, 'show_trend.html',
                      {
                        "build_name": build_name,
                        "test_cases": test_cases,
                        "trend_data": sorted_trend_data,
                        'chart_title': chart_title,
                      })


def get_result_file_path(job_id=None, build_name=None, build_no=None):
    if (job_id is None) or (build_name is None) or ( build_no is None):
        return None
    lava_nick = get_all_build_configs()[build_name]['lava_server'].nick
    return os.path.join(FILES_DIR, "%s-%s-%s-%s.zip" % (lava_nick, job_id, build_name, build_no))

def get_attachment_url(job_id=None, lava_server=None, build_name=None):
    attachment_case_name = 'test-attachment'
    cts_vts = [] + cts_v7a + cts_v8a + vts

    suite_list =  yaml.load(lava_server.results.get_testjob_suites_list_yaml(job_id))
    for test_suite in suite_list:
        # 1_cts-focused1-arm64-v8a
        test_suite_name = re.sub('^\d+_', '', test_suite['name'])
        if not test_suite_name in cts_vts:
            continue
        attachment = yaml.load(lava_server.results.get_testcase_results_yaml(job_id, test_suite['name'], attachment_case_name))
        # http://archive.validation.linaro.org/artifacts/team/qa/2018/11/07/17/43/tradefed-output-20181107180851.tar.xz
        return attachment[0].get('metadata').get('reference')
    return None


def get_bug_version_from_build_name(build_name=None):
    if not build_name:
        return 'Master'
    version_str = None
    if build_name.endswith('-p') or build_name.endswith('-p-premerge-ci'):
        version_str = 'PIE-9.0'
    elif build_name.endswith('-o') or build_name.endswith('-o-premerge-ci'):
        version_str = 'OREO-8.1'
    else:
        version_str = 'Master'
    return version_str


def get_bugs_for_build(build_name=None):
    bugs = []
    if not build_name:
        return bugs

    bugzilla_instance = get_all_build_configs()[build_name]['bugzilla_instance']
    build_bugzilla = get_all_build_configs()[build_name]['build_bugzilla']

    terms = [
                {u'product': build_bugzilla.product},
                {u'component': build_bugzilla.component},
                {u'platform': build_bugzilla.rep_platform},
                {u'op_sys': build_bugzilla.op_sys},
                {u'version': get_bug_version_from_build_name(build_name)},
                {u'keywords': 'LCR'}
            ]

    for bug in bugzilla_instance.search_bugs(terms).bugs:
        bugs.append(bugzilla.DotDict(bug))


    def get_bug_summary(item):
        return item.get('summary')

    sorted_bugs = sorted(bugs, key=get_bug_summary)
    return sorted_bugs


@login_required
def show_cts_vts_failures(request):

    # does not work
    def download_request(url, path):
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(path, "wb") as fd:
                 fd.write(r.content)
            #with open(temp_path, 'wb') as temp_fd:
            #r.raw.decode_content = True
            #shutil.copyfileobj(r.raw, fd)
            print("File is saved to %s" % path)
        else:
            print('Failed to download file: %s' % attachment_url)

    def download_urllib2(url, path):
        import urllib2
        f = urllib2.urlopen(url)
        data = f.read()
        with open(path, "wb") as fd:
            fd.write(data)
        print("File is saved to %s" % path)

    def download_urllib(url, path):
        def Schedule(a,b,c):
            '''
            a: the number downloaded of blocks
            b: the size of the block
            c: the size of the file
            '''
            per = 100.0 * a * b / c
            if per > 100 :
                per = 100
                sys.stdout.write("\r %.2f%%" % per)
                sys.stdout.flush()
                sys.stdout.write('\n')
            else:
                sys.stdout.write("\r %.2f%%" % per)
                sys.stdout.flush()
        logger.info('Start to download: %s to path: %s' % (url, path))
        urllib.urlretrieve(url, path, Schedule)
        print("File is saved to %s" % path)


    def extract(result_zip_path, failed_testcases_all={}, metadata={}):
        '''
            failures = {
                    'module_name': {
                        'test_name': {
                                        'test_name': 'test_name', #class#TestName
                                        'stacktrace': 'stackstrace',
                                        'abis': [abi1, abi2],
                                        'job_id': 'job_id',
                                    },
                    },
            }
        '''
        # no affect for cts result and non vts-hal test result
        vts_abi_suffix_pat = re.compile(r"_32bit$|_64bit$")
        with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
            try:
                root = ET.fromstring(f_zip_fd.read(TEST_RESULT_XML_NAME))
                for elem in root.findall('Module'):
                    abi = elem.attrib['abi']
                    module_name = elem.attrib['name']

                    failed_tests_module = failed_testcases_all.get(module_name)
                    if not failed_tests_module:
                        failed_tests_module = {}
                        failed_testcases_all[module_name] = failed_tests_module

                    # test classes
                    test_cases = elem.findall('.//TestCase')
                    for test_case in test_cases:
                        failed_tests = test_case.findall('.//Test[@result="fail"]')
                        for failed_test in failed_tests:
                            test_name = '%s#%s' % (test_case.get("name"), vts_abi_suffix_pat.sub('', failed_test.get("name")))
                            stacktrace = failed_test.find('.//Failure/StackTrace').text
                            ## ignore duplicate cases as the jobs are for different modules
                            failed_testcase = failed_tests_module.get(test_name)
                            if failed_testcase:
                                if failed_testcase.get('abi_stacktrace').get(abi) is None:
                                    failed_testcase.get('abi_stacktrace')[abi] = stacktrace
                                job_id = metadata.get('job_id')
                                if not job_id in failed_testcase.get('job_ids'):
                                    failed_testcase.get('job_ids').append(job_id)
                            else:
                                failed_tests_module[test_name]= {
                                                                    'test_name': test_name,
                                                                    'abi_stacktrace': {abi: stacktrace},
                                                                    'job_ids': [metadata.get('job_id')],
                                                                }
            except ET.ParseError as e:
                logger.error('xml.etree.ElementTree.ParseError: %s' % e)
                logger.info('Please Check %s manually' % result_zip_path)

    def extract_save_result(tar_path, result_zip_path):
        # https://pymotw.com/2/zipfile/
        tar = tarfile.open(tar_path, "r")
        for f_name in tar.getnames():
            if f_name.endswith("/test_result.xml"):
                result_fd = tar.extractfile(f_name)
                with zipfile.ZipFile(result_zip_path, 'w') as f_zip_fd:
                    f_zip_fd.writestr(TEST_RESULT_XML_NAME, result_fd.read(), compress_type=zipfile.ZIP_DEFLATED)
                    logger.info('Save result in %s to %s' % (tar_path, result_zip_path))

        tar.close()

    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        build_no = request.POST.get("build_no")
        job_ids_str = request.POST.get("job_ids", '')
    else: # GET
        build_name = request.GET.get("build_name")
        build_no = request.GET.get("build_no")
        job_ids_str = request.GET.get("job_ids", '')

    job_ids = job_ids_str.split(',')

    lava_server = get_all_build_configs()[build_name]['lava_server'].server
    lava_nick = get_all_build_configs()[build_name]['lava_server'].nick
    bugzilla_instance = get_all_build_configs()[build_name]['bugzilla_instance']
    build_bugzilla = get_all_build_configs()[build_name]['build_bugzilla']

    logger.info('Start to get attachment url info for jobs: %s' % (str(job_ids)))
    job_attachments_url = {}
    for job_id in job_ids:
        result_file_path = get_result_file_path(build_name=build_name, build_no=build_no, job_id=job_id)
        logger.info('result_file_path: %s' % (result_file_path))
        if os.path.exists(result_file_path):
            continue
        attachment_url = get_attachment_url(job_id=job_id, lava_server=lava_server, build_name=build_name)
        if attachment_url is not None:
            job_attachments_url[job_id] = attachment_url
            logger.info('The attachment url for job(%s) is:  %s' % (str(job_id), job_attachments_url[job_id]))

    logger.info('Start to download result file for jobs: %s' % (str(job_ids)))
    for job_id in job_ids:
        if not job_attachments_url.get(job_id):
            logger.warn('No attachment_url for job: %s' % (str(job_id)))
            continue
        (temp_fd, temp_path) = tempfile.mkstemp(suffix='.tar.xz', text=False)
        download_urllib(job_attachments_url.get(job_id), temp_path)
        tar_f = temp_path.replace(".xz", '')
        os.system("xz -d %s" % temp_path)
        result_file_path = get_result_file_path(build_name=build_name, build_no=build_no, job_id=job_id)
        extract_save_result(tar_f, result_file_path)
        os.unlink(tar_f)

    download_failures = []
    for job_id in job_ids:
        result_file_path = get_result_file_path(build_name=build_name, build_no=build_no, job_id=job_id)
        if not os.path.exists(result_file_path):
            download_failures.append(job_id)
            logger.warn('No result file saved for job: %s' % (str(job_id)))

    logger.info('Start to extract failures for jobs: %s' % (str(job_ids)))
    failures = {}
    if download_failures:
        logger.warn('Jobs that failed to find result files: %s' % (str(download_failures)))
        # process for download failures
        pass
    else:
        for job_id in job_ids:
            result_file_path = get_result_file_path(build_name=build_name, build_no=build_no, job_id=job_id)
            metadata = {
                'job_id': job_id,
                'result_url': job_attachments_url.get(job_id),
                'lava_nick': lava_nick,
                'build_no': build_no,
                'build_name': build_name,
                }
            extract(result_file_path, failed_testcases_all=failures, metadata=metadata)

    '''
        failures = {
                'module_name': {
                    'test_name': {
                                    'test_name': 'test_name',
                                    'stacktrace': 'stackstrace',
                                    'abis': [abi1, abi2]
                                },
                },
        }
    '''
    bugs = get_bugs_for_build(build_name=build_name)
    for module_name, failures_in_module in failures.items():
        for test_name, failure in failures_in_module.items():
            abi_stacktrace = failure.get('abi_stacktrace')
            abis = sorted(abi_stacktrace.keys())

            stacktrace_msg = ''
            if (len(abis) == 2) and (abi_stacktrace.get(abis[0]) != abi_stacktrace.get(abis[1])):
                for abi in abis:
                    stacktrace_msg = '%s\n\n%s:\n%s' % (stacktrace_msg, abi, abi_stacktrace.get(abi))
            else:
                stacktrace_msg = abi_stacktrace.get(abis[0])

            failure['abis'] = abis
            failure['stacktrace'] = stacktrace_msg.strip()

            if test_name.find(module_name) >=0:
                # vts test, module name is the same as the test name.
                search_key = test_name
            else:
                search_key = '%s %s' % (module_name, test_name)

            module_bugs = []
            for bug in bugs:
                if bug.summary.find(search_key) >= 0:
                    if not bug.summary.endswith(search_key) and bug.summary.find('%s ' % search_key) < 0:
                         continue

                    if failure.get('bugs'):
                        failure['bugs'].append(bug)
                    else:
                        failure['bugs'] = [bug]
                elif bug.summary.find('#') < 0 and bug.summary.find(module_name) >= 0:
                    if bug.summary.endswith(' %s' % module_name) or bug.summary.find(' %s ' % module_name) >=0 :
                        module_bugs.append(bug)

            if not failure.get('bugs'):
                # if no bugs on the test suite/test cases,
                # then check if there is any bug related to the job name
                failure['module_bugs'] = module_bugs

    # sort failures
    for module_name, failures_in_module in failures.items():
        failures[module_name] = collections.OrderedDict(sorted(failures_in_module.items()))
    failures = collections.OrderedDict(sorted(failures.items()))

    build_info = {
                    'build_name': build_name,
                    'build_no': build_no,
                    'bugzilla_show_bug_prefix': '%s/show_bug.cgi?id=' % build_bugzilla.new_bug_url.replace('/enter_bug.cgi', ''),
                }
    return render(request, 'cts_vts_failures.html',
                    {
                        "failures": failures,
                        "build_info": build_info,
                        'download_failures': download_failures
                    })



class BugCreationForm(forms.Form):
    build_name = forms.CharField(label='Build Name', widget=forms.TextInput(attrs={'size': 80}))
    build_no = forms.CharField(label='Build No.')
    product = forms.CharField(label='Product', widget=forms.TextInput(attrs={'readonly': True}))
    component = forms.CharField(label='Component', widget=forms.TextInput(attrs={'readonly': True}))
    version = forms.CharField(label='Version', widget=forms.TextInput(attrs={'readonly': True}) )
    os = forms.CharField(label='Os', widget=forms.TextInput(attrs={'readonly': True}))
    hardware = forms.CharField(label='Hardware', widget=forms.TextInput(attrs={'readonly': True}))
    severity = forms.CharField(label='Severity')
    summary = forms.CharField(label='Summary', widget=forms.TextInput(attrs={'size': 80}))
    description = forms.CharField(label='Description', widget=forms.Textarea(attrs={'cols': 80}))

@login_required
def file_bug(request):
    submit_result = False
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        build_no = request.POST.get("build_no")

        form = BugCreationForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            build_name = cd['build_name']

            bug = bugzilla.DotDict()
            bug.product = cd['product']
            bug.component = cd['component']
            bug.summary = cd['summary']
            bug.description = cd['description']
            bug.bug_severity = cd['severity']
            bug.op_sys = cd['os']
            bug.platform = cd['hardware']
            bug.version = cd['version']
            bug.keywords = 'LCR'

            build_bugzilla = get_all_build_configs()[build_name]['build_bugzilla']
            bugzilla_instance = get_all_build_configs()[build_name]['bugzilla_instance']
            bug_id = bugzilla_instance.post_bug(bug).id

            submit_result = True
            build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                      'bug_id': bug_id,
                      'bugzilla_show_bug_prefix': '%s/show_bug.cgi?id=' % build_bugzilla.new_bug_url.replace('/enter_bug.cgi', ''),
                     }
            return render(request, 'file_bug.html',
                          {
                            "submit_result": submit_result,
                            'build_info': build_info,
                            'form': 'form'
                          })

        else:
            # not possible here since all are selectable elements
            return render(request, 'file_bug.html',
                      {
                        "form": form,
                        'submit_result': False,
                      })
    else: # GET
        build_name = request.GET.get("build_name")
        build_no = request.GET.get("build_no")
        job_ids_str = request.GET.get("job_ids")
        module_name = request.GET.get("module_name")
        test_name = request.GET.get("test_name")

        job_ids_tmp = job_ids_str.split(',')
        job_ids = []
        for job_id in job_ids_tmp:
            if not job_id in job_ids:
                job_ids.append(job_id)

        lava = get_all_build_configs()[build_name]['lava_server']
        lava_server = lava.server
        build_bugzilla = get_all_build_configs()[build_name]['build_bugzilla']

        form_initial = {
                        "build_name": build_name,
                        "build_no": build_no,
                        'product': build_bugzilla.product,
                        'component': build_bugzilla.component,
                        'severity': build_bugzilla.bug_severity,
                        'os': build_bugzilla.op_sys,
                        'hardware': build_bugzilla.rep_platform,
                        }

        form_initial['version'] = get_bug_version_from_build_name(build_name=build_name)
        if test_name.find(module_name) >=0:
            job_name = JobCache.objects.get(job_id=job_ids[0], lava_nick=lava.nick).job_name
            bug_summary = '%s: %s %s' % (build_bugzilla.short_desc_prefix, job_name, test_name)
            description = '%s %s' % (job_name, test_name)
        else:
            bug_summary = '%s: %s %s' % (build_bugzilla.short_desc_prefix, module_name, test_name)
            description = '%s %s' % (module_name, test_name)


        def extract_abi_stacktrace(result_zip_path, module_name='', test_name=''):
            failures = {}
            class_method = test_name.split('#')
            with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
                try:
                    root = ET.fromstring(f_zip_fd.read(TEST_RESULT_XML_NAME))
                    for elem in root.findall('.//Module[@name="%s"]' %(module_name)):
                        abi = elem.attrib['abi']
                        stacktrace_node = root.find('.//TestCase[@name="%s"]/Test[@name="%s"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                        if stacktrace_node is None:
                            # Try for VtsHal test cases
                            if abi == 'arm64-v8a':
                                stacktrace_node = root.find('.//TestCase[@name="%s"]/Test[@name="%s_64bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                            elif abi == 'armeabi-v7a':
                                stacktrace_node = root.find('.//TestCase[@name="%s"]/Test[@name="%s_32bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                        if stacktrace_node is not None:
                            failures[abi] = stacktrace_node.text
                        else:
                            logger.warn('failure StackTrace Node not found for module_name=%s, test_name=%s, abi=%s in file:%s' % (module_name, test_name, abi, result_zip_path))

                except ET.ParseError as e:
                    logger.error('xml.etree.ElementTree.ParseError: %s' % e)
                    logger.info('Please Check %s manually' % result_zip_path)
            return failures

        abis = []
        stacktrace_msg = None
        failures = {}
        for job_id in job_ids:
            result_file_path = get_result_file_path(build_name=build_name, build_no=build_no, job_id=job_id)
            if os.path.exists(result_file_path):
                metadata = {
                            'job_id': job_id,
                            'result_url': get_attachment_url(job_id=job_id, lava_server=lava_server, build_name=build_name),
                            'build_no': build_no,
                            'build_name': build_name,
                            }
                failures.update(extract_abi_stacktrace(result_file_path, module_name=module_name, test_name=test_name))

        abis = sorted(failures.keys())
        stacktrace_msg = ''
        if len(abis) == 0:
            logger.error('Failed to get stacktrace information for %s %s form jobs: '% (module_name, test_name, str(job_ids)))
        elif (len(abis) == 2) and (failures.get(abis[0]) != failures.get(abis[1])):
            for abi in abis:
                stacktrace_msg = '%s\n\n%s:\n%s' % (stacktrace_msg, abi, failures.get(abi))
        else:
            stacktrace_msg = failures.get(abis[0])
            bug_summary = "%s failed only with %s" % (bug_summary, abis[0])

        description += '\n\nABIs:\n%s' % (' '.join(abis))
        description += '\n\nStackTrace: \n%s' % (stacktrace_msg.strip())
        description += '\n\nLava Job:'
        for job_id in job_ids:
            description += '\n%s/%s' % (lava.job_url_prefix, job_id)

        description += '\n\nResult File Url:'
        for job_id in job_ids:
            description += '\n%s' % get_attachment_url(job_id=job_id, lava_server=lava_server, build_name=build_name)

        description += '\n\nImages Url:\n%s/%s/%s' % (android_snapshot_url_base, build_name, build_no)

        form_initial['summary'] = bug_summary
        form_initial['description'] = description
        form = BugCreationForm(initial=form_initial)

        build_info = {
                      'build_name': build_name,
                      'build_no': build_no,
                     }
    return render(request, 'file_bug.html',
                    {
                        "form": form,
                        'build_info': build_info,
                    })

if __name__ == "__main__":
    build_name = "android-lcr-reference-hikey-o"
    build_no = '20'
#    job_template = get_possible_job_names(build_name=build_name)
#    print str(job_template)
#    (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, server, jobs=[])
#    for job_name, job_result in checklist_results.items():    for test_name, test_result in job_result.items():
#    print str(checklist_results)

    lava_server = get_all_build_configs()[build_name]['lava_server']

    jobs = get_jobs(build_name, build_no, lava_server, job_name_list=[])
    print str(jobs)