# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django import forms
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required, permission_required

import collections
import datetime
import json
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

# Create your views here.
from models import TestCase, JobCache, BaseResults, Bug, BuildSummary, LAVA, LAVAUser, BuildBugzilla, BuildConfig, Comment

from lcr import qa_report

from lcr.settings import BASE_DIR, FILES_DIR, BUGZILLA_API_KEY, QA_REPORT, QA_REPORT_DEFAULT

from lcr_config import DEFAULT_LCR_BUILD_NAME, DEFAULT_LAVA_USER, TEST_RESULT_XML_NAME
from lcr_config import job_priority_list, job_status_string_int, job_status_dict
from lcr_config import android_snapshot_url_base, ci_job_url_base, android_build_config_url_base, template_url_prefix
from lcr_config import benchmarks_common, vts, less_is_better_measurement, pat_ignore, names_ignore
from lcr_config import get_basic_optee_weekly_tests, get_cts_tests, get_kernel_makefile_url, get_kernel_src_path, get_platform_name

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))

class LavaInstance(object):
    def __init__(self, nick=None, user=None):
        self.nick = nick
        self.lava = LAVA.objects.get(nick=self.nick)
        self.domain = self.lava.domain
        self.lava_user = LAVAUser.objects.get(lava=self.lava, user_name=user)
        self.url = "https://%s:%s@%s/RPC2/" % (self.lava_user.user_name, self.lava_user.token, self.domain)
        self.job_url_prefix = "https://%s/scheduler/job" % self.domain
        self.server = xmlrpclib.ServerProxy(self.url)
        self.lava_api = qa_report.LAVAApi(self.domain, self.lava_user.token)

    def __str__(self):
        return self.url

LAVAS = {}
def initialize_all_lavas():
    global LAVAS
    if len(LAVAS) > 0:
        return LAVAS
    for lava in LAVA.objects.all():
        LAVAS[lava.nick] = LavaInstance(nick=lava.nick, user=DEFAULT_LAVA_USER)

def find_lava_config(job_url):
    for nick, config in LAVAS.items():
        if job_url.find('://%s/' % config.domain) >= 0:
            return config

    logger.warn('No lava instance found for the job_url=%s' % job_url)
    return None


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


def get_qa_project_name_with_lcr_build_name(build_name):
    return 'lcr/%s' % build_name.replace('android-', '')


def get_possible_builds(build_name=DEFAULT_LCR_BUILD_NAME):
    all_builds_no = []
    for build in qa_report_api.get_builds_with_project_name(get_qa_project_name_with_lcr_build_name(build_name)):
        all_builds_no.append(build.get('version'))

    all_builds_no.reverse()
    return all_builds_no


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


def get_possible_templates(build_name=DEFAULT_LCR_BUILD_NAME):
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

def get_possible_job_names(build_name=DEFAULT_LCR_BUILD_NAME):
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

    except xmlrpclib.ProtocolError as e:
        logger.info("Got error in cache_job_result_to_db for job_id=%s, lava_nick=%s: %s" % (job_id, lava.nick, str(e)))
        # for cases that no permission to check result submitted by others
    except xmlrpclib.Fault as e:
        raise e
    except:
        raise


@login_required
def resubmit_job(request):
    qa_job_ids = request.POST.getlist("qa_job_ids")
    if len(qa_job_ids) == 0:
        qa_job_id = request.GET.get("qa_job_id", "")
        if qa_job_id:
            qa_job_ids = [qa_job_id]

    if len(qa_job_ids) == 0:
        return render(request, 'job-resubmit.html',
                      {
                        'errors': True,
                      })

    qa_job = qa_report_api.get_job_with_id(qa_job_ids[0])
    build_url = qa_job.get('target_build')
    build_id = build_url.strip('/').split('/')[-1]

    jobs = qa_report_api.get_jobs_for_build(build_id)
    parent_job_urls = []
    for job in jobs:
        parent_job_url = job.get('parent_job')
        if parent_job_url:
            parent_job_urls.append(parent_job_url.strip('/'))

    succeed_qa_job_urls = []
    failed_qa_jobs = {}
    old_job_urls = []
    for qa_job_id in qa_job_ids:
        qa_job_url = qa_report_api.get_job_api_url(qa_job_id).strip('/')
        old_job_urls.append(qa_job_url)

        if qa_job_url in parent_job_urls:
            continue

        res = qa_report_api.forceresubmit(qa_job_id)
        if res.ok:
            succeed_qa_job_urls.append(qa_job_url)
        else:
            failed_qa_jobs[qa_job_url] = res

    # assuming all the jobs are belong to the same build

    jobs = qa_report_api.get_jobs_for_build(build_id)
    old_jobs = {}
    created_jobs = {}
    for job in jobs:
        qa_job_url = job.get('url').strip('/')
        if qa_job_url in old_job_urls:
            old_jobs[qa_job_url] = job

        parent_job_url = job.get('parent_job')
        if parent_job_url and parent_job_url.strip('/') in succeed_qa_job_urls:
            created_jobs[parent_job_url.strip('/')] = job


    results = []
    for qa_job_id in qa_job_ids:
        qa_job_url = qa_report_api.get_job_api_url(qa_job_id).strip('/')
        old = old_jobs.get(qa_job_url)
        if not old:
            results.append({
                'qa_job_url': qa_job_url,
                'old': None,
                'new': None,
                'error_msg': 'The job does not exists on qa-report'
            })
            continue

        if qa_job_url in parent_job_urls:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': None,
                'error_msg': 'The job is a parent job, could not be resubmitted again'
            })
            continue

        new = created_jobs.get(qa_job_url)
        if new:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': None
                })
            continue

        response = failed_qa_jobs.get(qa_job_url)
        if response is not None:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': 'Reason: %s<br/>Status Code: %s<br/>Url: %s' % (response.reason, response.status_code, response.url)
            })
        else:
            results.append({
                'qa_job_url': qa_job_url,
                'old': old,
                'new': new,
                'error_msg': 'Unknown Error happend, No job has the original job as parent, and no response found'
            })

    return render(request, 'job-resubmit.html',
                  {
                   'results': results,
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
    job_caches = list(JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id))
    if len(job_caches) != 1:
        return False
    else:
        return job_caches[0].cached


def get_test_results_for_build(build_name, build_no, job_name_list=[]):
    jobs_failed = []
    total_tests_res = {}

    jobs_raw = qa_report_api.get_jobs_with_project_name_build_version(get_qa_project_name_with_lcr_build_name(build_name), build_no)

    resubmitted_jobs_url = [ job.get('parent_job') for job in jobs_raw if job.get('parent_job') ]
    for job in jobs_raw:
        job_id = job.get("job_id")
        lava = find_lava_config(job.get('external_url'))
        job_status_str = job.get("job_status")
        if not job_status_str and job.get('submitted'):
            job_status_str = 'Submitted'
        job["job_status"] = job_status_str

        local_job_name = job.get("name").replace("%s-%s-" % (build_name, build_no), "")
        job["name"] = local_job_name
        job["lava_nick"] = lava.nick

        if job.get('failure'):
            failure = job.get('failure')
            new_str = failure.replace('"', '\\"').replace('\'', '"')
            try:
                failure_dict = json.loads(new_str)
            except ValueError:
                failure_dict = {'error_msg': new_str}
            job['failure'] = failure_dict

        if job_status_str != job_status_dict[2]:
            jobs_failed.append(job)
            continue

        if job.get('url') in resubmitted_jobs_url:
            jobs_failed.append(job)
            continue

        job_status_int = job_status_string_int[job_status_str]
        job_cached = is_job_cached(job_id, lava)
        if not job_cached:
            cache_job_result_to_db(job_id, lava, job_status_int)

        tests_res = get_yaml_result(job_id=job_id, lava=lava)
        if len(tests_res) == 0:
            jobs_failed.append(job)
            continue

        total_tests_res[local_job_name] = {
                                     "job_name": local_job_name,
                                     "build_no": build_no,
                                     'job_id': job_id,
                                     'lava_nick': lava.nick,
                                     'build_name': build_name,
                                     "results": tests_res}

        if not job_cached:
            job_lava_info = lava.lava_api.get_job(job_id=job_id)
            job_start_time = datetime.datetime.strptime(str(job_lava_info['start_time']), '%Y-%m-%dT%H:%M:%S.%fZ')
            job_end_time =  datetime.datetime.strptime(str(job_lava_info['end_time']), '%Y-%m-%dT%H:%M:%S.%fZ')
            job_duration = job_end_time - job_start_time
            jobcache_query = JobCache.objects.filter(lava_nick=lava.nick, job_id=job_id)
            job_cache_count = jobcache_query.count()
            if job_cache_count == 0:
                JobCache.objects.create(build_name=build_name, build_no=build_no,
                                    lava_nick=lava.nick, job_id=job_id, job_name=local_job_name, status=job_status_int,
                                    duration=job_duration, cached=True)
            elif job_cache_count == 1:
                jobcache_query.update(build_name=build_name, build_no=build_no,
                                    lava_nick=lava.nick, job_id=job_id, job_name=local_job_name, status=job_status_int,
                                   duration=job_duration, cached=True)
            else:
                jobcache_query.delete()
                JobCache.objects.create(build_name=build_name, build_no=build_no,
                                    lava_nick=lava.nick, job_id=job_id, job_name=local_job_name, status=job_status_int,
                                    duration=job_duration, cached=True)

    return (jobs_failed, total_tests_res, resubmitted_jobs_url)

def get_build_config_value(build_config_url, key="MANIFEST_BRANCH"):
    response = urllib2.urlopen(build_config_url)
    html = response.read()

    pat = re.compile('%s=(?P<value>.+)' % key)
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
    build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)

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
                    "build_numbers": all_build_numbers,
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
        build_name = request.POST.get("build_name", DEFAULT_LCR_BUILD_NAME)
        all_build_numbers = get_possible_builds(build_name)
        build_no_1 = request.POST.get("build_no_1", "0")
        build_no_2 = request.POST.get("build_no_2", "0")
        (failed_jobs_1, tests_result_1) = get_test_results_for_build(build_name, build_no_1)
        (failed_jobs_2, tests_result_2) = get_test_results_for_build(build_name, build_no_2)
        compare_results = compare_results_func(tests_result_1, tests_result_2)
    else:
        build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
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
        build_name = request.POST.get("build_name", DEFAULT_LCR_BUILD_NAME)
        job_name = request.POST.get("job_name", "basic")
        (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, lava, jobs=[job_name])
        #(all_build_numbers, checklist_results) = get_test_results_for_job(build_name, lava_server, jobs=[])
    else:
        build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
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
        build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
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
    build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
    generate_pdf = request.GET.get("generate_pdf", None)

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
    (jobs_failed, total_tests_res, resubmitted_job_urls) = get_test_results_for_build(build_name, build_no)


    jobs_failed_not_resubmitted = []
    resubmitted_jobs = []

    for job in jobs_failed:
        job_name = job.get('name')

        bugs = []
        for bug in bugs_total:
            if bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX':
                continue
            if bug.summary.find(' %s ' % job_name) >= 0:
                bugs.append(bug)
        job['bugs'] = bugs

        job['qa_job_id'] = job.get('url').rstrip('/').split('/')[-1]

        if job.get('failure'):
            job['error_msg'] = job.get('failure').get('error_msg')
        if not job.get('url') in resubmitted_job_urls:
            jobs_failed_not_resubmitted.append(job)
        else:
            resubmitted_jobs.append(job)

    lava_nick = get_all_build_configs()[build_name]['lava_server'].nick
    successful_job_ids = []
    #######################################################
    ## Get result for basic/optee/weekly tests
    #######################################################
    basic_optee_weekly = get_basic_optee_weekly_tests(build_name)
    basic_optee_weekly_res = []
    for job_name in sorted(basic_optee_weekly.keys()):
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            job_id = None
            lava_nick = '-'
        else:
            job_id = job_res['job_id']
            lava_nick = job_res.get('lava_nick')
            job_id_lava_nick = '%s@%s' % (job_id, lava_nick)
            if job_id_lava_nick not in successful_job_ids:
                successful_job_ids.append(job_id_lava_nick)
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
                                           'lava_nick': lava_nick,
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

    benchmarks_res = []
    for job_name in sorted(benchmarks.keys()):
        job_res = total_tests_res.get(job_name)
        if job_res is None:
            job_id = None
            lava_nick = '-'
        else:
            job_id = job_res['job_id']
            lava_nick = job_res.get('lava_nick')
            job_id_lava_nick = '%s@%s' % (job_id, lava_nick)
            if job_id_lava_nick not in successful_job_ids:
                successful_job_ids.append(job_id_lava_nick)

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
                                       'lava_nick': lava_nick,
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
        ## needs all the cts/vts jobs run on the same lava instance
        ## used for cts/vts failures display
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
                                'lava_nick': '',
                                'module_name': '--',
                                'number_pass': 0,
                                'number_fail': 0,
                                'number_total': 0,
                                'number_passrate': 0,
                               })
            else:
                job_id = job_res['job_id']
                lava_nick = job_res.get('lava_nick')
                job_id_lava_nick = '%s@%s' % (job_id, lava_nick)
                if job_id_lava_nick not in successful_job_ids:
                    successful_job_ids.append(job_id_lava_nick)

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
                                    'lava_nick': lava_nick,
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
                        'lava_nick': '-',
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
    cts = get_cts_tests(build_name)
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
    for job_id_lava_nick in successful_job_ids:
        try:
            fields = job_id_lava_nick.split('@')
            job_id = fields[0]
            lava_nick = fields[1]
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
        vts_pkg_url = build_summary.vts_pkg_url
        cts_pkg_url = build_summary.cts_pkg_url

    except BuildSummary.DoesNotExist:
        images_url = '%s/%s/%s' % (android_snapshot_url_base, build_name, build_no)
        pinned_manifest_url = '%s/pinned-manifest.xml' % images_url
        kernel_src_path = get_kernel_src_path(build_name)
        makefile_url = get_kernel_makefile_url(build_name)
        if kernel_src_path and makefile_url:
            kernel_commit = get_commit_from_pinned_manifest(pinned_manifest_url, kernel_src_path)
            kernel_url = makefile_url % kernel_commit
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
        vts_pkg_url = get_build_config_value(build_config_url, key="VTS_PKG_URL")
        cts_pkg_url = get_build_config_value(build_config_url, key="CTS_PKG_URL")

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
                    'vts_pkg_url': vts_pkg_url,
                    'cts_pkg_url': cts_pkg_url,
                 }

    no_resolved_bugs = []
    for bug in bugs_total:
        if bug.status == 'RESOLVED':
            continue
        no_resolved_bugs.append(bug)

    if not generate_pdf or generate_pdf != 'true':
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
                   'jobs_failed': jobs_failed_not_resubmitted,
                   'jobs_resubmitted': resubmitted_jobs,
                   'jobs_duration': jobs_duration,
                   'total_duration': total_duration,
                  }
        )
    else:
        # Create the HttpResponse object with the appropriate PDF headers.
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="Test-Report-%s-%s.pdf"' % (build_name, build_no)

        def reportlab_pdf(response):
            from io import BytesIO
            from reportlab.pdfgen import canvas

            import time
            from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, ListFlowable, PageBreak
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle, ListStyle
            from reportlab.lib import colors
            from reportlab.lib.units import cm, mm

            def get_link_text(url=None, text=""):
                if not url or url == '--':
                    return text
                else:
                    return '<link href="%s" underline="true" textColor="navy">%s</link>' % (url, text)

            Story = []

            styles = getSampleStyleSheet()
            styleHeader = styles["Normal"].clone(ParagraphStyle)
            styleHeader.alignment = TA_CENTER
            styleHeader.textColor = 'white'
            styleHeader.backColor = 'black'

            styleHeaderVertical = styleHeader.clone(ParagraphStyle)
            styleHeaderVertical.alignment = TA_LEFT


            styleContent = styles["Normal"].clone(ParagraphStyle)
            styleContent.fontSize = 8

            styleContentRightAlign = styleContent.clone(ParagraphStyle)
            styleContentRightAlign.alignment = TA_RIGHT

            stylelist = styles["OrderedList"].clone(ListStyle)
            stylelist.bulletFontSize = 8

            styleTitle = styles["Title"]

            styleHeading1 = styles["Heading1"]
            styleHeading1.backColor = 'darkgrey'

            styleBlockQuote = styles["Normal"].clone(ParagraphStyle)
            styleBlockQuote.leftIndent = 20
            styleBlockQuote.allowWidows = 1
            styleBlockQuote.backColor = '#FFFFE0'

            #######################################################################
            ##  Create the Title Page
            #######################################################################
            date_today = datetime.datetime.now()

            STATICS_DIR = os.path.join(BASE_DIR, "static")
            IMAGES_DIR = os.path.join(STATICS_DIR, "images")
            LOGO_PATH = os.path.join(IMAGES_DIR, "Linaro-Logo_standard.png")

            logo = Image(LOGO_PATH, width=9*cm, height=4.5*cm, hAlign='RIGHT')
            Story.append(logo)
            Story.append(Spacer(1, 24))

            Story.append(Paragraph('<b>%s Reference LCR for %s</b>' % (date_today.strftime('%y.%m'),
                                                                                        get_platform_name(build_info.get('build_name'))), styleTitle))
            Story.append(Paragraph('<b>Test Report</b>', styleTitle))
            Story.append(Spacer(1, 240))

            lines = []
            lines.append(('Date', date_today.strftime('%Y.%m.%d')))
            lines.append(('Author', 'Yongqin Liu <yongqin.liu@linaro.org>, Linaro Consumer Group'))
            lines.append(('Approvers', 'Tom Gall <tom.gall@linaro.org>, Linaro Consumer Group'))

            ci_link = "%s/%s/%s" % (ci_job_url_base, build_info.get('build_name'), build_info.get('build_no'))
            lines.append(('Build', Paragraph(get_link_text(url=ci_link, text=ci_link), styleContent)))
            lines.append(('Release', Paragraph(get_link_text(url=build_info.get('images_url'), text=build_info.get('images_url')), styleContent)))
            table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"), # outter border
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"), # inner grid
                ])

            table = Table(lines, colWidths=[60,300], style=table_style, hAlign='CENTER', vAlign='BOTTOM')
            Story.append(table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the Build Summary table
            #######################################################################
            Story.append(Paragraph('<b>Build Summary</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (0, -1), 'black'),  # background for the header
                ])

            lines = []
            lines.append((Paragraph('<b>Build Name</b>', styleHeaderVertical), Paragraph(build_info.get('build_name'), styleContent)))
            lines.append((Paragraph('<b>Build Number</b>', styleHeaderVertical), Paragraph(build_info.get('build_no'), styleContent)))
            lines.append((Paragraph('<b>Build Config</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('build_config_url'), text=build_info.get('build_config_name')), styleContent)))
            lines.append((Paragraph('<b>Android Version</b>', styleHeaderVertical), Paragraph(build_info.get('android_version'), styleContent)))
            lines.append((Paragraph('<b>Kernel Version</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('kernel_url'), text=build_info.get('kernel_version')), styleContent)))
            lines.append((Paragraph('<b>Toolchain</b>', styleHeaderVertical), Paragraph(build_info.get('toolchain_info').replace(' and ', '<br/>'), styleContent)))
            lines.append((Paragraph('<b>Firmware Info</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('firmware_url'), text=build_info.get('firmware_version')), styleContent)))
            lines.append((Paragraph('<b>Images</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('images_url'), text=build_info.get('images_url')), styleContent)))
            lines.append((Paragraph('<b>CTS</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('cts_pkg_url'), text=build_info.get('cts_pkg_url')), styleContent)))
            lines.append((Paragraph('<b>VTS</b>', styleHeaderVertical),
                            Paragraph(get_link_text(url=build_info.get('vts_pkg_url'), text=build_info.get('vts_pkg_url')), styleContent)))

            table = Table(lines, colWidths=[100, 350], style=table_style, hAlign='LEFT')
            Story.append(table)
            Story.append(Spacer(1, 12))

            Story.append(Paragraph('<b>Glossary</b>', styleHeading1))
            lines = []
            lines.append(('CTS', 'Android Compatibility Test Suite'))
            lines.append(('VTS', 'Android Vendor Test Suite'))
            lines.append(('LAVA', 'Linaro Automated Validation Architecture'))
            table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"), # outter border
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"), #  inner border
                ])

            table = Table(lines, colWidths=[40,400], style=table_style, hAlign='LEFT')
            Story.append(table)
            Story.append(Spacer(1, 12))
            Story.append(Spacer(1, 12))

            Story.append(Paragraph('<b>Pass-rate encodings</b>', styleHeading1))
            lines = [('100%',), ('50% - 99%',), ('1 - 49%',), ('0%',)]
            table_style = TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), "#94bd5e"),
                                ("BACKGROUND", (0, 1), (-1, 1), "#ffd966"),
                                ("BACKGROUND", (0, 2), (-1, 2), "#f6b26b"),
                                ("BACKGROUND", (0, 3), (-1, 3), "#e06666"),
                                ])
            table = Table(lines, colWidths=[100], style=table_style, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the Failed Jobs table
            #######################################################################
            Story.append(Paragraph('<b>Failed Jobs Without Test Result</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header
                ])
            index = 0
            lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Job Name</b>', styleHeader),
                            Paragraph('<b>Job Status</b>', styleHeader),
                            Paragraph('<b>ErrorMsg</b>', styleHeader),
                            Paragraph('<b>Bugs</b>', styleHeader),
                        )]
            for test in jobs_failed_not_resubmitted:
                index = index + 1
                job_id = test.get('job_id')
                job_name = test.get('name')
                if not job_id:
                    job_paragraph = Paragraph(str(job_name), styleContent)
                else:
                    job_paragraph = Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[test.get('lava_nick')].job_url_prefix, job_id, job_name), styleContent)

                bugs_paragraph_list = []
                if test.get('bugs'):
                    for bug in test.get('bugs'):
                        bug_id = bug.id
                        link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                        bugs_paragraph_list.append(Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent))

                bugs_paragraph = ListFlowable(bugs_paragraph_list, style=stylelist)
                lines.append((
                                    Paragraph(str(index), styleContent),
                                    job_paragraph,
                                    Paragraph(str(test.get('job_status')), styleContent),
                                    Paragraph(str(test.get('error_msg')), styleContent),
                                    bugs_paragraph,
                                ))

            table = Table(lines, colWidths=[30, 90, 90, 200, 50], style=table_style, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the Basic-OPTEE-Weekly table
            #######################################################################
            Story.append(Paragraph('<b>Basic And Weekly</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            table_style_cmds = [
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (3, 1), (6, -1), 'RIGHT'),  # alignment for the pass/fail/total column
                ]
            index = 0
            lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Job Name</b>', styleHeader),
                            Paragraph('<b>Test Name</b>', styleHeader),
                            Paragraph('<b>Pass</b>', styleHeader),
                            Paragraph('<b>Fail</b>', styleHeader),
                            Paragraph('<b>Total</b>', styleHeader),
                            Paragraph('<b>%</b>', styleHeader),
                            Paragraph('<b>Bugs</b>', styleHeader),
                        )]
            for test in basic_optee_weekly_res:
                index = index + 1
                job_id = test.get('job_id')
                job_name = test.get('job_name')
                if not job_id:
                    job_paragraph = Paragraph(str(job_name), styleContent)
                else:
                    job_paragraph = Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[test.get('lava_nick')].job_url_prefix, job_id, job_name), styleContent)

                bugs_paragraph_list = []
                if test.get('bugs'):
                    for bug in test.get('bugs'):
                        bug_id = bug.id
                        link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                        bugs_paragraph_list.append(Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent))

                bugs_paragraph = ListFlowable(bugs_paragraph_list, style=stylelist)
                lines.append((
                                    Paragraph(str(index), styleContent),
                                    job_paragraph,
                                    Paragraph(str(test.get('test_suite')), styleContent),
                                    Paragraph(str(test.get('number_pass')), styleContentRightAlign),
                                    Paragraph(str(test.get('number_fail')), styleContentRightAlign),
                                    Paragraph(str(test.get('number_total')), styleContentRightAlign),
                                    Paragraph(str(test.get('number_passrate')), styleContentRightAlign),
                                    bugs_paragraph,
                                ))
                number_passrate = test.get('number_passrate')
                if number_passrate == 100:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#94bd5e"))
                elif number_passrate >= 50:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#ffd966"))
                elif number_passrate > 0:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#f6b26b"))
                else:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#e06666"))

            table = Table(lines, colWidths=[30, 70, 150, 38, 35, 40, 38, 50], style=table_style_cmds, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())
            #######################################################################
            ##  Create the Benchmark table
            #######################################################################
            Story.append(Paragraph('<b>Benchmarks</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            table_style_cmds = [
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (5, 1), (5, -1), 'RIGHT'),  # alignment for the measurement column
                ]
            index = 0
            lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Benchmarks</b>', styleHeader),
                            Paragraph('<b>Test Suite</b>', styleHeader),
                            Paragraph('<b>Test Case</b>', styleHeader),
                            Paragraph('<b>Unit</b>', styleHeader),
                            Paragraph('<b>Value</b>', styleHeader),
                            Paragraph('<b>Bugs</b>', styleHeader)
                        )]
            for test in benchmarks_res:
                index = index + 1
                job_id = test.get('job_id')
                job_name = test.get('job_name')
                if not job_id:
                    job_paragraph = Paragraph(str(job_name), styleContent)
                else:
                    job_paragraph = Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[test.get('lava_nick')].job_url_prefix, job_id, job_name), styleContent)

                bugs_paragraph_list = []
                if test.get('bugs'):
                    for bug in test.get('bugs'):
                        bug_id = bug.id
                        link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                        bugs_paragraph_list.append(Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent))

                bugs_paragraph = ListFlowable(bugs_paragraph_list, style=stylelist)
                lines.append((
                                    Paragraph(str(index), styleContent),
                                    job_paragraph,
                                    Paragraph(str(test.get('test_suite')), styleContent),
                                    Paragraph(str(test.get('test_case')), styleContent),
                                    Paragraph(str(test.get('unit')), styleContent),
                                    Paragraph(str(test.get('measurement')), styleContentRightAlign),
                                    bugs_paragraph,
                                ))
                if test.get('measurement') == '--':
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#e06666"))

            table = Table(lines, colWidths=[30, 80, 100, 150, None, 60, 50], style=table_style_cmds, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())
            #######################################################################
            ##  Create the CTS table
            #######################################################################
            Story.append(Paragraph('<b>CTS</b>', styleHeading1))
            Story.append(Paragraph('To start complete CTS as a test plan run:', styleContent))
            Story.append(Paragraph('# ./android-cts/tools/cts-tradefed<br/>cts-tf > run cts --disable-reboot', style=styleBlockQuote))
            Story.append(Paragraph('To start CTS tests as individual package tests run:', styleContent))
            Story.append(Paragraph('# ./android-cts/tools/cts-tradefed<br/>cts-tf > run cts --module <MODULE_NAME> --disable-reboot', style=styleBlockQuote))
            Story.append(Paragraph('To run CTS test package as a plan:', styleContent))
            Story.append(Paragraph('# ./android-cts/tools/cts-tradefed<br/>cts-tf > run <PLAN_NAME> --disable-reboot', style=styleBlockQuote))

            Story.append(Spacer(1, 12))
            table_style_cmds = [
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (3, 1), (5, -1), 'RIGHT'),  # alignment for the pass/fail/total column
                    ('ALIGN', (7, 1), (7, -1), 'RIGHT'),  # alignment for the pass rate column
                ]
            index = 0
            lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Plan</b>', styleHeader),
                            Paragraph('<b>Module</b>', styleHeader),
                            Paragraph('<b>Pass</b>', styleHeader),
                            Paragraph('<b>Fail</b>', styleHeader),
                            Paragraph('<b>Total</b>', styleHeader),
                            Paragraph('<b>Done</b>', styleHeader),
                            Paragraph('<b>%</b>', styleHeader),
                            Paragraph('<b>Bugs</b>', styleHeader),
                        )]
            for cts in cts_res:
                index = index + 1
                job_id = cts.get('job_id')
                job_name = cts.get('job_name')
                if not job_id:
                    job_paragraph = Paragraph(str(job_name), styleContent)
                else:
                    job_paragraph = Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[cts.get('lava_nick')].job_url_prefix, job_id, job_name), styleContent)

                bugs_paragraph_list = []
                if cts.get('bugs'):
                    for bug in cts.get('bugs'):
                        bug_id = bug.id
                        link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                        bugs_paragraph_list.append(Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent))

                bugs_paragraph = ListFlowable(bugs_paragraph_list, style=stylelist)
                lines.append((
                                    Paragraph(str(index), styleContent),
                                    job_paragraph,
                                    Paragraph(str(cts.get('module_name')), styleContent),
                                    Paragraph(str(cts.get('number_pass')), styleContentRightAlign),
                                    Paragraph(str(cts.get('number_fail')), styleContentRightAlign),
                                    Paragraph(str(cts.get('number_total')), styleContentRightAlign),
                                    Paragraph(str(cts.get('module_done')), styleContent),
                                    Paragraph(str(cts.get('number_passrate')), styleContentRightAlign),
                                    bugs_paragraph,
                                ))
                number_passrate = cts.get('number_passrate')
                if number_passrate == 100:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#94bd5e"))
                elif number_passrate >= 50:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#ffd966"))
                elif number_passrate > 0:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#f6b26b"))
                else:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#e06666"))

            table = Table(lines, colWidths=[30, 100, 170, 38, 30, 40, 40, 35, 50], style=table_style_cmds, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the VTS table
            #######################################################################
            Story.append(Paragraph('<b>VTS</b>', styleHeading1))
            Story.append(Spacer(1, 12))

            Story.append(Paragraph('To start complete VTS as a test plan run:', styleContent))
            Story.append(Paragraph('# ./android-vts/tools/vts-tradefed<br/>vts-tf > run vts --disable-reboot', style=styleBlockQuote))
            Story.append(Paragraph('To start VTS tests as individual package tests run:', styleContent))
            Story.append(Paragraph('# ./android-vts/tools/vts-tradefed<br/>vts-tf > run <vts or othe Plan Name> --module <MODULE_NAME> --disable-reboot', style=styleBlockQuote))
            Story.append(Paragraph('To run VTS test package as a plan:', styleContent))
            Story.append(Paragraph('# ./android-vts/tools/vts-tradefed<br/>vts-tf > run <PLAN_NAME> --disable-reboot', style=styleBlockQuote))

            table_style_cmds = [
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (3, 1), (5, -1), 'RIGHT'),  # alignment for the pass/fail/total column
                    ('ALIGN', (7, 1), (7, -1), 'RIGHT'),  # alignment for the pass rate column
                ]
            index = 0
            lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Plan</b>', styleHeader),
                            Paragraph('<b>Module</b>', styleHeader),
                            Paragraph('<b>Pass</b>', styleHeader),
                            Paragraph('<b>Fail</b>', styleHeader),
                            Paragraph('<b>Total</b>', styleHeader),
                            Paragraph('<b>Done</b>', styleHeader),
                            Paragraph('<b>%</b>', styleHeader),
                            Paragraph('<b>Bugs</b>', styleHeader),
                        )]
            for vts in vts_res:
                index = index + 1
                job_id = vts.get('job_id')
                job_name = vts.get('job_name')
                if not job_id:
                    job_name_paragraph = Paragraph(str(job_name), styleContent)
                else:
                    job_name_paragraph = Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[vts.get('lava_nick')].job_url_prefix, job_id, job_name), styleContent)

                bugs_paragraph_list = []
                if vts.get('bugs'):
                    for bug in vts.get('bugs'):
                        bug_id = bug.id
                        link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                        bugs_paragraph_list.append(Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent))

                bugs_paragraph = ListFlowable(bugs_paragraph_list, style=stylelist)
                lines.append((
                                    Paragraph(str(index), styleContent),
                                    job_name_paragraph,
                                    Paragraph(str(vts.get('module_name')), styleContent),
                                    Paragraph(str(vts.get('number_pass')), styleContentRightAlign),
                                    Paragraph(str(vts.get('number_fail')), styleContentRightAlign),
                                    Paragraph(str(vts.get('number_total')), styleContentRightAlign),
                                    Paragraph(str(vts.get('module_done')), styleContent),
                                    Paragraph(str(vts.get('number_passrate')), styleContentRightAlign),
                                    bugs_paragraph,
                                ))
                number_passrate = vts.get('number_passrate')
                if number_passrate == 100:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#94bd5e"))
                elif number_passrate >= 50:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#ffd966"))
                elif number_passrate > 0:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#f6b26b"))
                else:
                    table_style_cmds.append(("BACKGROUND", (0, index), (-1, index), "#e06666"))

            table = Table(lines, colWidths=[30, 70, None, 38, 30, 40, 40, 35, 50], style=table_style_cmds, hAlign='LEFT')
            Story.append(table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the Bugs table
            #######################################################################
            Story.append(Paragraph('<b>Bug Status:</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            bug_table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (3, 1), (3, -1), 'RIGHT'),  # alignment for the last column of duration
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # 所有表格上下居中对齐
                ])
            index = 0
            bug_lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Bug ID</b>', styleHeader),
                            Paragraph('<b>Summary</b>', styleHeader),
                            Paragraph('<b>Status</b>', styleHeader),
                        )]
            for bug in no_resolved_bugs:
                index = index + 1
                bug_id = bug.id
                bug_summary = bug.summary
                bug_status = bug.status
                link = 'https://bugs.linaro.org/show_bug.cgi?id=%s' % (bug_id)
                bug_lines.append((
                                    Paragraph(str(index), styleContent),
                                    Paragraph('<link href="%s" underline="true" textColor="navy">%s</link>' % (link, bug_id), styleContent),
                                    Paragraph(bug_summary, styleContent),
                                    Paragraph(bug_status, styleContent),
                                ))

            bugs_table = Table(bug_lines, colWidths=[30, 40, 350, 80], style=bug_table_style, hAlign='LEFT')
            Story.append(bugs_table)
            Story.append(PageBreak())

            #######################################################################
            ##  Create the Job Duration table
            #######################################################################
            Story.append(Paragraph('<b>Jobs Duration:</b>', styleHeading1))
            Story.append(Spacer(1, 12))
            job_duration_table_style = TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.5, "black"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, "black"),

                    ('BACKGROUND', (0, 0), (-1, 0), 'black'),  # background for the header

                    ('ALIGN', (3, 1), (3, -1), 'RIGHT'),  # alignment for the last column of duration
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # 所有表格上下居中对齐
                ])

            index = 0
            job_lines = [(
                            Paragraph('<b>No.</b>', styleHeader),
                            Paragraph('<b>Job ID</b>', styleHeader),
                            Paragraph('<b>Job Name</b>', styleHeader),
                            Paragraph('<b>Duration</b>', styleHeader),
                        )]
            for job in jobs_duration:
                index = index + 1
                job_id = job.job_id
                job_name = job.job_name
                job_duration = job.duration
                job_lines.append((
                    Paragraph(str(index), styleContent),
                    Paragraph('<link href="%s/%s" underline="true" textColor="navy">%s</link>' % (LAVAS[job.lava_nick].job_url_prefix, job_id, job_id), styleContent),
                    Paragraph(job_name, styleContent),
                    Paragraph(str(job_duration), styleContentRightAlign),
                ))
            job_lines.append((
                    Paragraph(str(index + 1), styleContent),
                    Paragraph('-', styleContent),
                    Paragraph('-', styleContent),
                    Paragraph(str(total_duration), styleContentRightAlign),
                ))
            job_duration_table = Table(job_lines, colWidths=[30, 50, 147, None], style=job_duration_table_style, hAlign='LEFT')
            Story.append(job_duration_table)

            Story.append(PageBreak())
            Story.append(Paragraph('<b>Test End<br/>Thanks!</b>', styleTitle))

            # Create the PDF object, using the BytesIO object as its "file."
            class TestReportDocTemplate(SimpleDocTemplate):
                def afterFlowable(self, flowable):
                    "Registers TOC entries."
                    if flowable.__class__.__name__ == 'Paragraph':
                        text = flowable.getPlainText()
                        style = flowable.style.name
                        if style == 'Heading1':
                            self.notify('TOCEntry', (0, text, self.page))
                            key = text.replace(' ', '-')
                            self.canv.bookmarkPage(key)
                            self.canv.addOutlineEntry(text, key, 0, 0)


            def addPageNumber(canvas, doc):
                """
                Add the page number
                """
                page_num = canvas.getPageNumber()
                text = "Page #%s" % page_num
                canvas.drawRightString(200*mm, 20*mm, text)

            buffer = BytesIO()
            #doc = TestReportDocTemplate(buffer, rightMargin=20, leftMargin=20, topMargin=72, bottomMargin=18)
            doc = TestReportDocTemplate(buffer, rightMargin=20, leftMargin=20)
            doc.build(Story, onFirstPage=addPageNumber, onLaterPages=addPageNumber)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)

            #doc.build(Story)

        reportlab_pdf(response)
        return response


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
        build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
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
        build_name = request.GET.get("build_name", DEFAULT_LCR_BUILD_NAME)
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
        basic_optee_weekly = get_basic_optee_weekly_tests(build_name)

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
            basic_optee_weekly = get_basic_optee_weekly_tests(build_name)
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
    cts_vts = [] + get_cts_tests(build_name) + vts

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
            logger.error('Failed to get stacktrace information for %s %s form jobs: %s'% (module_name, test_name, str(job_ids)))
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
    build_no = '20'
#    job_template = get_possible_job_names(build_name=build_name)
#    print str(job_template)
#    (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, server, jobs=[])
#    for job_name, job_result in checklist_results.items():    for test_name, test_result in job_result.items():
#    print str(checklist_results)

#    lava_server = get_all_build_configs()[build_name]['lava_server']

#    jobs = get_jobs(build_name, build_no, lava_server, job_name_list=[])
#    print str(jobs)
