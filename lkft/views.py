# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django import forms
from django.http import HttpResponse
from django.shortcuts import render

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
import xml.etree.ElementTree as ET
import zipfile

from django.contrib.auth.decorators import login_required
from django.utils.timesince import timesince

from lcr.settings import FILES_DIR, LAVA_SERVERS, BUGZILLA_API_KEY, BUILD_WITH_JOBS_NUMBER
from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT
from lcr.irc import IRC

from lcr import qa_report, bugzilla
from lcr.qa_report import DotDict, UrlNotFoundException
from lcr.utils import download_urllib
from lkft.lkft_config import find_citrigger, find_cibuild, get_hardware_from_pname, get_version_from_pname, get_kver_with_pname_env
from lkft.lkft_config import find_expect_cibuilds
from lkft.lkft_config import get_configs, get_qa_server_project

from .models import KernelChange, CiBuild, ReportBuild, ReportProject

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)
irc = IRC.getInstance()

DIR_ATTACHMENTS = os.path.join(FILES_DIR, 'lkft')
logger = logging.getLogger(__name__)

TEST_RESULT_XML_NAME = 'test_result.xml'

class LinaroAndroidLKFTBug(bugzilla.Bugzilla):

    def __init__(self, host_name, api_key):
        self.host_name = host_name
        self.new_bug_url_prefix = "https://%s/enter_bug.cgi" % self.host_name
        self.rest_api_url = "https://%s/rest" % self.host_name
        self.show_bug_prefix = 'https://%s/show_bug.cgi?id=' % self.host_name

        self.product = 'Linaro Android'
        self.component = 'General'
        self.bug_severity = 'normal'
        self.op_sys = 'Android'
        self.keywords = "LKFT"

        super(LinaroAndroidLKFTBug, self).__init__(self.rest_api_url, api_key)

        #self.build_version = None
        #self.hardware = None
        #self.version = None

    def get_new_bug_url_prefix(self):
        new_bug_url = '%s?product=%s&op_sys=%s&bug_severity=%s&component=%s&keywords=%s' % ( self.new_bug_url_prefix,
                                                                                                   self.product,
                                                                                                   self.op_sys,
                                                                                                   self.bug_severity,
                                                                                                   self.component,
                                                                                                   self.keywords)
        return new_bug_url

bugzilla_host_name = 'bugs.linaro.org'
bugzilla_instance = LinaroAndroidLKFTBug(host_name=bugzilla_host_name, api_key=BUGZILLA_API_KEY)
bugzilla_show_bug_prefix = bugzilla_instance.show_bug_prefix

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
        os.makedirs(zip_parent)
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
    modules_done = 0
    modules_total = 0

    # no affect for cts result and non vts-hal test result
    vts_abi_suffix_pat = re.compile(r"_32bit$|_64bit$")
    with zipfile.ZipFile(result_zip_path, 'r') as f_zip_fd:
        try:
            root = ET.fromstring(f_zip_fd.read(TEST_RESULT_XML_NAME))

            summary_node = root.find('Summary')
            passed_number = int(summary_node.attrib['pass'])
            failed_number = int(summary_node.attrib['failed'])
            total_number = passed_number + failed_number
            modules_done = int(summary_node.attrib['modules_done'])
            modules_total = int(summary_node.attrib['modules_total'])

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
                        #test_name = '%s#%s' % (test_case.get("name"), vts_abi_suffix_pat.sub('', failed_test.get("name")))
                        mod_name = test_case.get("name")
                        test_name = failed_test.get("name")
                        if test_name.endswith('_64bit') or test_name.endswith('_32bit'):
                            test_name = '%s#%s' % (mod_name, test_name)
                        else: 
                            test_name = '%s#%s#%s' % (mod_name, test_name, abi)
                        message = failed_test.find('.//Failure').attrib.get('message')
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
                                                                'message': message,
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
                'failed_number': failed_number,
                'modules_done': modules_done,
                'modules_total': modules_total,
            }


def get_last_trigger_build(project=None):
    ci_trigger_name = find_citrigger(project=project)
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

    job['numbers'] = {
            'number_passed': int(job_number_passed),
            'number_failed': int(job_number_failed),
            'number_total': int(job_number_passed) + int(job_number_failed),
            'modules_total': int(modules_total),
            'modules_done': int(modules_done)
            }

    return job['numbers']


def get_classified_jobs(jobs=[]):
    '''
        remove the resubmitted jobs and duplicated jobs(needs the jobs to be sorted in job_id descending order)
        as the result for the resubmit(including the duplicated jobs) jobs should be ignored.
    '''
    resubmitted_job_urls = [ job.get('parent_job') for job in jobs if job.get('parent_job')]
    job_names = []
    jobs_to_be_checked = []
    resubmitted_or_duplicated_jobs = []
    for job in jobs:
        if job.get('url') in resubmitted_job_urls:
            # ignore jobs which were resubmitted
            logger.info("%s: %s:%s has been resubmitted already" % (build.get('version'), job.get('job_id'), job.get('url')))
            job['resubmitted'] = True
            resubmitted_or_duplicated_jobs.append(job)
            continue

        if job.get('name') in job_names:
            logger.info("%s %s: %s %s the same name job has been recorded" % (build.get('version'), job.get('name'), job.get('job_id'), job.get('url')))
            job['duplicated'] = True
            resubmitted_or_duplicated_jobs.append(job)
            continue

        jobs_to_be_checked.append(job)
        job_names.append(job.get('name'))

    return {
        'final_jobs': jobs_to_be_checked,
        'resubmitted_or_duplicated_jobs': resubmitted_or_duplicated_jobs,
        }


def get_test_result_number_for_build(build, jobs=None):
    test_numbers = qa_report.TestNumbers()

    if not jobs:
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))

    jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
    download_attachments_save_result(jobs=jobs_to_be_checked)
    for job in jobs_to_be_checked:
        numbers = get_testcases_number_for_job(job)
        test_numbers.addWithHash(numbers)

    return {
        'number_passed': test_numbers.number_passed,
        'number_failed': test_numbers.number_failed,
        'number_total': test_numbers.number_total,
        'modules_done': test_numbers.modules_done,
        'modules_total': test_numbers.modules_total,
        }

def get_lkft_build_status(build, jobs):
    if not jobs:
        jobs = qa_report_api.get_jobs_for_build(build.get("id"))

    jobs_to_be_checked = get_classified_jobs(jobs=jobs).get('final_jobs')
    last_fetched_timestamp = build.get('created_at')
    has_unsubmitted = False
    is_inprogress = False
    for job in jobs_to_be_checked:
        if not job.get('submitted'):
            has_unsubmitted = True
            break
        if job.get('fetched'):
            job_last_fetched_timestamp = qa_report_api.get_aware_datetime_from_str(job.get('fetched_at'))
            if job_last_fetched_timestamp > last_fetched_timestamp:
                last_fetched_timestamp = job_last_fetched_timestamp
        else:
            is_inprogress = True
            break

    if has_unsubmitted:
        build['build_status'] = "JOBSNOTSUBMITTED"
    elif is_inprogress:
        build['build_status'] = "JOBSINPROGRESS"
    else:
        build['build_status'] = "JOBSCOMPLETED"
        build['last_fetched_timestamp'] = last_fetched_timestamp

    return {
        'is_inprogress': is_inprogress,
        'has_unsubmitted': has_unsubmitted,
        'last_fetched_timestamp': last_fetched_timestamp,
        }


def get_project_info(project):

    logger.info("%s: Start to get qa-build information for project", project.get('name'))
    builds = qa_report_api.get_all_builds(project.get('id'), only_first=True)
    if len(builds) > 0:
        last_build = builds[0]
        last_build['created_at'] = qa_report_api.get_aware_datetime_from_str(last_build.get('created_at'))

        jobs = qa_report_api.get_jobs_for_build(last_build.get("id"))
        last_build['numbers_of_result'] = get_test_result_number_for_build(last_build, jobs)
        build_status = get_lkft_build_status(last_build, jobs)
        project['last_build'] = last_build

    logger.info("%s: Start to get ci trigger build information for project", project.get('name'))
    last_trigger_build = get_last_trigger_build(project)
    if last_trigger_build:
        last_trigger_url = last_trigger_build.get('url')
        last_trigger_build = jenkins_api.get_build_details_with_full_url(build_url=last_trigger_url)
        last_trigger_build['start_timestamp'] = qa_report_api.get_aware_datetime_from_timestamp(int(last_trigger_build['timestamp'])/1000)
        last_trigger_build['duration'] = datetime.timedelta(milliseconds=last_trigger_build['duration'])
        project['last_trigger_build'] = last_trigger_build

    logger.info("%s: Start to get ci build information for project", project.get('name'))
    ci_build_project_name = find_cibuild(project)
    if ci_build_project_name:
        ci_build_project = jenkins_api.get_build_details_with_job_url(ci_build_project_name)

        isInQueue = ci_build_project.get('inQueue')
        ci_build_last_duration = None
        ci_build_last_start_timestamp = None
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
            ci_build_last_start_timestamp = qa_report_api.get_aware_datetime_from_timestamp(int(ci_build_last['timestamp'])/1000)
            ci_build_last_duration = datetime.timedelta(milliseconds=ci_build_last['duration'])

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
            'duration': ci_build_last_duration,
            'start_timestamp': ci_build_last_start_timestamp,
        }
        project['last_ci_build'] = last_ci_build

    if project.get('last_build') and project.get('last_ci_build') and \
        project['last_build']['build_status'] == "JOBSCOMPLETED":
        last_ci_build = project.get('last_ci_build')
        last_build = project.get('last_build')
        if last_ci_build.get('start_timestamp'):
            project['duration'] = last_build.get('last_fetched_timestamp') - last_ci_build.get('start_timestamp')

    logger.info("%s: finished to get information for project", project.get('name'))


def get_projects_info(group_name=""):
    import threading
    threads = list()
    prefix_group = "%s/" % group_name

    projects = []
    for project in qa_report_api.get_projects():
        project_full_name = project.get('full_name')
        if project.get('is_archived'):
            continue
        if not project_full_name.startswith(prefix_group):
            continue

        projects.append(project)
        t = threading.Thread(target=get_project_info, args=(project,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    def get_project_name(item):
        return item.get('name')

    sorted_projects = sorted(projects, key=get_project_name)
    return sorted_projects


def list_group_projects(request, group_name="android-lkft", title_head="LKFT Projects"):
    sorted_projects = get_projects_info(group_name=group_name)

    bugs = get_lkft_bugs()
    open_bugs = []
    for bug in bugs:
        if bug.status == 'VERIFIED' or bug.status== 'RESOLVED':
            continue
        open_bugs.append(bug)

    return render(request, 'lkft-projects.html',
                           {
                                "projects": sorted_projects,
                                'open_bugs': open_bugs,
                                'group_name': group_name,
                                'title_head': title_head,
                            }
                )

@login_required
def list_rc_projects(request):
    group_name = "android-lkft-rc"
    title_head = "LKFT RC Projects"
    return list_group_projects(request, group_name=group_name, title_head=title_head)


@login_required
def list_projects(request):
    group_name = "android-lkft"
    title_head = "LKFT Projects"
    return list_group_projects(request, group_name=group_name, title_head=title_head)


@login_required
def list_builds(request):
    project_id = request.GET.get('project_id', None)
    project =  qa_report_api.get_project(project_id)
    builds = qa_report_api.get_all_builds(project_id)

    try:
        db_reportproject = ReportProject.objects.get(project_id=project_id)
    except ReportProject.DoesNotExist:
        db_reportproject = None

    number_of_build_with_jobs = 0
    builds_result = []
    for build in builds:
        number_of_build_with_jobs = number_of_build_with_jobs + 1
        if number_of_build_with_jobs > BUILD_WITH_JOBS_NUMBER:
            continue

        db_report_build = None
        if db_reportproject:
            try:
                db_report_build = ReportBuild.objects.get(version=build.get('version'), qa_project=db_reportproject)
            except ReportBuild.DoesNotExist:
                pass

        if db_report_build:
            build['numbers'] = {
                'number_passed': db_report_build.number_passed,
                'number_failed': db_report_build.number_failed,
                'number_total': db_report_build.number_total,
                'modules_done': db_report_build.modules_done,
                'modules_total': db_report_build.modules_total,
                }
            build['created_at'] = db_report_build.started_at
            build['build_status'] = db_report_build.status
        else:
            ## For cases that the build information still not cached into database yet
            build_numbers = qa_report.TestNumbers()
            jobs = qa_report_api.get_jobs_for_build(build.get("id"))
            temp_build_numbers = get_test_result_number_for_build(build, jobs)
            build_numbers.addWithHash(temp_build_numbers)
            build['created_at'] = qa_report_api.get_aware_datetime_from_str(build.get('created_at'))

            build['numbers'] = {
                                'number_passed': build_numbers.number_passed,
                                'number_failed': build_numbers.number_failed,
                                'number_total': build_numbers.number_total,
                                'modules_done': build_numbers.modules_done,
                                'modules_total': build_numbers.modules_total,
                                }
            if build.get('finished'):
                build['build_status'] = 'JOBSCOMPLETED'
            else:
                build['build_status'] = 'JOBSINPROGRESS'

        builds_result.append(build)

    return render(request, 'lkft-builds.html',
                           {
                                "builds": builds_result,
                                'project': project,
                            })


def get_lkft_bugs(summary_keyword=None, platform=None):
    bugs = []

    terms = [
                {u'product': 'Linaro Android'},
                {u'component': 'General'},
                {u'op_sys': 'Android'},
                {u'keywords': 'LKFT'}
            ]
    if platform is not None:
        terms.append({u'platform': platform})

    for bug in bugzilla_instance.search_bugs(terms).bugs:
        bug_dict = bugzilla.DotDict(bug)
        if summary_keyword is not None and \
            bug_dict.get('summary').find(summary_keyword) < 0:
            continue
        bugs.append(bug_dict)

    def get_bug_summary(item):
        return item.get('summary')

    sorted_bugs = sorted(bugs, key=get_bug_summary)
    return sorted_bugs


def find_bug_for_failure(failure, patterns=[], bugs=[]):
    found_bug = None
    for pattern in patterns:
        if found_bug is not None:
            break
        for bug in bugs:
            if pattern.search(bug.summary):
                if failure.get('bugs'):
                    failure['bugs'].append(bug)
                else:
                    failure['bugs'] = [bug]
                found_bug = bug
            if found_bug is not None:
                break

    return found_bug


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

        short_desc = "%s: %s job failed to get test result with %s" % (project_name, job.get('name'), build.get('version'))
        new_bug_url = '%s&rep_platform=%s&version=%s&short_desc=%s' % ( bugzilla_instance.get_new_bug_url_prefix(),
                                                                          get_hardware_from_pname(pname=project_name, env=job.get('environment')),
                                                                          get_version_from_pname(pname=project_name),
                                                                          short_desc)
        job['new_bug_url'] = new_bug_url

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

    bugs = get_lkft_bugs(summary_keyword=project_name, platform=get_hardware_from_pname(project_name))
    bugs_reproduced = []
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

            if test_name.find(module_name) >=0:
                # vts test, module name is the same as the test name.
                search_key = test_name
            else:
                search_key = '%s %s' % (module_name, test_name)
            search_key_exact = search_key.replace('#arm64-v8a', '').replace('#armeabi-v7a', '')

            pattern_testcase = re.compile(r'\b({0})\s+failed\b'.format(search_key_exact.replace('[', '\[').replace(']', '\]')))
            pattern_testclass = re.compile(r'\b({0})\s+failed\b'.format(failure.get('test_class').replace('[', '\[').replace(']', '\]')))
            pattern_module = re.compile(r'\b({0})\s+failed\b'.format(module_name.replace('[', '\[').replace(']', '\]')))
            patterns = [pattern_testcase, pattern_testclass, pattern_module]
            found_bug = find_bug_for_failure(failure, patterns=patterns, bugs=bugs)
            if found_bug is not None:
                bugs_reproduced.append(found_bug)

    android_version = get_version_from_pname(pname=project.get('name'))
    open_bugs = []
    bugs_not_reproduced = []
    for bug in bugs:
        if bug.status == 'VERIFIED' or (bug.status == 'RESOLVED' and bug.resolution != 'WONTFIX'):
            continue
        if bug.version != android_version:
            continue
        if bug in bugs_reproduced:
            open_bugs.append(bug)
        else:
            bugs_not_reproduced.append(bug)

    # sort failures
    for module_name, failures_in_module in failures.items():
        failures[module_name] = collections.OrderedDict(sorted(failures_in_module.items()))
    failures = collections.OrderedDict(sorted(failures.items()))

    def get_job_name(item):
        if item.get('name'):
            return item.get('name')
        else:
            return ""

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
                                'bugs_not_reproduced': bugs_not_reproduced,
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
            form_initial['summary'] = '%s: %s failed' % (project.get('name'), test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))
            description = '%s' % (test_name)
        else:
            form_initial['summary'] = '%s: %s %s failed' % (project.get('name'), module_name, test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))
            description = '%s %s' % ( module_name, test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', ''))

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
                                                             test_name.replace('#arm64-v8a', '').replace('#armeabi-v7a', '').replace('#', '.'))
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
            qa_build =  qa_report_api.get_build(build_id)
            qa_project =  qa_report_api.get_project_with_url(qa_build.get('project'))

            try:
                db_reportproject = ReportProject.objects.get(project_id=qa_project.get('id'))
                db_report_build = ReportBuild.objects.get(version=qa_build.get('version'), qa_project=db_reportproject)
                db_report_build.status = 'JOBSINPROGRESS'
                db_report_build.save()

                db_report_build.kernel_change.reported = False
                db_report_build.kernel_change.save()

            except ReportProject.DoesNotExist:
                logger.info("db_reportproject not found for project_id=%s" % qa_project.get('id'))
                pass
            except ReportBuild.DoesNotExist:
                logger.info("db_report_build not found for project_id=%s, version=%s" % (qa_project.get('id'), qa_build.get('version')))
                pass
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


def new_kernel_changes(request, branch, describe, trigger_name, trigger_number):

    remote_addr = request.META.get("REMOTE_ADDR")
    remote_host = request.META.get("REMOTE_HOST")
    logger.info('request from remote_host=%s,remote_addr=%s' % (remote_host, remote_addr))
    logger.info('request for branch=%s, describe=%s, trigger_name=%s, trigger_number=%s' % (branch, describe, trigger_name, trigger_number))

    irc.send("New kernel changes found: branch=%s, describe=%s, %s" % (branch, describe, "https://ci.linaro.org/job/%s/%s" % (trigger_name, trigger_number)))

    err_msg = None
    try:
        KernelChange.objects.get(branch=branch, describe=describe)
        err_msg = 'request for branch=%s, describe=%s is already there' % (branch, describe)
        logger.info(err_msg)
    except KernelChange.DoesNotExist:
        kernel_change = KernelChange.objects.create(branch=branch,
                                    describe=describe,
                                    reported=False,
                                    trigger_name=trigger_name,
                                    trigger_number=trigger_number)
        CiBuild.objects.create(name=trigger_name,
                                number=trigger_number,
                                kernel_change=kernel_change)


    if err_msg is None:
        return HttpResponse(status=200)
    else:
        return HttpResponse("ERROR:%s" % err_msg,
                            status=200)


def new_build(request, branch, describe, name, number):
    remote_addr = request.META.get("REMOTE_ADDR")
    remote_host = request.META.get("REMOTE_HOST")
    logger.info('request from %s %s' % (remote_host, remote_addr))
    logger.info('request for branch=%s, describe=%s, trigger_name=%s, trigger_number=%s' % (branch, describe, name, number))

    err_msg = None
    try:
        kernel_change = KernelChange.objects.get(branch=branch, describe=describe)

        try:
            CiBuild.objects.get(name=name, number=number)
            err_msg = "The build already recorded: name=%s, number=%s" % (name, number)
            logger.info(err_msg)
        except CiBuild.DoesNotExist:
            CiBuild.objects.create(name=name,
                                    number=number,
                                    kernel_change=kernel_change)
            kernel_change.reported = False
            kernel_change.save()

    except KernelChange.DoesNotExist:
        err_msg = "The change for the specified kernel and describe does not exist: branch=%s, describe=%s" % (branch, describe)
        logger.info(err_msg)

    if err_msg is None:
        return HttpResponse(status=200)
    else:
        return HttpResponse("ERROR:%s" % err_msg,
                            status=200)


def get_ci_build_info(build_name, build_number):
    ci_build_url = jenkins_api.get_job_url(name=build_name, number=build_number)
    try:
        ci_build = jenkins_api.get_build_details_with_full_url(build_url=ci_build_url)
        ci_build['start_timestamp'] = qa_report_api.get_aware_datetime_from_timestamp(int(ci_build['timestamp'])/1000)
        kernel_change_start_timestamp = ci_build['start_timestamp']

        if ci_build.get('building'):
            ci_build['status'] = 'INPROGRESS'
            ci_build['duration'] = datetime.timedelta(milliseconds=0)
        else:
            ci_build['status']  = ci_build.get('result') # null or SUCCESS, FAILURE, ABORTED
            ci_build['duration'] = datetime.timedelta(milliseconds=ci_build['duration'])
        ci_build['finished_timestamp'] = ci_build['start_timestamp'] + ci_build['duration']

    except qa_report.UrlNotFoundException as e:
        ci_build = {
                'number': build_number,
                'status': 'CI_BUILD_DELETED',
                'duration': datetime.timedelta(milliseconds=0),
                'actions': [],
            }

    ci_build['name'] = build_name
    return ci_build


def get_qareport_build(build_version, qaproject_name, cached_qaprojects=[], cached_qareport_builds=[]):
    target_qareport_project = None
    for lkft_project in cached_qaprojects:
        if lkft_project.get('full_name') == qaproject_name:
            target_qareport_project = lkft_project
            break
    if target_qareport_project is None:
        return (None, None)


    target_qareport_project_id = target_qareport_project.get('id')
    builds = cached_qareport_builds.get(target_qareport_project_id)
    if builds is None:
        builds = qa_report_api.get_all_builds(target_qareport_project_id)
        cached_qareport_builds[target_qareport_project_id] = builds

    target_qareport_build = None
    for build in builds:
        if build.get('version') == build_version:
            target_qareport_build = build
            break

    return (target_qareport_project, target_qareport_build)


def get_kernel_changes_info(db_kernelchanges=[]):
    queued_ci_items = jenkins_api.get_queued_items()
    lkft_projects = qa_report_api.get_lkft_qa_report_projects()
    kernelchanges = []
    # add the same project might have several kernel changes not finished yet
    project_builds = {} # cache builds for the project

    number_kernelchanges = len(db_kernelchanges)
    index = 0
    logger.info("length of kernel changes: %s" % number_kernelchanges)
    for db_kernelchange in db_kernelchanges:
        index = index +1
        logger.info("%d/%d: Try to get info for kernel change: %s %s %s %s" % (index, number_kernelchanges, db_kernelchange.branch, db_kernelchange.describe, db_kernelchange.result, timesince(db_kernelchange.timestamp)))
        test_numbers = qa_report.TestNumbers()
        kernelchange = {}
        if db_kernelchange.reported and db_kernelchange.result == 'ALL_COMPLETED':
            kernelchange['branch'] = db_kernelchange.branch
            kernelchange['describe'] = db_kernelchange.describe
            kernelchange['trigger_name'] = db_kernelchange.trigger_name
            kernelchange['trigger_number'] = db_kernelchange.trigger_number
            kernelchange['start_timestamp'] = db_kernelchange.timestamp
            kernelchange['finished_timestamp'] = None
            kernelchange['duration'] = datetime.timedelta(seconds=db_kernelchange.duration)
            kernelchange['status'] = db_kernelchange.result
            kernelchange['number_passed'] = db_kernelchange.number_passed
            kernelchange['number_failed'] = db_kernelchange.number_failed
            kernelchange['number_total'] = db_kernelchange.number_total
            kernelchange['modules_done'] = db_kernelchange.modules_done
            kernelchange['modules_total'] = db_kernelchange.modules_total
            kernelchanges.append(kernelchange)
            continue

        trigger_build = get_ci_build_info(db_kernelchange.trigger_name, db_kernelchange.trigger_number)
        trigger_build['kernel_change'] = db_kernelchange
        if trigger_build.get('start_timestamp') is None:
            trigger_build['start_timestamp'] = db_kernelchange.timestamp
            trigger_build['finished_timestamp'] = trigger_build['start_timestamp'] + trigger_build['duration']
            kernel_change_status = "TRIGGER_BUILD_DELETED"
        else:
            kernel_change_status = "TRIGGER_BUILD_COMPLETED"
        kernel_change_start_timestamp = trigger_build['start_timestamp']
        kernel_change_finished_timestamp = trigger_build['finished_timestamp']

        dbci_builds = CiBuild.objects_kernel_change.get_builds_per_kernel_change(kernel_change=db_kernelchange).order_by('name', '-number')
        expect_build_names = find_expect_cibuilds(trigger_name=db_kernelchange.trigger_name, branch_name=db_kernelchange.branch)

        # used to cached all the ci builds data
        jenkins_ci_builds = []
        # used to record the lkft build config to find the qa-report project
        lkft_build_configs = {}
        ci_build_names = []
        has_build_inprogress = False
        for dbci_build in dbci_builds:
            #if dbci_build.name == db_kernelchange.trigger_name:
            #    # ignore the trigger builds
            #    continue
            #else:
            ci_build_names.append(dbci_build.name)

            build = get_ci_build_info(dbci_build.name, dbci_build.number)
            build['dbci_build'] = dbci_build
            jenkins_ci_builds.append(build)
            if build.get('status') == 'INPROGRESS':
                has_build_inprogress = True

            if build.get('status') != 'SUCCESS':
                # no need to check the build/job results as the ci build not finished successfully yet
                # and the qa-report build is not created yet
                continue

            configs = get_configs(ci_build=build)
            for lkft_build_config, ci_build in configs:
                if lkft_build_config.startswith('lkft-gki-'):
                    # gki builds does not have any qa-preoject set
                    continue
                if lkft_build_configs.get(lkft_build_config) is not None:
                    # only use the latest build(which might be triggered manually) for the same kernel change
                    # even for the generic build that used the same lkft_build_config.
                    # used the "-number" filter to make sure ci builds is sorted in descending,
                    # and the first one is the latest
                    continue

                    lkft_build_configs[lkft_build_config] = ci_build

        not_started_ci_builds = expect_build_names - set(ci_build_names)

        # need to check how to find the builds not started or failed
        queued_ci_builds = []
        disabled_ci_builds = []
        not_reported_ci_builds = []
        if len(not_started_ci_builds) > 0:
            for cibuild_name in not_started_ci_builds:
                is_queued_build = False
                for queued_item in queued_ci_items:
                    if cibuild_name == queued_item.get('build_name') and \
                        db_kernelchange.describe == queued_item.get('KERNEL_DESCRIBE'):
                            is_queued_build = True
                            queued_ci_builds.append(queued_item)
                if is_queued_build:
                    continue

                if jenkins_api.is_build_disabled(cibuild_name):
                    disabled_ci_builds.append(cibuild_name)
                #else:
                #    not_reported_ci_builds.append(cibuild_name)

        if queued_ci_builds:
            kernel_change_status = "CI_BUILDS_IN_QUEUE"
        elif not_reported_ci_builds:
            kernel_change_status = "CI_BUILDS_NOT_REPORTED"
            logger.info("NOT REPORTED BUILDS: %s" % ' '.join(not_reported_ci_builds))
        elif has_build_inprogress:
            kernel_change_status = "CI_BUILDS_IN_PROGRESS"
        else:
            kernel_change_status = "CI_BUILDS_COMPLETED"

        qa_report_builds = []
        has_jobs_not_submitted = False
        has_jobs_in_progress = False
        all_jobs_finished = False

        qareport_project_not_found_configs = []
        qareport_build_not_found_configs = []
        for lkft_build_config, ci_build in lkft_build_configs.items():
            (project_group, project_name) = get_qa_server_project(lkft_build_config_name=lkft_build_config)
            target_lkft_project_full_name = "%s/%s" % (project_group, project_name)
            (target_qareport_project, target_qareport_build) = get_qareport_build(db_kernelchange.describe,
                                                                    target_lkft_project_full_name,
                                                                    cached_qaprojects=lkft_projects,
                                                                    cached_qareport_builds=project_builds)
            if target_qareport_project is None:
                qareport_project_not_found_configs.append(lkft_build_config)
                continue

            if target_qareport_build is None:
                qareport_build_not_found_configs.append(lkft_build_config)
                continue

            created_str = target_qareport_build.get('created_at')
            target_qareport_build['created_at'] = qa_report_api.get_aware_datetime_from_str(created_str)
            target_qareport_build['project_name'] = project_name
            target_qareport_build['project_group'] = project_group
            target_qareport_build['project_slug'] = target_qareport_project.get('slug')
            target_qareport_build['project_id'] = target_qareport_project.get('id')

            jobs = qa_report_api.get_jobs_for_build(target_qareport_build.get("id"))
            classified_jobs = get_classified_jobs(jobs=jobs)
            final_jobs = classified_jobs.get('final_jobs')
            resubmitted_or_duplicated_jobs = classified_jobs.get('resubmitted_or_duplicated_jobs')

            build_status = get_lkft_build_status(target_qareport_build, final_jobs)
            if build_status['has_unsubmitted']:
                has_jobs_not_submitted = True
            elif build_status['is_inprogress']:
                has_jobs_in_progress = True
            else:
                if kernel_change_finished_timestamp is None or \
                    kernel_change_finished_timestamp < build_status['last_fetched_timestamp']:
                    kernel_change_finished_timestamp = build_status['last_fetched_timestamp']
                target_qareport_build['duration'] = build_status['last_fetched_timestamp'] - target_qareport_build['created_at']

            numbers_of_result = get_test_result_number_for_build(target_qareport_build, final_jobs)
            target_qareport_build['numbers_of_result'] = numbers_of_result
            target_qareport_build['qa_report_project'] = target_qareport_project
            target_qareport_build['final_jobs'] = final_jobs
            target_qareport_build['resubmitted_or_duplicated_jobs'] = resubmitted_or_duplicated_jobs
            target_qareport_build['ci_build'] = ci_build
            qa_report_builds.append(target_qareport_build)

            test_numbers.addWithHash(numbers_of_result)

        has_error = False
        error_dict = {}
        if kernel_change_status == "CI_BUILDS_COMPLETED":
            if qareport_project_not_found_configs or qareport_build_not_found_configs:
                has_error = True
                if qareport_project_not_found_configs:
                    kernel_change_status = 'HAS_QA_PROJECT_NOT_FOUND'
                    error_dict['qareport_project_not_found_configs'] = qareport_project_not_found_configs
                    logger.info("qareport_build_not_found_configs: %s" % ' '.join(qareport_build_not_found_configs))
                if qareport_build_not_found_configs:
                    kernel_change_status = 'HAS_QA_BUILD_NOT_FOUND'
                    error_dict['qareport_build_not_found_configs'] = qareport_build_not_found_configs
                    logger.info("qareport_build_not_found_configs: %s" % ' '.join(qareport_build_not_found_configs))
            elif has_jobs_not_submitted:
                kernel_change_status = 'HAS_JOBS_NOT_SUBMITTED'
            elif has_jobs_in_progress:
                kernel_change_status = 'HAS_JOBS_IN_PROGRESS'
            else:
                kernel_change_status = 'ALL_COMPLETED'

        kernelchange['branch'] = db_kernelchange.branch
        kernelchange['describe'] = db_kernelchange.describe
        kernelchange['trigger_name'] = db_kernelchange.trigger_name
        kernelchange['trigger_number'] = db_kernelchange.trigger_number
        kernelchange['start_timestamp'] = kernel_change_start_timestamp
        kernelchange['finished_timestamp'] = kernel_change_finished_timestamp
        kernelchange['duration'] = kernelchange['finished_timestamp'] - kernelchange['start_timestamp']
        kernelchange['status'] = kernel_change_status
        kernelchange['number_passed'] = test_numbers.number_passed
        kernelchange['number_failed'] = test_numbers.number_failed
        kernelchange['number_total'] = test_numbers.number_total
        kernelchange['modules_done'] = test_numbers.modules_done
        kernelchange['modules_total'] = test_numbers.modules_total

        kernelchanges.append(kernelchange)

    return kernelchanges


def get_kernel_changes_for_all_branches():
    db_kernelchanges = KernelChange.objects.all().order_by('branch', '-trigger_number')
    check_branches = []
    unique_branch_names = []
    for db_kernelchange in db_kernelchanges:
        if db_kernelchange.branch in unique_branch_names:
            continue
        else:
            unique_branch_names.append(db_kernelchange.branch)
            check_branches.append(db_kernelchange)

    return get_kernel_changes_info(db_kernelchanges=check_branches)


@login_required
def list_kernel_changes(request):
    kernelchanges = get_kernel_changes_for_all_branches()
    return render(request, 'lkft-kernelchanges.html',
                       {
                            "kernelchanges": kernelchanges,
                        }
            )

@login_required
def list_branch_kernel_changes(request, branch):
    db_kernelchanges = KernelChange.objects.all().filter(branch=branch).order_by('-trigger_number')
    kernelchanges = get_kernel_changes_info(db_kernelchanges=db_kernelchanges)

    return render(request, 'lkft-kernelchanges.html',
                       {
                            "kernelchanges": kernelchanges,
                        }
            )
@login_required
def list_describe_kernel_changes(request, branch, describe):
    db_kernel_change = KernelChange.objects.get(branch=branch, describe=describe)
    db_report_builds = ReportBuild.objects.filter(kernel_change=db_kernel_change).order_by('qa_project__group', 'qa_project__name')
    db_ci_builds = CiBuild.objects.filter(kernel_change=db_kernel_change).exclude(name=db_kernel_change.trigger_name).order_by('name', 'number')
    db_trigger_build = CiBuild.objects.get(name=db_kernel_change.trigger_name, kernel_change=db_kernel_change)

    kernel_change = {}
    kernel_change['branch'] = db_kernel_change.branch
    kernel_change['describe'] = db_kernel_change.describe
    kernel_change['result'] = db_kernel_change.result
    kernel_change['trigger_name'] = db_kernel_change.trigger_name
    kernel_change['trigger_number'] = db_kernel_change.trigger_number
    kernel_change['timestamp'] = db_kernel_change.timestamp
    kernel_change['duration'] = datetime.timedelta(seconds=db_kernel_change.duration)
    kernel_change['number_passed'] = db_kernel_change.number_passed
    kernel_change['number_failed'] = db_kernel_change.number_failed
    kernel_change['number_total'] = db_kernel_change.number_total
    kernel_change['modules_done'] = db_kernel_change.modules_done
    kernel_change['modules_total'] = db_kernel_change.modules_total

    trigger_build = {}
    trigger_build['name'] = db_trigger_build.name
    trigger_build['number'] = db_trigger_build.number
    trigger_build['timestamp'] = db_trigger_build.timestamp
    trigger_build['result'] = db_trigger_build.result
    trigger_build['duration'] = datetime.timedelta(seconds=db_trigger_build.duration)

    ci_builds = []
    for db_ci_build in db_ci_builds:
        ci_build = {}
        ci_build['name'] = db_ci_build.name
        ci_build['number'] = db_ci_build.number
        ci_build['timestamp'] = db_ci_build.timestamp
        ci_build['result'] = db_ci_build.result
        ci_build['duration'] = datetime.timedelta(seconds=db_ci_build.duration)
        if db_ci_build.timestamp and db_trigger_build.timestamp:
            ci_build['queued_duration'] = db_ci_build.timestamp - db_trigger_build.timestamp  - trigger_build['duration']
        ci_builds.append(ci_build)

    report_builds = []
    for db_report_build in db_report_builds:
        report_build = {}
        report_build['qa_project'] = db_report_build.qa_project
        report_build['started_at'] = db_report_build.started_at
        report_build['number_passed'] = db_report_build.number_passed
        report_build['number_failed'] = db_report_build.number_failed
        report_build['number_total'] = db_report_build.number_total
        report_build['modules_done'] = db_report_build.modules_done
        report_build['modules_total'] = db_report_build.modules_total
        report_build['qa_build_id'] = db_report_build.qa_build_id
        report_build['status'] = db_report_build.status
        if db_report_build.fetched_at and db_report_build.started_at:
            report_build['duration'] = db_report_build.fetched_at - db_report_build.started_at

        report_builds.append(report_build)

    return render(request, 'lkft-describe.html',
                       {
                            "kernel_change": kernel_change,
                            'report_builds': report_builds,
                            'trigger_build': trigger_build,
                            'ci_builds': ci_builds,
                        }
            )

########################################
### Register for IRC functions
########################################
def func_irc_list_kernel_changes(irc=None, text=None):
    if irc is None:
        return
    kernelchanges = get_kernel_changes_for_all_branches()
    ircMsgs = []
    for kernelchange in kernelchanges:
        irc_msg = "branch:%s, describe=%s, %s, modules_done=%s" % (kernelchange.get('branch'),
                        kernelchange.get('describe'),
                        kernelchange.get('status'),
                        kernelchange.get('modules_done'))
        ircMsgs.append(irc_msg)

    irc.send(ircMsgs)

irc_notify_funcs = {
    'listkernelchanges': func_irc_list_kernel_changes,
}

irc.addFunctions(irc_notify_funcs)

########################################
########################################
