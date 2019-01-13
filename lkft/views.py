# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django import forms
from django.shortcuts import render

import bugzilla
import collections
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
import yaml
import zipfile

from lcr.settings import FILES_DIR, LAVA_SERVERS, BUGZILLA_API_KEY

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
    for nick, config in LAVA_SERVERS.items():
        if job_url.find('://%s/' % config.get('hostname')) >= 0:
            return config
    return None

class DotDict(dict):
    '''dict.item notation for dict()'s'''
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def download_urllib(url, path):
    import urllib
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
    urllib.urlretrieve(url, path, Schedule)
    logger.info("File is saved to %s" % path)


def get_attachment_urls(jobs=[]):
    for job in jobs:
        lava_config = job.get('lava_config')
        if not lava_config :
            lava_config = find_lava_config(job.get('external_url'))
            if not lava_config:
                logger.error('lava server is not found for job: %s' % job.get('external_url'))
                return None
            else:
                job['lava_config'] = lava_config
        lava_server = lava_config.get('server')
        job_id = job.get('job_id')

        # something need to be cached here when the attachment already there
        res = lava_server.results.get_testjob_suites_list_yaml(job_id)
        for test_suite in yaml.load(res):
            if test_suite['name'] == "lava":
                continue
            if test_suite['name'].find("install-android-platform-tools") >= 0:
                continue
            if test_suite['name'].find("android-boot") >= 0:
                continue
            if test_suite['name'].find("boottime") >= 0:
                continue

            # suite_name = '1_cts-f ocused1-arm64-v8a'
            suite_name = test_suite['name']
            case_name = 'test-attachment'
            res = yaml.load(lava_server.results.get_testcase_results_yaml(job_id, suite_name, case_name))
            attachment_url = res[0].get('metadata').get('reference')
            if attachment_url:
                job['attachment_url'] = attachment_url
            else:
                logger.info("No attachment for job: %s" % (job_url))

def extract_save_result(tar_path, result_zip_path):
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
    lava_nick = job.get('lava_config').get('nick')
    job_id = job.get('job_id')
    result_file_path = os.path.join(DIR_ATTACHMENTS, "%s-%s.zip" % (lava_nick, job_id))
    return result_file_path

def download_attachments_save_result(jobs=[]):
    # https://lkft.validation.linaro.org/scheduler/job/566144
    get_attachment_urls(jobs=jobs)
    for job in jobs:
        lava_nick = job.get('lava_config').get('nick')
        job_id = job.get('job_id')
        job_url = job.get('external_url')
        result_file_path = get_result_file_path(job)
        if not os.path.exists(result_file_path):
            attachment_url = job.get('attachment_url')
            if not attachment_url:
                logger.info("No attachment for job: %s" % job_url)
                continue

            (temp_fd, temp_path) = tempfile.mkstemp(suffix='.tar.xz', text=False)
            logger.info("Start downloading result file for job %s: %s" % (job_url, temp_path))
            download_urllib(attachment_url, temp_path)
            tar_f = temp_path.replace(".xz", '')
            os.system("xz -d %s" % temp_path)
            extract_save_result(tar_f, result_file_path)
            os.unlink(tar_f)


def extract(result_zip_path, failed_testcases_all={}, metadata={}):
    kernel_version = metadata.get('kernel_version')
    qa_job_id = metadata.get('qa_job_id')

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

                            if not qa_job_id in failed_testcase.get('qa_job_ids'):
                                failed_testcase.get('qa_job_ids').append(qa_job_id)

                            if not kernel_version in failed_testcase.get('kernel_versions'):
                                failed_testcase.get('kernel_versions').append(kernel_version)
                        else:
                            failed_tests_module[test_name]= {
                                                                'test_name': test_name,
                                                                'module_name': module_name,
                                                                'abi_stacktrace': {abi: stacktrace},
                                                                'qa_job_ids': [ qa_job_id ],
                                                                'kernel_versions': [ kernel_version ],
                                                            }
        except ET.ParseError as e:
            logger.error('xml.etree.ElementTree.ParseError: %s' % e)
            logger.info('Please Check %s manually' % result_zip_path)


qa_report_api_url = 'https://qa-reports.linaro.org/'
def qa_report_get(api_url=''):
    local_api_url = api_url.strip('/')
    request_url = '%s/%s/?format=json' % (qa_report_api_url, local_api_url)
    return qa_report_get_with_full_api(request_url=request_url)

def qa_report_get_with_full_api(request_url=''):
    headers = {'Content-Type': 'application/json'}
    r = requests.get(request_url, headers=headers)
    ret = DotDict(r.json())
    if (not r.ok or ('error' in ret and ret.error == True)):
        raise Exception(r.url, r.reason, r.status_code, r.json())
    return ret


def list_projects(request):
    # https://qa-reports.linaro.org/api/projects/
    api_url = "/api/projects/"
    projects = []
    for project in qa_report_get(api_url=api_url).get('results'):
        project_full_name = project.get('full_name')
        if project_full_name.startswith('android-lkft/'):
            projects.append(project)

    bugs = get_lkft_bugs()
    open_bugs = []
    for bug in bugs:
        if bug.status== 'VERIFIED' or bug.status== 'RESOLVED':
            continue
        else:
            open_bugs.append(bug)
    return render(request, 'lkft-projects.html',
                           {
                                "projects": projects,
                                'open_bugs': open_bugs,
                            }
                )

def list_builds(request):
    project_id = request.GET.get('project_id', None)
    project_api_url = 'api/projects/%s' % project_id
    project =  qa_report_get(api_url=project_api_url)
    

    builds_api_url = "api/projects/%s/builds" % project_id
    builds = qa_report_get(api_url=builds_api_url).get('results')
    return render(request, 'lkft-builds.html',
                           {
                                "builds": builds,
                                'project': project,
                            }
                )

def get_lkft_bugs():
    bugs = []

    terms = [
                {u'product': 'Linaro Android'},
                {u'component': 'General'},
                {u'platform': 'HiKey'},
                {u'op_sys': 'Android'},
                #{u'version': get_bug_version_from_build_name(build_name)},
                {u'keywords': 'LKFT'}
            ]

    for bug in bugzilla_instance.search_bugs(terms).bugs:
        bugs.append(bugzilla.DotDict(bug))

    def get_bug_summary(item):
        return item.get('summary')

    sorted_bugs = sorted(bugs, key=get_bug_summary)
    return sorted_bugs

def list_jobs(request):
    build_id = request.GET.get('build_id', None)

    build_api_url = 'api/builds/%s' % build_id
    build =  qa_report_get(api_url=build_api_url)

    project_api_url = build.get('project')
    project =  qa_report_get_with_full_api(request_url=project_api_url)

    api_url = "api/builds/%s/testjobs" % build_id
    jobs = qa_report_get(api_url=api_url).get('results')

    project_kernel_version = None
    if project.get('name').startswith('android-hikey-linaro-') or project.get('name').startswith('android-x15-linux-'):
        project_kernel_version = project.get('name').split('-')[3]
    else:
        # aosp-master-tracking and aosp-8.1-tracking
        pass

    download_attachments_save_result(jobs=jobs)
    failures = {}
    for job in jobs:
        result_file_path = get_result_file_path(job=job)
        if not os.path.exists(result_file_path):
            continue
        if project_kernel_version is None:
            environment = job.get('environment')
            if environment.startswith('hi6220-hikey_'):
                kernel_version = environment.replace('hi6220-hikey_', '')
            else:
                # impossible path for hikey
                pass
        else:
            kernel_version = project_kernel_version

        metadata = {
            'job_id': job.get('job_id'),
            'qa_job_id': job.get('url').replace('/?format=json', '').split('/')[-1],
            'result_url': job.get('attachment_url'),
            'lava_nick': job.get('lava_config').get('nick'),
            'kernel_version': kernel_version,
            }
        extract(result_file_path, failed_testcases_all=failures, metadata=metadata)


    bugs = get_lkft_bugs()
    failures_list = []
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


    open_bugs = []
    for bug in bugs:
        if bug.status== 'VERIFIED' or bug.status== 'RESOLVED':
            continue
        else:
            open_bugs.append(bug)

    # sort failures
    for module_name, failures_in_module in failures.items():
        failures[module_name] = collections.OrderedDict(sorted(failures_in_module.items()))
    failures = collections.OrderedDict(sorted(failures.items()))

    return render(request, 'lkft-jobs.html',
                           {
                                "jobs": jobs,
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

def get_bug_android_version_from_project_name(project_name=None):
    if project_name.endswith('android-9.0'):
        # android-hikey-linaro-4.14-android-9.0
        return 'PIE-9.0'
    elif project_name.endswith('android-8.1'):
        return 'OREO-8.1'
    elif project_name.find('aosp') >=0:
        # exception of the aosp premerge ci builds, might need to fix when it is changed to use pie based builds
        return 'Master'

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

            submit_result = True
            return render(request, 'lkft-file-bug.html',
                          {
                            "submit_result": submit_result,
                            'bugzilla_show_bug_prefix': bugzilla_show_bug_prefix,
                            'bug_id': bug_id,
                            'form': 'form'
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
                job_api_url = 'api/testjobs/%s' % qa_job_id
                qa_job =  qa_report_get(api_url=job_api_url)
                if qa_job is not None:
                    qa_jobs.append(qa_job)
                if target_build is None:
                    target_build = qa_job.get('target_build')
                elif target_build != qa_job.get('target_build'):
                    # need to make sure all the jobs are belong to the same build
                    # otherwise there is no meaning to list failures from jobs belong to different builds
                    # TODO : report error on webpage
                    logger.error("The jobs are belong to different builds: %s" % (qa_job_ids_str))

        project_api_url = qa_jobs[0].get('target')
        project = qa_report_get_with_full_api(request_url=project_api_url)
        build_api_url = qa_jobs[0].get('target_build')
        build = qa_report_get_with_full_api(request_url=build_api_url)

        build_meta_api_url = build.get('metadata')
        build_meta = qa_report_get_with_full_api(request_url=build_meta_api_url)

        # download all the necessary attachments
        download_attachments_save_result(jobs=qa_jobs)


        form_initial = {
                        "project_name": project.get('name'),
                        "project_id": project.get('id'),
                        'build_version': build.get('version'),
                        'build_id': build.get('id'),
                        'product': 'Linaro Android',
                        'component': 'General',
                        'severity': 'normal',
                        'os': 'Android',
                        'hardware': get_bug_hardware_from_environment(qa_jobs[0].get('environment')),
                        'keywords': 'LKFT',
                        'version': get_bug_android_version_from_project_name(project.get('name')),
                        }

        if test_name.find(module_name) >=0:
            form_initial['summary'] = '%s' % (test_name)
            description = '%s' % (test_name)
        else:
            form_initial['summary'] = '%s %s' % (module_name, test_name)
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
        for qa_job in qa_jobs:
            lava_job_id = qa_job.get('job_id')
            lava_url = qa_job.get('external_url')
            lava_config = find_lava_config(lava_url)
            result_file_path = get_result_file_path(qa_job)
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

        description += '\n\nABIs:\n%s' % (' '.join(abis))
        description += '\n\nStackTrace: \n%s' % (stacktrace_msg.strip())
        description += '\n\nLava Job:'
        for qa_job in qa_jobs:
            description += '\n%s' % (qa_job.get('external_url'))

        description += '\n\nResult File Url:'
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