# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django import forms
from django.shortcuts import render
from django.http import HttpResponse

import re
import sys
import urllib2
import xmlrpclib
import yaml

from lava_tool.authtoken import AuthenticatingServerProxy, KeyringAuthBackend

# Create your views here.

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
                        "|regression_\d+"
                        "|arm64-v8a.+_executed"
                        "|arm64-v8a.+_failed"
                        "|armeabi-v7a.+_executed"
                        "|armeabi-v7a.+_failed"
                        ")$")

names_ignore = ["test-attachment",
                "test-skipped", "regression_4003_XTS", "regression_4003_NO_XTS", "subtests-fail-rate",
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
                  }


job_priority_list = ['high', 'medium', 'low']
user = "yongqin.liu"
token = {'staging': 'ty1dprzx7wysqrqmzuytccufwbyyl9xthwowgim0p0z5hm00t6mzwebyp4dgagmyg2f1kag9ln0s9dh212s3wdaxhasm0df7bqnumrwz1m5mbmf4xg780xgeo9x1348k',
         'production': 'n2ab47pbfbu4um0sw5r3zd22q1zdorj7nlnj3qaaaqwdfigahkn6j1kp0ze49jjir84cud7dq4kezhms0jrwy14k1m609e8q50kxmgn9je3zlum0yrlr0njxc87bpss9',
         'lkft': 'gdr5ww4npc7y7fby703hcz1b62bxrbpdt2ug1169wce02r2y2jiz96dy83n5xsm96uhnidxxotxj92uefy4degk3bwgiqgz1gq09h02yjipuon6wacfmkxnoocx4mdwg'
    }


lava_server_domain = {
                'staging': "staging.validation.linaro.org",
                'production': "validation.linaro.org",
                'lkft': "lkft.validation.linaro.org",
              }

lava_server_url = {
                'staging': "https://%s:%s@%s/RPC2/" % (user, token['staging'], lava_server_domain['staging']),
                'production': "https://%s:%s@%s/RPC2/" % (user, token['production'], lava_server_domain['production']),
                'lkft': "https://%s:%s@%s/RPC2/" % (user, token['lkft'], lava_server_domain['lkft']),
              }

lava_server_job_prefix = {
                'staging': "https://%s/scheduler/job" % lava_server_domain['staging'],
                'production': "https://%s/scheduler/job" % lava_server_domain['production'],
                'lkft': "https://%s/scheduler/job" % lava_server_domain['lkft'],
              }

lava_server_production = AuthenticatingServerProxy(lava_server_url['production'], auth_backend=KeyringAuthBackend())
lava_server_lkft = AuthenticatingServerProxy(lava_server_url['lkft'], auth_backend=KeyringAuthBackend())
lava_server_staging = AuthenticatingServerProxy(lava_server_url['staging'], auth_backend=KeyringAuthBackend())
server = lava_server_staging

build_configs = {
                  'android-lcr-reference-hikey-o': {
                                                    'lava_server': lava_server_staging,
                                                    'img_ext': ".img.xz",
                                                    'template_dir': "hikey-v2",
                                                   },
                  'android-lcr-reference-x15-o': {
                                                    'lava_server': lava_server_production,
                                                    'img_ext': ".img",
                                                    'template_dir': "x15",
                                                   },
                }

build_names = build_configs.keys()
build_names.sort()

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
    url = 'https://git.linaro.org/qa/test-plans.git/tree/android/%s' % build_configs[build_name]['template_dir']
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
        url = '%s/%s/%s' % (template_url_prefix, build_configs[build_name]['template_dir'], template)
        response = urllib2.urlopen(url)
        html = response.read()
        job_names = pat.findall(html)
        if len(job_names) == 0:
            job_names = pat_json.findall(html)

        job_name_template_name_hash[job_names[0]] = template

    sorted(job_name_template_name_hash.items())
    return job_name_template_name_hash


def get_jobs(build_name, build_no, lava_server, job_name_list=[]):
    jobs_to_be_checked = get_possible_job_names(build_name=build_name).keys()
    if job_name_list is None or len(job_name_list) == 0 or len(job_name_list) > 1:
        search_condition = "description__icontains__%s-%s" % (build_name, build_no)
    elif len(job_name_list) == 1:
        search_condition = "description__icontains__%s-%s-%s" % (build_name, build_no, job_name_list[0])
    jobs_from_lava = lava_server.results.make_custom_query("testjob", search_condition)
    jobs = { }
    for job in jobs_from_lava:
        job_id = job.get("id")
        job_description = job.get("description")
        job_status = job.get("status")
        if job_name_list is None or len(job_name_list) == 0 or len(job_name_list) > 1:
            local_job_name = job_description.replace("%s-%s-" % (build_name, build_no), "")

            if local_job_name not in jobs_to_be_checked:
                continue
            if len(job_name_list) > 1 and local_job_name not in job_name_list:
                continue
        else:
            local_job_name = job_name_list[0]

        job_exist = jobs.get(local_job_name)
        if job_exist is not None:
            job_exist.get("id_list").append(job_id)
            job_exist.get("status_list").append(job_status)
        else:
            jobs[local_job_name] = {
                                "id_list": [job_id],
                                "status_list": [job_status],
                             }

    return jobs

def get_job_name(job_dict):
    return  job_dict.get("name")

def jobs_dict_to_sorted_tuple(dict_jobs={}):
    jobs_tuple = []
    for job_name, job_details in dict_jobs.items():
        id_list = job_details.get("id_list")
        status_string_list = []
        for status in job_details.get("status_list"):
            status_string_list.append(job_status_dict[status])
        jobs_tuple.append({"name": job_name,
                           "id_list": id_list,
                           "status_list": job_details.get("status_list"),
                           "status_string_list": status_string_list,
                           "id_status_list": zip(id_list, status_string_list)})
    jobs_tuple.sort(key=get_job_name)
    return jobs_tuple


def get_yaml_result(job_id, lava_server):
    tests_res = {}
    try:
        res = lava_server.results.get_testjob_results_yaml(job_id)
        for test in yaml.load(res):
            if test.get("suite") == "lava":
                continue
            if pat_ignore.match(test.get("name")):
                continue

            if test.get("name") in names_ignore:
                continue
            if test.get("measurement") and test.get("measurement") == "None":
                test["measurement"] = None
            tests_res[test.get("name")] = { "name": test.get("name"),
                                            "result": test.get("result"),
                                            "measurement": test.get("measurement"),
                                            "unit": test.get("unit"),
                                            "job_id": job_id,
                                          }

        return tests_res

    except xmlrpclib.Fault as e:
        raise e
    except:
        raise

def resubmit_job(request):
    job_id = request.GET.get("job_id", "")
    build_name = request.GET.get("build_name", "")
    if not job_id:
        return render(request, 'job-resubmit.html',
                  {
                   'errors': True,
                  }
        )

    lava_server = build_configs[build_name]['lava_server']
    new_job_id = lava_server.scheduler.jobs.resubmit(job_id)
    return render(request, 'job-resubmit.html',
                  {
                   'job_id': new_job_id,
                   'lava_server_job_prefix': lava_server_job_prefix["staging"],
                  }
        )

def get_default_build_no(all_build_numbers=[], defaut_build_no=None):
    if len(all_build_numbers) > 0:
        return  all_build_numbers[-1]
    elif defaut_build_no:
        return defaut_build_no
    else:
        return 0


def get_test_results_for_build(build_name, build_no, job_name_list=[]):
    jobs_failed = []
    total_tests_res = {}
    lava_server = build_configs[build_name]['lava_server']

    jobs = jobs_dict_to_sorted_tuple(get_jobs(build_name, build_no, lava_server, job_name_list=job_name_list))
    for job in jobs:
        id_status_list = job.get("id_status_list")
        job_total_res = {}
        result_job_id_status = None
        for job_id, job_status in id_status_list:
            if job_status != job_status_dict[2]:
                continue
            tests_res = get_yaml_result(job_id, lava_server)
            if len(tests_res) != 0:
                # use the last to replace the first
                # might be better to change to use the better one
                # compare the 2 results
                job_total_res.update(tests_res)
                result_job_id_status = (job_id, job_status)

        if len(job_total_res) == 0:
            jobs_failed.append(job)
        else:
            total_tests_res[job.get("name")] = {
                                     "job_name": job.get("name"),
                                     "id_status_list": job.get("id_status_list"),
                                     "result_job_id_status": result_job_id_status,
                                     "build_no": build_no,
                                     "results": job_total_res}

    return (jobs_failed, total_tests_res)

def jobs(request):
    build_name = request.GET.get("build_name", DEFAULT_BUILD_NAME)

    all_build_numbers = get_possible_builds(build_name)
    build_no = request.GET.get("build_no", get_default_build_no(all_build_numbers))

    (jobs_failed, total_tests_res) = get_test_results_for_build(build_name, build_no)

    build_config_url = "%s/%s" % (android_build_config_url_base, build_name.replace("android-", ""))

    build_info = {
                    "build_name": build_name,
                    "build_no": build_no,
                    "ci_url_base": ci_job_url_base,
                    "snapshot_url_base": android_snapshot_url_base,
                    "android_tag": "android-8.0.0_r4",
                    "build_config_url": build_config_url,
                    "build_numbers": get_possible_builds(build_name),
                 }
    return render(request, 'jobs.html',
                  {
                   'jobs_failed': jobs_failed,
                   'jobs_result': sorted(total_tests_res.items()),
                   'lava_server_job_prefix': lava_server_job_prefix['staging'],
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
                   'lava_server_job_prefix': lava_server_job_prefix['staging'],
                   'form': form,
                   'compare_results': compare_results,
                  }
        )


def get_test_results_for_job(build_name, lava_server, jobs=[]):
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

def checklist(request):
    checklist_results = {}
    all_build_numbers= []
    #form = CompareForm(request)
    if request.method == 'POST':
        build_name = request.POST.get("build_name", DEFAULT_BUILD_NAME)
        job_name = request.POST.get("job_name", "basic")
        lava_server = build_configs[build_name]['lava_server']
        (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, lava_server, jobs=[job_name])
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
                   'lava_server_job_prefix': lava_server_job_prefix['staging'],
                   'form': form,
                   'checklist_results': checklist_results,
                   'all_build_numbers': all_build_numbers,
                  }
        )



class JobSubmissionForm(forms.Form):
    build_name = forms.ChoiceField(label='Build Name')
    build_no = forms.ChoiceField(label='Build No.')
    lava_instance= forms.ChoiceField(label='LAVA Instance',
                                     choices=(
                                              ("staging", "staging"),
                                              ("production", "production"),
                                              ("lkft", "lkft"),
                                             ))
    job_priority = forms.ChoiceField(label='Priority', choices=zip(job_priority_list, job_priority_list))
    jobs = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple)


def submit_lava_jobs(request):
    if request.method == 'POST':
        build_name = request.POST.get("build_name")
        job_template = get_possible_job_names(build_name=build_name)
        jobs = job_template.keys()
        jobs.sort()
        all_build_numbers = get_possible_builds(build_name)
        all_build_numbers.reverse()

        form = JobSubmissionForm(request.POST)
        form.fields["build_name"].choices = zip(build_names, build_names)
        form.fields["build_no"].choices = zip(all_build_numbers, all_build_numbers)
        form.fields["jobs"].choices = zip(jobs, jobs)
        if form.is_valid():
            cd = form.cleaned_data
            build_name = cd['build_name']
            build_no = cd['build_no']
            jobs = cd['jobs']
            job_priority = cd['job_priority']
            lava_instance = cd['lava_instance']
            lava_server = build_configs[build_name]['lava_server']

            submit_result = []
            for job_name in jobs:
                template = job_template[job_name]
                url = '%s/%s/%s' % (template_url_prefix, build_configs[build_name]['template_dir'], template)
                response = urllib2.urlopen(url)
                html = response.read()

                meta_url = "%s/%s/%s" % (ci_job_url_base, build_name, build_no)
                download_url = "%s/%s/%s" % (android_snapshot_url_base, build_name, build_no)
                img_ext = build_configs[build_name]['img_ext']
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
                    job_id = lava_server.scheduler.submit_job(job_definition)
                    submit_result.append({
                                           "job_name": job_name,
                                           "template": template,
                                           "template_url": url,
                                           "lava_server_job_prefix": lava_server_job_prefix[lava_instance],
                                           "job_id": job_id,
                                         })
                except xmlrpclib.Fault as e:
                    submit_result.append({
                                           "job_name": job_name,
                                           "template": template,
                                           "template_url": url,
                                           "lava_server_job_prefix": lava_server_job_prefix[lava_instance],
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
                        "job_priority": 'medium',
                       }
        form = JobSubmissionForm(initial=form_initial)
        form.fields["build_name"].choices = zip(build_names, build_names)
        form.fields["build_no"].choices = zip(all_build_numbers, all_build_numbers)
        form.fields["jobs"].choices = zip(jobs, jobs)

    return render(request, 'submit_jobs.html',
                      {
                        "form": form,
                      })

def index(request):
    builds = {}
    for build_name in build_names:
        builds[build_name] = {
                                "build_name": build_name,
                                "android_version": "android-8.0.0_r4",
                                "kernel_version": "4.9",
                                "ci_link": "%s/%s" % (ci_job_url_base, build_name),
                                "android_build_config_link": "%s/%s" % (android_build_config_url_base, build_name.replace("android-", "")),
                                "snapshot_url": '%s/%s/' % (android_snapshot_url_base, build_name),
                                "job_status": "--",
                             }

    builds.items().sort()
    return render(request, 'index.html',
                  {
                    "builds": builds,
                  })

if __name__ == "__main__":
    build_name = "android-lcr-reference-x15-o"
    job_template = get_possible_job_names(build_name=build_name)
    print str(job_template)
#    (all_build_numbers, checklist_results) = get_test_results_for_job(build_name, server, jobs=[])
#    for job_name, job_result in checklist_results.items():    for test_name, test_result in job_result.items():
#    print str(checklist_results)

