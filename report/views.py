# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.shortcuts import render
from django.http import HttpResponse

import re
import sys
import yaml
import xmlrpclib
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
                "tradefed-test-run",
                "3D-mean","Overall_Score-mean", "Memory_Bandwidth_Add_Multi_Core-mean", "Platform-mean", "Memory_Bandwidth-mean", "Memory_Bandwidth_Copy_Single_Core-mean", "Memory_Latency_64M_range-mean", "Memory_Bandwidth_Scale_Single_Core-mean", "Memory_Bandwidth_Copy_Multi_Core-mean", "Storage-mean", "Memory_Bandwidth_Triad_Single_Core-mean", "CoreMark-PRO_Base-mean", "Memory_Bandwidth_Add_Single_Core-mean", "CoreMark-PRO_Peak-mean", "Memory_Bandwidth_Scale_Multi_Core-mean", "Memory_Latency-mean", "Memory_Bandwidth_Triad_Multi_Core-mean",
               ]

job_status_dict = {0: "Submitted",
                   1: "Running",
                   2: "Complete",
                   3: "Incomplete",
                   4: "Canceled",
                  }


def get_jobs(build_name, build_no, server):
    search_condition = "description__icontains__%s-%s" % (build_name, build_no)
    jobs_from_lava = server.results.make_custom_query("testjob", search_condition)
    jobs = { }
    for job in jobs_from_lava:
        job_id = job.get("id")
        job_description = job.get("description")
        job_status = job.get("status")
        job_name = job_description.replace("%s-%s-" % (build_name, build_no), "")

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
    tests_res = []
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
            ## print "%s" % str(test)
            tests_res.append(test)

        return tests_res

    except xmlrpclib.Fault as e:
        raise e
    except:
        raise


def jobs(request):
    #build_name = "android-lcr-reference-hikey-o"
    build_no = request.GET.get("build_no", "10")
    build_name = request.GET.get("build_name", "android-lcr-reference-hikey-o")

    jobs_failed = []
    total_tests_res = []

    jobs = jobs_dict_to_sorted_tuple(get_jobs(build_name, build_no, server))
    for job in jobs:
        id_list = job.get("id_list")
        job_total_res = []
        for job_id in id_list:
            tests_res = get_yaml_result(job_id, server)
            if len(tests_res) != 0:
                job_total_res.extend(tests_res)

        if len(job_total_res) == 0:
            jobs_failed.append(job)
        else:
            total_tests_res.append({
                                     "job_name": job.get("name"),
                                     "id_status_list": job.get("id_status_list"),
                                     "results": job_total_res})

    build_config_url = "http://android-git.linaro.org/android-build-configs.git/tree/%s" % (build_name.replace("android-", ""))

    build_info = {
                    "build_name": build_name,
                    "build_no": build_no,
                    "ci_url_base": "https://ci.linaro.org/job",
                    "snapshot_url_base": "https://snapshots.linaro.org/android",
                    "android_tag": "android-8.0.0_r4",
                    "build_config_url": build_config_url,
                 }
    return render(request, 'jobs.html',
                  {
                   'jobs_failed': jobs_failed,
                   'jobs_result': total_tests_res,
                   'lava_server_job_prefix': lava_server_job_prefix,
                   'build_info': build_info,
                  }
        )

if __name__ == "__main__":
    for job in jobs_dict_to_sorted_tuple(get_jobs(build_name, build_no, server)):
        print str(job)
