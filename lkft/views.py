# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django import forms
from django.shortcuts import render

import bugzilla
import collections
import datetime
import json
import logging
import os
import re
import requests
import sys
import tarfile
import tempfile
import xmlrpclib
import xml.etree.ElementTree as ET
import zipfile

from django.contrib.auth.decorators import login_required

from lcr.settings import FILES_DIR, LAVA_SERVERS, BUGZILLA_API_KEY, BUILD_WITH_JOBS_NUMBER
from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT

from lcr import qa_report
from lcr.qa_report import DotDict
from lcr.utils import download_urllib
from lkft.lkft_config import find_citrigger, find_cibuild, get_hardware_from_pname, get_version_from_pname, get_kver_with_pname_env

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)


DIR_ATTACHMENTS = os.path.join(FILES_DIR, 'lkft')
logger = logging.getLogger(__name__)

TEST_RESULT_XML_NAME = 'test_result.xml'

for nick, config in LAVA_SERVERS.items():
    server_url = "https://%s:%s@%s/RPC2/" % ( config.get('username'),
                                              config.get('token'),
                                              config.get('hostname'))
    server = xmlrpclib.ServerProxy(server_url)
    config.update({'server': server})

bugzilla_host_name = 'bugs.linaro.org'
bugzilla_api_url = "https://%s/rest" % bugzilla_host_name
bugzilla_instance = bugzilla.Bugzilla(url=bugzilla_api_url, api_key=BUGZILLA_API_KEY)
bugzilla_show_bug_prefix = 'https://%s/show_bug.cgi?id=' % bugzilla_host_name

def find_lava_config(job_url):
    if job_url is None:
        return None
    for nick, config in LAVA_SERVERS.items():
        if job_url.find('://%s/' % config.get('hostname')) >= 0:
            return config
    return None

def get_attachment_urls(jobs=[]):
    first_job = jobs[0]
    target_build = qa_report_api.get_build_with_url(first_job.get('target_build'))
    target_build_metadata = qa_report_api.get_build_meta_with_url(target_build.get('metadata'))

    for job in jobs:
        lava_config = job.get('lava_config')
        if not lava_config :
            lava_config = find_lava_config(job.get('external_url'))
            if not lava_config:
                logger.error('lava server is not found for job: %s' % job.get('url'))
                return None
            else:
                job['lava_config'] = lava_config

        if not job.get('job_status') or job.get('job_status') == 'Submitted' \
                or job.get('job_status') == 'Running' :
            # the job is still in queue, so it should not have attachment yet
            continue

        attachment_url_key = 'tradefed_results_url_%s' % job.get('job_id')
        attachment_url = target_build_metadata.get(attachment_url_key)
        job['attachment_url'] = attachment_url


def extract_save_result(tar_path, result_zip_path):
    zip_parent = os.path.abspath(os.path.join(result_zip_path, os.pardir))
    if not os.path.exists(zip_parent):
        os.mkdirs(zip_parent)
    # https://pymotw.com/2/zipfile/
    tar = tarfile.open(tar_path, "r")
    for f_name in tar.getnames():
        if f_name.endswith("/%s" % TEST_RESULT_XML_NAME):
            result_fd = tar.extractfile(f_name)
            with zipfile.ZipFile(result_zip_path, 'w') as f_zip_fd:
                f_zip_fd.writestr(TEST_RESULT_XML_NAME, result_fd.read(), compress_type=zipfile.ZIP_DEFLATED)
                logger.info('Save result in %s to %s' % (tar_path, result_zip_path))

    tar.close()


def get_result_file_path(job=None):
    if not job.get('lava_config'):
        return None
    lava_nick = job.get('lava_config').get('nick')
    job_id = job.get('job_id')
    result_file_path = os.path.join(DIR_ATTACHMENTS, "%s-%s.zip" % (lava_nick, job_id))
    return result_file_path

def download_attachments_save_result(jobs=[]):
    # https://lkft.validation.linaro.org/scheduler/job/566144
    get_attachment_urls(jobs=jobs)
    for job in jobs:
        if not job.get('lava_config'):
            continue

        lava_nick = job.get('lava_config').get('nick')
        job_id = job.get('job_id')
        job_url = job.get('external_url')
        result_file_path = get_result_file_path(job)
        if not result_file_path:
            logger.info("Skip to get the attachment as the result_file_path is not found: %s %s" % (job_url, job.get('url')))
            continue
        if not os.path.exists(result_file_path):
            if job.get('job_status') != 'Complete':
                logger.info("Skip to get the attachment as the job is not Complete: %s %s" % (job_url, job.get('name')))
                continue

            attachment_url = job.get('attachment_url')
            if not attachment_url:
                logger.info("No attachment for job: %s %s" % (job_url, job.get('name')))
                continue

            (temp_fd, temp_path) = tempfile.mkstemp(suffix='.tar.xz', text=False)
            logger.info("Start downloading result file for job %s %s: %s" % (job_url, job.get('name'), temp_path))
            ret_err = download_urllib(attachment_url, temp_path)
            if ret_err:
                logger.info("There is a problem with the size of the file: %s" % attachment_url)
                continue
            else:
                tar_f = temp_path.replace(".xz", '')
                ret = os.system("xz -d %s" % temp_path)
                if ret == 0 :
                    extract_save_result(tar_f, result_file_path)
                    os.unlink(tar_f)
                else:
                    logger.info("Failed to decompress %s with xz -d command for job: %s " % (temp_path, job_url))


def extract(result_zip_path, failed_testcases_all={}, metadata={}):
    kernel_version = metadata.get('kernel_version')
    platform = metadata.get('platform')
    qa_job_id = metadata.get('qa_job_id')
    total_number = 0
    passed_number = 0
    failed_number = 0

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
                    total_number = total_number + len(test_case.findall('.//Test'))
                    passed_number = passed_number + len(test_case.findall('.//Test[@result="pass"]'))
                    failed_tests = test_case.findall('.//Test[@result="fail"]')
                    failed_number = failed_number + len(failed_tests)
                    for failed_test in failed_tests:
                        #test_name = '%s#%s' % (test_case.get("name"), vts_abi_suffix_pat.sub('', failed_test.get("name")))
                        test_name = '%s#%s' % (test_case.get("name"), failed_test.get("name"))
                        stacktrace = failed_test.find('.//Failure/StackTrace').text
                        ## ignore duplicate cases as the jobs are for different modules
                        failed_testcase = failed_tests_module.get(test_name)
                        if failed_testcase:
                            if failed_testcase.get('abi_stacktrace').get(abi) is None:
                                failed_testcase.get('abi_stacktrace')[abi] = stacktrace

                            if not qa_job_id in failed_testcase.get('qa_job_ids'):
                                failed_testcase.get('qa_job_ids').append(qa_job_id)

                            if not kernel_version in failed_testcase.get('kernel_versions'):
                                failed_testcase.get('kernel_versions').append(kernel_version)

                            if not platform in failed_testcase.get('platforms'):
                                failed_testcase.get('platforms').append(platform)
                        else:
                            failed_tests_module[test_name]= {
                                                                'test_name': test_name,
                                                                'module_name': module_name,
                                                                'test_class': test_case.get("name"),
                                                                'test_method': failed_test.get("name"),
                                                                'abi_stacktrace': {abi: stacktrace},
                                                                'qa_job_ids': [ qa_job_id ],
                                                                'kernel_versions': [ kernel_version ],
                                                                'platforms': [ platform ],
                                                            }

        except ET.ParseError as e:
            logger.error('xml.etree.ElementTree.ParseError: %s' % e)
            logger.info('Please Check %s manually' % result_zip_path)
    return {
                'total_number': total_number,
                'passed_number': passed_number,
                'failed_number': failed_number
            }


def get_last_trigger_build(lkft_pname=''):
    ci_trigger_name = find_citrigger(lkft_pname=lkft_pname)
    if not ci_trigger_name:
        return None
    return jenkins_api.get_last_build(cijob_name=ci_trigger_name)


def get_testcases_number_for_job(job):
    job_number_passed = 0
    job_number_failed = 0
    job_number_total = 0
    modules_total = 0
    modules_done = 0

    result_file_path = get_result_file_path(job=job)
    if result_file_path and os.path.exists(result_file_path):
        with zipfile.ZipFile(result_file_path, 'r') as f_zip_fd:
            try:
                root = ET.fromstring(f_zip_fd.read(TEST_RESULT_XML_NAME))
                summary_node = root.find('Summary')
                job_number_passed = summary_node.attrib['pass']
                job_number_failed = summary_node.attrib['failed']
                modules_total = summary_node.attrib['modules_total']
                modules_done = summary_node.attrib['modules_done']
            except ET.ParseError as e:
                logger.error('xml.etree.ElementTree.ParseError: %s' % e)
                logger.info('Please Check %s manually' % result_zip_path)
    return {
            'number_passed': int(job_number_passed),
            'number_failed': int(job_number_failed),
            'number_total': int(job_number_passed) + int(job_number_failed),
            'modules_total': int(modules_total),
            'modules_done': int(modules_done)
            }


def get_test_result_number_for_build(build, jobs=None):
    build_number_passed = 0
    build_number_failed = 0
    build_number_total = 0
    build_modules_total = 0
    build_modules_done = 0

    if not jobs:
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))

    resubmitted_job_urls = [ job.get('parent_job') for job in jobs if job.get('parent_job')]
    download_attachments_save_result(jobs=jobs)
    job_names = []
    for job in jobs:
        if job.get('url') in resubmitted_job_urls:
            # ignore jobs which were resubmitted
            logger.info("%s: %s:%s has been resubmitted already" % (build.get('version'), job.get('job_id'), job.get('url')))
            continue

        if job.get('name') in job_names:
            logger.info("%s %s: %s %s the same name job has been recorded" % (build.get('version'), job.get('name'), job.get('job_id'), job.get('url')))
            continue

        numbers = get_testcases_number_for_job(job)
        build_number_passed = build_number_passed + numbers.get('number_passed')
        build_number_failed = build_number_failed + numbers.get('number_failed')
        build_number_total = build_number_total + numbers.get('number_total')
        build_modules_total = build_modules_total + numbers.get('modules_total')
        build_modules_done = build_modules_done + numbers.get('modules_done')
        job['numbers'] = numbers
        job_names.append(job.get('name'))

    return {
        'number_passed': build_number_passed,
        'number_failed': build_number_failed,
        'number_total': build_number_total,
        'modules_done': build_modules_done,
        'modules_total': build_modules_total,
        }

def get_lkft_build_status(build, jobs):
    if not jobs:
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))

    resubmitted_job_urls = [ job.get('parent_job') for job in jobs if job.get('parent_job')]
    job_names = []
    jobs_to_be_checked = []
    for job in jobs:
        if job.get('url') in resubmitted_job_urls:
            # ignore jobs which were resubmitted
            logger.info("%s: %s:%s has been resubmitted already" % (build.get('version'), job.get('job_id'), job.get('url')))
            continue

        if job.get('name') in job_names:
            logger.info("%s %s: %s %s the same name job has been recorded" % (build.get('version'), job.get('name'), job.get('job_id'), job.get('url')))
            continue

        jobs_to_be_checked.append(job)
        job_names.append(job.get('name'))

    last_fetched_timestamp = build.get('created_at')
    has_unsubmitted = False
    is_inprogress = False
    for job in jobs_to_be_checked:
        if not job.get('submitted'):
            has_unsubmitted = True
            break
        if job.get('fetched'):
            job_last_fetched_timestamp = datetime.datetime.strptime(job.get('fetched_at'), '%Y-%m-%dT%H:%M:%S.%fZ')
            if job_last_fetched_timestamp > last_fetched_timestamp:
                last_fetched_timestamp = job_last_fetched_timestamp
        else:
            is_inprogress = True
            break

    return {
        'is_inprogress': is_inprogress,
        'has_unsubmitted': has_unsubmitted,
        'last_fetched_timestamp': last_fetched_timestamp,
        }


@login_required
def list_projects(request):
    projects = []
    for project in qa_report_api.get_projects():
        project_full_name = project.get('full_name')
        if not project_full_name.startswith('android-lkft/') \
                or project.get('is_archived'):
            continue

        builds = qa_report_api.get_all_builds(project.get('id'))
        if len(builds) > 0:
            last_build = builds[0]
            created_str = last_build.get('created_at')
            last_build['created_at'] = datetime.datetime.strptime(str(created_str), '%Y-%m-%dT%H:%M:%S.%fZ')

            jobs = qa_report_api.get_jobs_for_build(last_build.get("id"))
            last_build['numbers_of_result'] = get_test_result_number_for_build(last_build, jobs)
            build_status = get_lkft_build_status(last_build, jobs)
            if build_status['has_unsubmitted']:
                last_build['build_status'] = "JOBSNOTSUBMITTED"
            elif build_status['is_inprogress']:
                last_build['build_status'] = "JOBSINPROGRESS"
            else:
                last_build['build_status'] = "JOBSCOMPLETED"
                last_build['last_fetched_timestamp'] = build_status['last_fetched_timestamp']
            project['last_build'] = last_build

        last_trigger_build = get_last_trigger_build(project.get('name'))
        if last_trigger_build:
            last_trigger_url = last_trigger_build.get('url')
            last_trigger_build = jenkins_api.get_build_details_with_full_url(build_url=last_trigger_url)
            last_trigger_build['start_timestamp'] = datetime.datetime.fromtimestamp(int(last_trigger_build['timestamp'])/1000)
            last_trigger_build['duration'] = datetime.timedelta(milliseconds=last_trigger_build['duration'])
            project['last_trigger_build'] = last_trigger_build

        ci_build_project_name = find_cibuild(lkft_pname=project.get('name'))
        if ci_build_project_name:
            ci_build_project = jenkins_api.get_build_details_with_job_url(ci_build_project_name)

            isInQueue = ci_build_project.get('inQueue')

            if isInQueue:
                build_status = 'INQUEUE'
                kernel_version = 'Unknown'
                queueItem = ci_build_project.get('queueItem')
                if queueItem:
                    # BUILD_DIR=lkft
                    # ANDROID_BUILD_CONFIG=lkft-hikey-android-9.0-mainline lkft-hikey-android-9.0-mainline-auto
                    # KERNEL_DESCRIBE=v5.3-rc7-223-g5da9f3fe49d4
                    # SRCREV_kernel=5da9f3fe49d47e313e397694c195c3b9b9b24134
                    # MAKE_KERNELVERSION=5.3.0-rc7
                    params = queueItem.get('params').strip().split('\n')
                    for param in params:
                        if param.find('KERNEL_DESCRIBE') >= 0:
                            kernel_version = param.split('=')[1]
                            break
                # case for aosp master tracking build
                if kernel_version == 'dummy':
                    kernel_version = ci_build_project.get('nextBuildNumber')
            elif ci_build_project.get('lastBuild') is not None:
                ci_build_last_url = ci_build_project.get('lastBuild').get('url')
                ci_build_last = jenkins_api.get_build_details_with_full_url(build_url=ci_build_last_url)
                ci_build_last['start_timestamp'] = datetime.datetime.fromtimestamp(int(ci_build_last['timestamp'])/1000)
                ci_build_last['duration'] = datetime.timedelta(milliseconds=ci_build_last['duration'])

                kernel_version = ci_build_last.get('displayName') # #buildNo.-kernelInfo
                if ci_build_last.get('building'):
                    build_status = 'INPROGRESS'
                else:
                    build_status = ci_build_last.get('result') # null or SUCCESS, FAILURE, ABORTED
            else:
                build_status = 'NOBUILDYET'
                kernel_version = 'Unknown'

            last_ci_build= {
                'build_status': build_status,
                'kernel_version': kernel_version,
                'ci_build_project_url': ci_build_project.get('url'),
            }
            project['last_ci_build'] = last_ci_build

        if project['last_build'] and last_trigger_build and \
            project['last_build']['build_status'] == "JOBSCOMPLETED":
            project['duration'] = project['last_build']['last_fetched_timestamp'] - last_trigger_build['start_timestamp']
        projects.append(project)

    bugs = get_lkft_bugs()
    open_bugs = []
    for bug in bugs:
        if bug.status == 'VERIFIED' or bug.status== 'RESOLVED':
            continue
        else:
            open_bugs.append(bug)

    def get_project_name(item):
        return item.get('name')

    sorted_projects = sorted(projects, key=get_project_name)
    return render(request, 'lkft-projects.html',
                           {
                                "projects": sorted_projects,
                                'open_bugs': open_bugs,
                            }
                )


@login_required
def list_builds(request):
    project_id = request.GET.get('project_id', None)
    project =  qa_report_api.get_project(project_id)
    builds = qa_report_api.get_all_builds(project_id)
    number_of_build_with_jobs = 0
    for build in builds:
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

        build['numbers'] = {
                            'number_passed': build_number_passed,
                            'number_failed': build_number_failed,
                            'number_total': build_number_total,
                            'modules_done': build_modules_done,
                            'modules_total': build_modules_total,
                            }
        created_str = build.get('created_at')
        build['created_at'] = datetime.datetime.strptime(str(created_str), '%Y-%m-%dT%H:%M:%S.%fZ')
        build['jobs'] = jobs

    return render(request, 'lkft-builds.html',
                           {
                                "builds": builds,
                                'project': project,
                            })


def get_lkft_bugs():
    bugs = []

    terms = [
                {u'product': 'Linaro Android'},
                {u'component': 'General'},
                {u'platform': 'HiKey'},
                {u'op_sys': 'Android'},
                {u'keywords': 'LKFT'}
            ]

    for bug in bugzilla_instance.search_bugs(terms).bugs:
        bugs.append(bugzilla.DotDict(bug))

    def get_bug_summary(item):
        return item.get('summary')

    sorted_bugs = sorted(bugs, key=get_bug_summary)
    return sorted_bugs


@login_required
def list_jobs(request):
    build_id = request.GET.get('build_id', None)
    build =  qa_report_api.get_build(build_id)
    project =  qa_report_api.get_project_with_url(build.get('project'))
    jobs = qa_report_api.get_jobs_for_build(build_id)

    project_name = project.get('name')

    download_attachments_save_result(jobs=jobs)
    failures = {}
    resubmitted_job_urls = []
    for job in jobs:
        if job.get('failure'):
            failure = job.get('failure')
            new_str = failure.replace('"', '\\"').replace('\'', '"')
            try:
                failure_dict = json.loads(new_str)
            except ValueError:
                failure_dict = {'error_msg': new_str}
        if job.get('parent_job'):
            resubmitted_job_urls.append(job.get('parent_job'))
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

    bugs = get_lkft_bugs()
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

            for bug in bugs:
                if test_name.find(module_name) >=0:
                    # vts test, module name is the same as the test name.
                    search_key = test_name
                else:
                    search_key = '%s %s' % (module_name, test_name)

                if bug.summary.find(search_key) >= 0:
                    if failure.get('bugs'):
                        failure['bugs'].append(bug)
                    else:
                        failure['bugs'] = [bug]

    android_version = get_version_from_pname(pname=project.get('name'))
    open_bugs = []
    for bug in bugs:
        if bug.status == 'VERIFIED' or bug.status == 'RESOLVED':
            continue

        if bug.version != android_version:
            continue

        open_bugs.append(bug)


    # sort failures
    for module_name, failures_in_module in failures.items():
        failures[module_name] = collections.OrderedDict(sorted(failures_in_module.items()))
    failures = collections.OrderedDict(sorted(failures.items()))


    def get_job_name(item):
        return item.get('name')

    sorted_jobs = sorted(jobs, key=get_job_name)
    final_jobs = []
    failed_jobs = []
    for job in sorted_jobs:
        job['qa_job_id'] = qa_report_api.get_qa_job_id_with_url(job.get('url'))
        if job.get('url') in resubmitted_job_urls:
            failed_jobs.append(job)
        else:
            final_jobs.append(job)

    return render(request, 'lkft-jobs.html',
                           {
                                'final_jobs': final_jobs,
                                'failed_jobs': failed_jobs,
                                'build': build,
                                'failures': failures,
                                'failures_list': failures_list,
                                'open_bugs':open_bugs,
                                'project': project,
                                'bugzilla_show_bug_prefix': bugzilla_show_bug_prefix,
                            }
                )


def get_bug_hardware_from_environment(environment):
    if environment.find('hi6220-hikey')>=0:
        return 'HiKey'
    else:
        return None

class BugCreationForm(forms.Form):
    project_name = forms.CharField(label='Project Name', widget=forms.TextInput(attrs={'size': 80}))
    project_id = forms.CharField(label='Project Id.')
    build_version = forms.CharField(label='Build Version', widget=forms.TextInput(attrs={'size': 80}))
    build_id = forms.CharField(label='Build Id.')
    product = forms.CharField(label='Product', widget=forms.TextInput(attrs={'readonly': True}))
    component = forms.CharField(label='Component', widget=forms.TextInput(attrs={'readonly': True}))
    version = forms.CharField(label='Version', widget=forms.TextInput(attrs={'readonly': True}) )
    os = forms.CharField(label='Os', widget=forms.TextInput(attrs={'readonly': True}))
    hardware = forms.CharField(label='Hardware', widget=forms.TextInput(attrs={'readonly': True}))
    severity = forms.CharField(label='Severity')
    keywords = forms.CharField(label='keywords')
    summary = forms.CharField(label='Summary', widget=forms.TextInput(attrs={'size': 80}))
    description = forms.CharField(label='Description', widget=forms.Textarea(attrs={'cols': 80}))

@login_required
def file_bug(request):
    submit_result = False
    if request.method == 'POST':
        form = BugCreationForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            bug = bugzilla.DotDict()
            bug.product = cd['product']
            bug.component = cd['component']
            bug.summary = cd['summary']
            bug.description = cd['description']
            bug.bug_severity = cd['severity']
            bug.op_sys = cd['os']
            bug.platform = cd['hardware']
            bug.version = cd['version']
            bug.keywords = cd['keywords']

            bug_id = bugzilla_instance.post_bug(bug).id
            bug_info = {
                           'bugzilla_show_bug_prefix': bugzilla_show_bug_prefix,
                           'bug_id': bug_id,
                        }
            submit_result = True
            return render(request, 'lkft-file-bug.html',
                          {
                            "submit_result": submit_result,
                            'bug_info': bug_info,
                            'form': form,
                          })

        else:
            # not possible here since all are selectable elements
            return render(request, 'lkft-file-bug.html',
                      {
                        "form": form,
                        'submit_result': False,
                      })
    else: # GET
        project_name = request.GET.get("project_name")
        project_id = request.GET.get("project_id")
        build_id = request.GET.get("build_id")
        qa_job_ids_str = request.GET.get("qa_job_ids")
        module_name = request.GET.get("module_name")
        test_name = request.GET.get("test_name")

        qa_job_ids_tmp = qa_job_ids_str.split(',')
        qa_job_ids = []
        qa_jobs = []
        # remove the duplicate job_ids
        target_build = None
        for qa_job_id in qa_job_ids_tmp:
            if not qa_job_id in qa_job_ids:
                qa_job_ids.append(qa_job_id)
                #https://qa-reports.linaro.org/api/testjobs/1319604/?format=json
                qa_job = qa_report_api.get_job_with_id(qa_job_id)
                if qa_job is not None:
                    qa_jobs.append(qa_job)
                if target_build is None:
                    target_build = qa_job.get('target_build')
                elif target_build != qa_job.get('target_build'):
                    # need to make sure all the jobs are belong to the same build
                    # otherwise there is no meaning to list failures from jobs belong to different builds
                    # TODO : report error on webpage
                    logger.error("The jobs are belong to different builds: %s" % (qa_job_ids_str))

        project =  qa_report_api.get_project_with_url(qa_jobs[0].get('target'))
        build = qa_report_api.get_build_with_url(qa_jobs[0].get('target_build'))
        build_meta = qa_report_api.get_build_meta_with_url(build.get('metadata'))

        # download all the necessary attachments
        download_attachments_save_result(jobs=qa_jobs)

        pname = project.get('name')
        form_initial = {
                        "project_name": pname,
                        "project_id": project.get('id'),
                        'build_version': build.get('version'),
                        'build_id': build.get('id'),
                        'product': 'Linaro Android',
                        'component': 'General',
                        'severity': 'normal',
                        'os': 'Android',
                        'hardware': get_hardware_from_pname(pname=pname, env=qa_jobs[0].get('environment')),
                        'keywords': 'LKFT',
                        'version': get_version_from_pname(pname=pname),
                        }


        def extract_abi_stacktrace(result_zip_path, module_name='', test_name=''):

            failures = {}
            class_method = test_name.split('#')
            with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
                try:
                    root = ET.fromstring(f_zip_fd.read(TEST_RESULT_XML_NAME))
                    for elem in root.findall('.//Module[@name="%s"]' %(module_name)):
                        abi = elem.attrib['abi']
                        stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                        if stacktrace_node is None:
                            # Try for VtsHal test cases
                            if abi == 'arm64-v8a':
                                stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s_64bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))
                            elif abi == 'armeabi-v7a':
                                stacktrace_node = elem.find('.//TestCase[@name="%s"]/Test[@name="%s_32bit"]/Failure/StackTrace' %(class_method[0], class_method[1]))

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
        failed_kernels = []
        for qa_job in qa_jobs:
            lava_job_id = qa_job.get('job_id')
            lava_url = qa_job.get('external_url')
            if not lava_url:
                logger.error('Job seems not submitted yet: '% job.get('url'))
                continue
            lava_config = find_lava_config(lava_url)
            result_file_path = get_result_file_path(qa_job)

            kernel_version = get_kver_with_pname_env(prj_name=project.get('name'), env=qa_job.get('environment'))

            qa_job['kernel_version'] = kernel_version
            job_failures = extract_abi_stacktrace(result_file_path, module_name=module_name, test_name=test_name)
            failures.update(job_failures)
            if not kernel_version in failed_kernels:
                # assuming the job specified mush have the failure for the module and test
                failed_kernels.append(kernel_version)

        abis = sorted(failures.keys())
        stacktrace_msg = ''
        if len(abis) == 0:
            logger.error('Failed to get stacktrace information for %s %s form jobs: '% (module_name, test_name, str(qa_job_ids_str)))
        elif (len(abis) == 2) and (failures.get(abis[0]) != failures.get(abis[1])):
            for abi in abis:
                stacktrace_msg = '%s\n\n%s:\n%s' % (stacktrace_msg, abi, failures.get(abi))
        else:
            stacktrace_msg = failures.get(abis[0])

        if test_name.find(module_name) >=0:
            form_initial['summary'] = '%s: %s' % (project.get('name'), test_name)
            description = '%s' % (test_name)
        else:
            form_initial['summary'] = '%s: %s %s' % (project.get('name'), module_name, test_name)
            description = '%s %s' % ( module_name, test_name)

        history_urls = []
        for abi in abis:
            if module_name.startswith('Vts'):
                test_res_dir = 'vts-test'
            else:
                test_res_dir = 'cts-lkft'
            history_url = '%s/%s/tests/%s/%s.%s/%s' % (qa_report_api.get_api_url_prefix(),
                                                             project.get('full_name'),
                                                             test_res_dir,
                                                             abi,
                                                             module_name,
                                                             test_name.replace('#', '.'))
            history_urls.append(history_url)

        description += '\n\nABIs:\n%s' % (' '.join(abis))
        description += '\n\nQA Report Test History Urls:\n%s' % ('\n'.join(history_urls))
        description += '\n\nKernels:\n%s' % (' '.join(sorted(failed_kernels)))
        description += '\n\nBuild Version:\n%s' % (build.get('version'))
        description += '\n\nStackTrace: \n%s' % (stacktrace_msg.strip())
        description += '\n\nLava Jobs:'
        for qa_job in qa_jobs:
            description += '\n%s' % (qa_job.get('external_url'))

        description += '\n\nResult File Urls:'
        for qa_job in qa_jobs:
            description += '\n%s' % qa_job.get('attachment_url')

        #description += '\n\nImages Url:\n%s/%s/%s' % (android_snapshot_url_base, build_name, build_no)

        form_initial['description'] = description
        form = BugCreationForm(initial=form_initial)

        build_info = {
                      'build_name': 'build_name',
                      'build_no': 'build_no',
                     }
    return render(request, 'lkft-file-bug.html',
                    {
                        "form": form,
                        'build_info': build_info,
                    })


@login_required
def resubmit_job(request):
    qa_job_ids = request.POST.getlist("qa_job_ids")
    if len(qa_job_ids) == 0:
        qa_job_id = request.GET.get("qa_job_id", "")
        if qa_job_id:
            qa_job_ids = [qa_job_id]

    if len(qa_job_ids) == 0:
        return render(request, 'lkft-job-resubmit.html',
                      {
                        'errors': True,
                      })
    logger.info('user: %s is going to resubmit job: %s' % (request.user, str(qa_job_ids)))

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

    return render(request, 'lkft-job-resubmit.html',
                  {
                   'results': results,
                  }
    )
