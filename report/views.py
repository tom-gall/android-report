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

LAVA_USER_TOKEN = ""
LAVA_USER = "yongqin.liu"
SERVER_URL="https://%s:%s@staging.validation.linaro.org/RPC2/" % (LAVA_USER, LAVA_USER_TOKEN)
server = AuthenticatingServerProxy(SERVER_URL, auth_backend=KeyringAuthBackend())
lava_server_job_prefix = "https://staging.validation.linaro.org/scheduler/job"

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
               ]

job_status_dict = {0: "Submitted",
                   1: "Running",
                   2: "Complete",
                   3: "Incomplete",
                   4: "Canceled",
                  }


def get_possible_builds(build_name="android-lcr-reference-hikey-o"):
    url = 'https://snapshots.linaro.org/android/%s/' % build_name
    response = urllib2.urlopen(url)
    html = response.read()

    pat = re.compile('<a href="/android/%s/(?P<build_no>\d+)/"' % build_name)
    all_builds = pat.findall(html)
    all_builds.reverse()
    return all_builds


jobs_checked = [
                    "andebenchpro2015",
                    "antutu6",
                    "basic",
                    "benchmarkpi",
                    "boottime",
                    "caffeinemark",
                    "cf-bench",
                    "cts-focused1-v7a",
                    "cts-focused1-v8a",
                    "cts-focused2-v7a",
                    "cts-focused2-v8a",
                    "cts-media2-v7a",
                    "cts-media2-v8a",
                    "cts-media-v7a",
                    "cts-media-v8a",
                    "cts-opengl-v7a",
                    "cts-opengl-v8a",
                    "cts-part1-v7a",
                    "cts-part1-v8a",
                    "cts-part2-v7a",
                    "cts-part2-v8a",
                    "cts-part3-v7a",
                    "cts-part3-v8a",
                    "cts-part4-v7a",
                    "cts-part4-v8a",
                    "cts-part5-v7a",
                    "cts-part5-v8a",
                    "gearses2eclair",
                    "geekbench3",
                    "glbenchmark25",
                    "javawhetstone",
                    "jbench",
                    "linpack",
                    "optee",
                    "quadrantpro",
                    "rl-sqlite",
                    "scimark",
                    "vellamo3",
                    "weekly",
               ]
def get_jobs(build_name, build_no, server):
    search_condition = "description__icontains__%s-%s" % (build_name, build_no)
    jobs_from_lava = server.results.make_custom_query("testjob", search_condition)
    jobs = { }
    for job in jobs_from_lava:
        job_id = job.get("id")
        job_description = job.get("description")
        job_status = job.get("status")
        job_name = job_description.replace("%s-%s-" % (build_name, build_no), "")

        if job_name not in jobs_checked:
            continue

        job_exist = jobs.get(job_name)
        if job_exist is not None:
            job_exist.get("id_list").append(job_id)
            job_exist.get("status_list").append(job_status)
        else:
            jobs[job_name] = {
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


def get_yaml_result(job_id, server):
    tests_res = {}
    # server = xmlrpclib.ServerProxy(SERVER_URL)
    try:
        #job_id = server.scheduler.submit_job(job_yaml_str)
        res = server.results.get_testjob_results_yaml(job_id)
        #res = server.results.get_testjob_results_csv(job_id)
        #print "results for job %s:" % str(job_id)
        #print "%s" % str(yaml.load(res))
        for test in yaml.load(res):
            if test.get("suite") == "lava":
                continue
            if pat_ignore.match(test.get("name")):
                continue

            if test.get("name") in names_ignore:
                continue
            if test.get("measurement") and test.get("measurement") == "None":
                test["measurement"] = None
            ## print "%s" % str(test)
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
    if not job_id:
        return render(request, 'job-resubmit.html',
                  {
                   'errors': True,
                  }
        )
    new_job_id = server.scheduler.jobs.resubmit(job_id)
    return render(request, 'job-resubmit.html',
                  {
                   'job_id': new_job_id,
                   'lava_server_job_prefix': lava_server_job_prefix,
                  }
        )

def get_default_build_no( all_build_numbers=[], defaut_build_no=None):
    if len(all_build_numbers) > 0:
        return  all_build_numbers[-1]
    elif defaut_build_no:
        return defaut_build_no
    else:
        return 0


def get_test_results_for_build(build_name, build_no, lava_server):
    jobs_failed = []
    total_tests_res = {}

    jobs = jobs_dict_to_sorted_tuple(get_jobs(build_name, build_no, lava_server))
    for job in jobs:
        id_status_list = job.get("id_status_list")
        job_total_res = {}
        result_job_id_status = None
        for job_id, job_status in id_status_list:
            if job_status != job_status_dict[2]:
                continue
            tests_res = get_yaml_result(job_id, server)
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
                                     "results": job_total_res}

    return (jobs_failed, total_tests_res)

def jobs(request):
    #build_name = "android-lcr-reference-hikey-o"
    build_name = request.GET.get("build_name", "android-lcr-reference-hikey-o")

    all_build_numbers = get_possible_builds(build_name)
    build_no = request.GET.get("build_no", get_default_build_no(all_build_numbers))

    (jobs_failed, total_tests_res) = get_test_results_for_build(build_name, build_no, server)

    build_config_url = "http://android-git.linaro.org/android-build-configs.git/tree/%s" % (build_name.replace("android-", ""))

    build_info = {
                    "build_name": build_name,
                    "build_no": build_no,
                    "ci_url_base": "https://ci.linaro.org/job",
                    "snapshot_url_base": "https://snapshots.linaro.org/android",
                    "android_tag": "android-8.0.0_r4",
                    "build_config_url": build_config_url,
                    "build_numbers": get_possible_builds(build_name),
                 }
    return render(request, 'jobs.html',
                  {
                   'jobs_failed': jobs_failed,
                   'jobs_result': sorted(total_tests_res.items()),
                   'lava_server_job_prefix': lava_server_job_prefix,
                   'build_info': build_info,
                  }
        )

class CompareForm(forms.Form):
    build_name = forms.CharField(widget=forms.HiddenInput())
    build_no_1 = forms.ChoiceField(label="",  choices=[])
    build_no_2 = forms.ChoiceField(label="",  choices=[])


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
    #form = CompareForm(request)
    if request.method == 'POST':
        build_name = request.POST.get("build_name", "android-lcr-reference-hikey-o")
        all_build_numbers = get_possible_builds(build_name)
        build_no_1 = request.POST.get("build_no_1", "0")
        build_no_2 = request.POST.get("build_no_2", "0")
        #if form.is_valid():
        #form.build_name = forms.CharField(widget=forms.HiddenInput()), initial=build_name)
        #form.build_no_1 = forms.ChoiceField(label="",  choices=[(build_no, build_no) for build_no in all_build_numbers], initial=build_no_1)
        #form.fields['build_no_1'].choices = [(build_no, build_no) for build_no in all_build_numbers]
        #form.fields['build_no_2'].choices = [(build_no, build_no) for build_no in all_build_numbers]
        #form.build_no_2 = forms.ChoiceField(label="",  choices=[(build_no, build_no) for build_no in all_build_numbers], initial=build_no_2)
        (failed_jobs_1, tests_result_1) = get_test_results_for_build(build_name, build_no_1, server)
        (failed_jobs_2, tests_result_2) = get_test_results_for_build(build_name, build_no_2, server)
        compare_results = compare_results_func(tests_result_1, tests_result_2)
    else:
        build_name = request.GET.get("build_name", "android-lcr-reference-hikey-o")
        all_build_numbers = get_possible_builds(build_name)
        build_no_1 = request.GET.get("build_no_1", "0")
        build_no_2 = request.GET.get("build_no_2", "0")
        # form = CompareForm(request)
        #form.build_name = forms.CharField(widget=forms.HiddenInput(), initial=build_name)
        #form.build_no_1 = forms.ChoiceField(label="",  choices=[(build_no, build_no) for build_no in get_possible_builds()])
        #form.build_no_2 = forms.ChoiceField(label="",  choices=[(build_no, build_no) for build_no in get_possible_builds()])
        #form.fields['build_no_1'].choices = [(build_no, build_no) for build_no in all_build_numbers]
        #form.fields['build_no_2'].choices = [(build_no, build_no) for build_no in all_build_numbers]


    form = {
                 "build_name": build_name,
                 "build_no_1": build_no_1,
                 "build_no_2": build_no_2,
                 "possible_numbers": all_build_numbers,
           }

    build_info = {
                    "build_name": build_name,
     #               "build_no_1": build_no_1,
     #               "build_no_2": build_no_2,
     #               "build_numbers": get_possible_builds(build_name),
                 }
    return render(request, 'result-comparison.html',
                  {
                   "build_info": build_info,
                   'lava_server_job_prefix': lava_server_job_prefix,
                   #'form': CompareForm(),
                   'form': form,
                   'compare_results': compare_results,
                  }
        )


if __name__ == "__main__":
    (jobs_failed, total_tests_res) = get_test_results_for_build("android-lcr-reference-hikey-o", "11", server)
    print "%d/%d" % (len(jobs_failed), len(total_tests_res))
