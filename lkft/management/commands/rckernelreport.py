## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/


from datetime import datetime as dt
import json
import os
import re
import yaml
import pdb

from django.core.management.base import BaseCommand, CommandError

from django.utils.timesince import timesince

from lkft.models import KernelChange, CiBuild, ReportBuild

from lcr import qa_report

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT, BUILD_WITH_JOBS_NUMBER

from lkft.views import get_test_result_number_for_build, get_projects_info
from lkft.views import extract
from lkft.views import download_attachments_save_result
from lkft.lkft_config import get_version_from_pname, get_kver_with_pname_env

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)

rawkernels = {
   'rc':['5.4-gki-aosp-master-db845c', 
         '4.19-q-10gsi-hikey960',
         '4.19-q-10gsi-hikey',
         '4.14-q-10gsi-hikey960',
         '4.14-q-10gsi-hikey',
         '4.9-p-10gsi-hikey960',
         '4.9-p-10gsi-hikey',
         '4.4-p-10gsi-hikey',
         '4.4-p-9LCR-hikey',
         ],
}

"""
rawkernels = {
   '4.4':['4.4o-8.1-hikey', 
            '4.4o-9.0-lcr-hikey',
            '4.4o-10.0-gsi-hikey',
            '4.4p-9.0-hikey',
            '4.4p-10.0-gsi-hikey',
            ],
   '4.9':['4.9o-8.1-hikey', 
            '4.9o-9.0-lcr-hikey',
            '4.9o-10.0-gsi-hikey',
            '4.9o-10.0-gsi-hikey960',
            '4.9p-9.0-hikey',
            '4.9p-9.0-hikey960',
            '4.9p-10.0-gsi-hikey',
            '4.9p-10.0-gsi-hikey960',
            '4.9q-10.0-gsi-hikey',
            '4.9q-10.0-gsi-hikey960',
            ],
   '4.14':[ '4.14p-9.0-hikey',
            '4.14p-9.0-hikey960',
            '4.14p-10.0-gsi-hikey',
            '4.14p-10.0-gsi-hikey960',
            '4.14q-10.0-gsi-hikey',
            '4.14q-10.0-gsi-hikey960',
            ],
   '4.19':[ 
            '4.19q-10.0-gsi-hikey',
            '4.19q-10.0-gsi-hikey960',
            ],
   '5.4':[ 
            '5.4-gki-aosp-master-hikey960',
            '5.4-gki-aosp-master-db845c',
            ],
}
"""

projectids = {
   '4.4o-8.1-hikey': 
                    {'project_id': 86, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android8',
                     'branch' : 'Android-4.4-o',}, 
   '4.4o-9.0-lcr-hikey':
                    {'project_id': 253, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.4-o',},
   '4.4o-10.0-gsi-hikey':
                    {'project_id': 254, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.4-o',},
   '4.4p-9.0-hikey':
                    {'project_id': 123, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.4-p',},
   '4.4p-10.0-gsi-hikey':
                    {'project_id': 225, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.4-p',},
   '4.9o-8.1-hikey':
                    {'project_id': 87, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android8',
                     'branch' : 'Android-4.9-o',},
   '4.9o-9.0-lcr-hikey':
                    {'project_id': 250, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.9-o',},
   '4.9o-10.0-gsi-hikey':
                    {'project_id': 251, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-o',},
   '4.9o-10.0-gsi-hikey960':
                    {'project_id': 255, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-o',},
   '4.9p-9.0-hikey':
                    {'project_id': 122, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.9-p',},
   '4.9p-9.0-hikey960':
                    {'project_id': 179,
                     'hardware': 'hikey960',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.9-p',},
   '4.9p-10.0-gsi-hikey':
                    {'project_id': 223,
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-p',},
   '4.9p-10.0-gsi-hikey960':
                    {'project_id': 222, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-p',},
   '4.9q-10.0-gsi-hikey':
                    {'project_id': 212, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-q',},
   '4.9q-10.0-gsi-hikey960':
                    {'project_id': 213, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-q',},
   '4.14p-9.0-hikey':
                    {'project_id': 121, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.14-p',},
   '4.14p-9.0-hikey960':
                    {'project_id': 177, 
                     'hardware': 'hikey960',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.14-p',},
   '4.14p-10.0-gsi-hikey':
                    {'project_id': 220, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.14-p',},
   '4.14p-10.0-gsi-hikey960':
                    {'project_id': 221, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.14-p',},
   '4.14q-10.0-gsi-hikey':
                    {'project_id': 211, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch': 'Android-4.14-q',},
   '4.14q-10.0-gsi-hikey960':
                    {'project_id': 214,
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.14-q',},
   '4.19q-10.0-gsi-hikey':
                    {'project_id': 210, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.19-q',},
   '4.19q-10.0-gsi-hikey960':
                    {'project_id': 215, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.19-q',},
   '5.4-gki-aosp-master-hikey960':
                    {'project_id': 257, 
                     'hardware': 'hikey960',
                     'OS' : 'AOSP',
                     'branch' : 'Android-5.4',},
   '5.4-gki-aosp-master-db845c':
                    {'project_id': 261,
                     'hardware': 'db845c',
                     'OS' : 'AOSP',
                     'branch' : 'Android-5.4',},
   'android-lkft-rc/5.4-gki-aosp-master-db845c':
                    {'project_id': 271,
                     'hardware': 'db845c',
                     'OS' : 'AOSP',
                     'branch' : 'Android-5.4',},
   'android-lkft-rc/4.19-q-10gsi-hikey960':
                    {'project_id': 248, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.19-q',},
   'android-lkft-rc/4.19-q-10gsi-hikey':
                    {'project_id': 247, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.19-q',},
   'android-lkft-rc/4.14-q-10gsi-hikey960':
                    {'project_id': 246, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.14-q',},
   'android-lkft-rc/4.14-q-10gsi-hikey':
                    {'project_id': 245, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.14-q',},
   'android-lkft-rc/4.9-p-10gsi-hikey960':
                    {'project_id': 244, 
                     'hardware': 'hikey960',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-p',},
   'android-lkft-rc/4.9-p-10gsi-hikey':
                    {'project_id': 243, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.9-p',},
   'android-lkft-rc/4.4-p-10gsi-hikey':
                    {'project_id': 242, 
                     'hardware': 'hikey',
                     'OS' : 'Android10',
                     'branch' : 'Android-4.4-p',},
   'android-lkft-rc/4.4-p-9LCR-hikey':
                    {'project_id': 249, 
                     'hardware': 'hikey',
                     'OS' : 'LCR-Android9',
                     'branch' : 'Android-4.4-p',},
}

def find_projectid_dict(fullname):
    for key in projectids.keys():
        location = fullname.find(key)
        if location > 0:
            return projectids[key]

    return None


def do_boilerplate():
    now = dt.utcnow()
    print "Generated : " + now.strftime("%d/%m/%Y %H:%M:%S")
    print " "

def versiontoMME(versionString):
    versionDict = { 'Major':0,
                    'Minor':0,
                    'Extra':0, }

    if versionString.startswith('v'):
        versionString = versionString[1:]
    # print versionString
    tokens = re.split( r'[.-]', versionString)
    # print tokens
    if tokens[0].isnumeric() and tokens[1].isnumeric() and tokens[2].isnumeric():
        versionDict['Major'] = tokens[0]
        versionDict['Minor'] = tokens[1]
        versionDict['Extra'] = tokens[2]

    return versionDict

def find_best_two_runs(builds, project_name, project):
    goodruns = []
    bailaftertwo = 0
    number_of_build_with_jobs = 0
    baseVersionDict = None
    nextVersionDict = None

    for build in builds:
        if bailaftertwo == 2:
            break
        build_number_passed = 0
        build_number_failed = 0
        build_number_total = 0
        build_modules_total = 0
        build_modules_done = 0
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))
        if number_of_build_with_jobs < BUILD_WITH_JOBS_NUMBER:
            build_numbers = get_test_result_number_for_build(build, jobs)
            build_number_passed = build_number_passed + build_numbers.get('number_passed')
            build_number_failed = build_number_failed + build_numbers.get('number_failed')
            build_number_total = build_number_total + build_numbers.get('number_total')
            build_modules_total = build_modules_total + build_numbers.get('modules_total')
            build_modules_done = build_modules_done + build_numbers.get('modules_done')
            number_of_build_with_jobs = number_of_build_with_jobs + 1
        number_of_build_with_jobs = number_of_build_with_jobs + 1
        build['numbers'] = {
                           'number_passed': build_number_passed,
                           'number_failed': build_number_failed,
                           'number_total': build_number_total,
                           'modules_done': build_modules_done,
                           'modules_total': build_modules_total,
                           }
        build['created_at'] = qa_report_api.get_aware_datetime_from_str(build.get('created_at'))
        build['jobs'] = jobs
        download_attachments_save_result(jobs=jobs)
        failures = {}
        resubmitted_job_urls = []
       
        jobisacceptable=1 
        for job in jobs:
           if job.get('job_status') is None and \
              job.get('submitted') and \
              not job.get('fetched'):
              job['job_status'] = 'Submitted'
              jobisacceptable = 0

           if job.get('parent_job'):
              resubmitted_job_urls.append(job.get('parent_job'))

           if job['job_status'] == 'Submitted':
              jobisacceptable = 0
           if jobisacceptable == 0:
              build['run_status'] = 'Submitted'

           # print "job " + job.get('job_id') + " " + job['job_status']

           result_file_path = get_result_file_path(job=job)
           if not result_file_path or not os.path.exists(result_file_path):
              continue

           kernel_version = get_kver_with_pname_env(prj_name=project_name, env=job.get('environment'))

           platform = job.get('environment').split('_')[0]
           metadata = {
               'job_id': job.get('job_id'),
               'qa_job_id': qa_report_api.get_qa_job_id_with_url(job_url=job.get('url')),
               'result_url': job.get('attachment_url'),
               'lava_nick': job.get('lava_config').get('nick'),
               'kernel_version': kernel_version,
               'platform': platform,
               }
           numbers = extract(result_file_path, failed_testcases_all=failures, metadata=metadata)
           job['numbers'] = numbers

        if 'run_status' in build:
            # print "found run status" + "build " + str(build.get("id")) + " NOT selected"
            continue
        else:
            # print "run status NOT found" + "build " + str(build.get("id")) + " selected"
            if bailaftertwo == 0 :
                baseVersionDict = versiontoMME(build['version'])
            #    print "baseset"
            elif bailaftertwo == 1 :
                nextVersionDict = versiontoMME(build['version'])
                if nextVersionDict['Extra'] == baseVersionDict['Extra'] :
                    continue
            goodruns.append(build)
            bailaftertwo += 1

        failures_list = []
        for module_name in sorted(failures.keys()):
            failures_in_module = failures.get(module_name)
            for test_name in sorted(failures_in_module.keys()):
                failure = failures_in_module.get(test_name)
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

                failures_list.append(failure)

        android_version = get_version_from_pname(pname=project.get('name'))
        build['failures_list'] = failures_list

    return goodruns


def find_regressions(goodruns):
    runA = goodruns[0]
    failuresA = runA['failures_list']
    runB = goodruns[1]
    failuresB = runB['failures_list']
    regressions = []
    for failureA in failuresA:
        match = 0
        for failureB in failuresB:
            testAname = failureA['test_name']
            testBname = failureB['test_name']
            if testAname == testBname:
                match = 1
                break
        if match != 1 :
            regressions.append(failureA)
    
    return regressions


def add_unique_kernel(unique_kernels, kernel_version):
    if kernel_version not in unique_kernels:
        unique_kernels.append(kernel_version)


def report_results(run, regressions, combo, priorrun):
    jobs = run['jobs']
    job = jobs[0]
    numbers = job['numbers']
    print combo
    project_info = projectids[combo]
    print project_info['branch']
    

    print "Kernel:" + run['version'] + "  Prior:" + priorrun['version']
    if len(regressions) > 0:
        print "Result: FAIL - " + str (len(regressions)) + " Regressions"
    else:
        print "Result: PASS "

    jobs = run['jobs']
    job = jobs[0]
    target_build = qa_report_api.get_build_with_url(job.get('target_build'))
    target_build_metadata = qa_report_api.get_build_meta_with_url(target_build.get('metadata'))

    print "Compiler: " + target_build_metadata['toolchain']
    print "Hardware: " + project_info['hardware'] 
    if len(regressions) > 0:
        print "Regressions:"
    for regression in regressions:
        print "        " + regression['test_name']

def report_kernels_in_report(unique_kernels): 
    print " "
    print " "
    print "Kernels in this report:"
    for kernel in unique_kernels:
        print "    " + kernel

class Command(BaseCommand):
    help = 'returns Android Common Kernel Regression Report for specific kernels'

    def add_arguments(self, parser):
        print ""
  #     parser.add_argument('kernel', type=str, help='Kernel version')

    def handle(self, *args, **options):
        work = []
        unique_kernels=[]

        do_boilerplate()
        group_name = "android-lkft-rc"
        title_head = "LKFT RC Projects"
        projects = get_projects_info(group_name=group_name)

        for project in projects:
            print " "
            project_name = project['full_name']
            project_id = project.get('id')
            builds = qa_report_api.get_all_builds(project_id)
            project_name = project.get('name')
            goodruns = find_best_two_runs(builds, project_name, project)
            add_unique_kernel(unique_kernels, goodruns[0]['version'])
            regressions = find_regressions(goodruns)
            report_results(goodruns[0], regressions, project['full_name'], goodruns[1])

