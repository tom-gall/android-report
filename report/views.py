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
import urllib2
import xmlrpclib
import yaml
import logging

logger = logging.getLogger(__name__)

from lava_tool.authtoken import AuthenticatingServerProxy, KeyringAuthBackend

# Create your views here.
from models import TestCase, JobCache, BaseResults, Bug, BuildSummary, LAVA, LAVAUser, BuildBugzilla, BuildConfig, Comment

basic_weekly = { # job_name: ['test_suite', ],
                        #"basic": [ "meminfo", 'meminfo-first', 'meminfo-second', "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "basic": [ 'meminfo-first', 'meminfo-second', "busybox", "ping", "linaro-android-kernel-tests", "tjbench"],
                        "weekly": [ 'media-codecs', 'piglit-gles2', 'piglit-gles3', 'piglit-glslparser', 'piglit-shader-runner', 'stringbench', 'libc-bench'],
                     }

optee = { # job_name: ['test_suite', ],
          "optee": [ "optee-xtest"],
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
                'gearses2eclair': {'gearses2eclair': ['gearses2eclair',]},
                'geekbench3': {'geekbench3': ['geekbench-multi-core-mean', 'geekbench-single-core-mean']},
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
cts_v7a = [ 'cts-focused1-v7a',
            'cts-focused2-v7a',
            'cts-media-v7a',
            'cts-media2-v7a',
            'cts-opengl-v7a',
            'cts-part1-v7a',
            'cts-part2-v7a',
            'cts-part3-v7a',
            'cts-part4-v7a',
            'cts-part5-v7a',
          ]

# test_suite is the same as job name
cts_v8a = [ 'cts-focused1-v8a',
            'cts-focused2-v8a',
            'cts-media-v8a',
            'cts-media2-v8a',
            'cts-opengl-v8a',
            'cts-part1-v8a',
            'cts-part2-v8a',
            'cts-part3-v8a',
            'cts-part4-v8a',
            'cts-part5-v8a',
          ]

android_snapshot_url_base = "https://snapshots.linaro.org/android"
ci_job_url_base = 'https://ci.linaro.org/job'
android_build_config_url_base = "https://android-git.linaro.org/android-build-configs.git/plain"
template_url_prefix = "https://git.linaro.org/qa/test-plans.git/plain/android/"

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
        build_config = {
                        'lava_server': LAVAS[build.lava.nick],
                        'img_ext': build.img_ext,
                        'template_dir': build.template_dir,
                        'base_build': {
                                        'build_name': build.base_build_name,
                                        'build_no': build.base_build_no,
                                       },
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


jobs_to_be_checked_array = [
    "basic", "boottime", "optee", "weekly", 'monkey',
    "antutu6", "andebenchpro2015", "benchmarkpi", "caffeinemark", "cf-bench", "gearses2eclair", "geekbench3", "glbenchmark25", "javawhetstone", "jbench", "linpack", "quadrantpro", "rl-sqlite", "scimark", "vellamo3",
    "cts-focused1-v7a", "cts-focused2-v7a", "cts-media2-v7a", "cts-media-v7a", "cts-opengl-v7a", "cts-part1-v7a", "cts-part2-v7a", "cts-part3-v7a", "cts-part4-v7a", "cts-part5-v7a",
    "cts-focused1-v8a", "cts-focused2-v8a", "cts-media2-v8a", "cts-media-v8a", "cts-opengl-v8a", "cts-part1-v8a", "cts-part2-v8a", "cts-part3-v8a", "cts-part4-v8a", "cts-part5-v8a",
    "vts-hal", "vts-kernel-kselftest", "vts-kernel-ltp", "vts-kernel-part1", "vts-library", "vts-performance",
    ]

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
                JobCache.objects.get(job_id=job_id, lava_nick=lava.nick)
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
    try:
        res = lava.server.results.get_testjob_results_yaml(job_id)
        for test in yaml.load(res):
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
            try:
                # not set again if already cached
                TestCase.objects.get(name=test.get("name"),
                                     suite=test.get("suite"),
                                     lava_nick=lava.nick,
                                     job_id=job_id)
            except TestCase.DoesNotExist:
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
        # for cases that no permission to check result submitted by others
        JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id).update(cached=True,
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
    pat = re.compile('path="%s" remote=".+" revision="(?P<commit_id>[\da-z]+)" ' % path)
    matches = pat.findall(html)
    if len(matches) > 0:
        return matches[0]
    else:
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
    build_name = forms.ChoiceField(label='Build Name')
    build_no = forms.ChoiceField(label='Build No.')
    lava_nick= forms.ChoiceField(label='LAVA Instance',
                                     choices=(
                                              ("lkft", "lkft"),
                                              ("production", "production"),
                                              ("staging", "staging"),
                                             ))
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


    (jobs_failed, total_tests_res) = get_test_results_for_build(build_name, build_no)

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

            bugs = Bug.objects.filter(build_name=build_name, plan_suite=test_suite, module_testcase=test_suite)
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

                bugs = Bug.objects.filter(build_name=build_name, plan_suite=test_suite, module_testcase=test_case)
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
                    BaseResults.objects.create(build_name=build_name, build_no=build_no, job_name=job_name, job_id=job_id, lava_nick=lava_nick,
                                               unit=unit, measurement=measurement,
                                               plan_suite=test_suite, module_testcase=test_case)


    #########################################################
    ########### result for vts ##############################
    #########################################################
    vts_res = []
    summary = {
                'pass': 0,
                'fail': 0,
                'total': 0,
               }
    for job_name in vts:
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            job_id = None
            number_pass = 0
            number_fail = 0
            number_total = 0
            failed_testcases = []
        else:
            job_id = job_res['result_job_id_status'][0]
            number_pass = len(TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_vts-test', result='pass'))
            failed_testcases = TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_vts-test', result='fail')
            number_fail = len(failed_testcases)
            number_total = number_pass + number_fail
            if job_id not in successful_job_ids:
                successful_job_ids.append(job_id)

        if number_total == 0:
            number_passrate = 0.00
        else:
            number_passrate = float(number_pass * 100 / number_total)

        try:
            base = BaseResults.objects.get(build_name=base_build_name, build_no=base_build_no, plan_suite=job_name, module_testcase=job_name)
        except BaseResults.DoesNotExist:
            base = None

        bugs = Bug.objects.filter(build_name=build_name, plan_suite=job_name, module_testcase=job_name)
        comments = Comment.objects.filter(build_name=build_name, plan_suite=job_name, module_testcase=job_name)

        vts_res.append({'job_name': job_name,
                        'job_id': job_id,
                        'number_pass': number_pass,
                        'number_fail': number_fail,
                        'number_total': number_total,
                        'number_passrate': number_passrate,
                        'failed_testcases': failed_testcases,
                        'base': base,
                        'bugs': bugs,
                        'comments': comments,
                       })
        if cache_to_base and job_id is not None:
            BaseResults.objects.create(build_name=build_name, build_no=build_no, job_name=job_name, job_id=job_id, lava_nick=lava_nick,
                                       number_pass=number_pass, number_fail=number_fail, number_total=number_total, number_passrate=number_passrate,
                                       plan_suite=job_name, module_testcase=job_name)

        summary['pass'] = summary['pass'] + number_pass
        summary['fail'] = summary['fail'] + number_fail
        summary['total'] = summary['total'] + number_total

    pass_rate = 0
    if summary['total'] != 0:
        pass_rate = float(summary['pass'] * 100 / summary['total'])
    vts_res.append({'job_name': "Summary",
                    'job_id': '--',
                    'number_pass': summary['pass'],
                    'number_fail': summary['fail'],
                    'number_total': summary['total'],
                    'number_passrate': pass_rate,
                    'failed_testcases': [],
                   })
    #########################################################
    ########### result for cts ##############################
    #########################################################
    cts = cts_v7a + []
    if build_name.find("hikey") >= 0:
        cts = cts_v7a + cts_v8a
    cts_res = []
    summary = {
                'pass': 0,
                'fail': 0,
                'total': 0,
               }
    for job_name in sorted(cts):
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            cts_res.append({'job_name': job_name,
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
            modules_res = TestCase.objects.filter(job_id=job_id, lava_nick=lava_nick, suite__endswith='_%s' % job_name)
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

                bugs = Bug.objects.filter(build_name=build_name, plan_suite=job_name, module_testcase=module_name)
                comments = Comment.objects.filter(build_name=build_name, plan_suite=job_name, module_testcase=module_name)
                cts_res.append({'job_name': job_name,
                                'job_id': job_id,
                                'module_name': module_name,
                                'number_pass': number_pass,
                                'number_fail': number_fail,
                                'number_total': number_total,
                                'number_passrate': number_passrate,
                                'module_done': module_done,
                                'base': base,
                                'bugs': bugs,
                                'comments': comments,
                               })
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
    cts_res.append({'job_name': "Summary",
                    'job_id': None,
                    'module_name': 'Total',
                    'number_pass': summary['pass'],
                    'number_fail': summary['fail'],
                    'number_total': summary['total'],
                    'number_passrate': pass_rate,
                   })
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
    build_bugs = Bug.objects.filter(build_name=build_name)
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
        if build_name.find('x15') >= 0:
            kernel_commit = get_commit_from_pinned_manifest(pinned_manifest_url, 'kernel/ti/x15')
            kernel_url = 'http://git.ti.com/android/kernel/commit/%s' % kernel_commit
            kernel_version = '4.4.91'
        else:
            kernel_url = '--'
            kernel_version = '4.9.60'

        build_config_url = "%s/%s" % (android_build_config_url_base, build_name.replace("android-", "").replace('-premerge-ci', ''))
        build_android_tag = get_build_config_value(build_config_url, key="MANIFEST_BRANCH")
        toolchain_info = '--'
        firmware_version = '--'
        firmware_url = '--'

    ## bugzilla related information
    build_bugzilla = BuildBugzilla.objects.get(build_name=build_name.replace('-premerge-ci', ''))
    build_new_bug_url_prefix = '%s?product=%s&op_sys=%s&bug_severity=%s&component=%s&keywords=%s&rep_platform=%s&short_desc=%s: ' % ( build_bugzilla.new_bug_url,
                                                                                                                                      build_bugzilla.product,
                                                                                                                                      build_bugzilla.op_sys,
                                                                                                                                      build_bugzilla.bug_severity,
                                                                                                                                      build_bugzilla.component,
                                                                                                                                      build_bugzilla.keywords,
                                                                                                                                      build_bugzilla.rep_platform,
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
                    'firmware_url': firmware_url,
                    'firmware_version': firmware_version,
                    'toolchain_info': toolchain_info,
                    'images_url': images_url,
                    'cached_in_base': cached_in_base,
                 }

    return render(request, 'test_report.html',
                  {
                   'lava_server_job_prefix': get_all_build_configs()[build_name]['lava_server'].job_url_prefix,
                   'build_info': build_info,
                   'basic_optee_weekly_res': basic_optee_weekly_res,
                   'benchmarks_res': benchmarks_res,
                   'vts_res': vts_res,
                   'cts_res': cts_res,
                   'build_bugs': build_bugs,
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
