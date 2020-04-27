# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import logging
import requests

from abc import abstractmethod

logger = logging.getLogger(__name__)

class DotDict(dict):
    '''dict.item notation for dict()'s'''
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

class UrlNotFoundException(Exception):
    '''
        Specific Expection for UrlNotFound Error
    '''
    response = None

    def __init__(self, response):
        self.response = response


class ParameterInvalidException(Exception):
    """
    Exception when wrong Parameters passed
    """
    pass


class RESTFullApi():
    def __init__(self, domain, api_token):
        self.domain = domain
        self.api_token = api_token

    def call_with_full_url(self, request_url='', method='GET', returnResponse=False, post_data=None):
        headers = {
                'Content-Type': 'application/json',
                }
        if self.api_token:
            headers['Authorization'] = 'Token %s' % self.api_token
            headers['Auth-Token'] = self.api_token

        if method == 'GET':
            r = requests.get(request_url, headers=headers)
        else:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            r = requests.post(request_url, headers=headers, data=post_data)

        if returnResponse:
            return r

        if not r.ok and r.status_code == 404:
            raise UrlNotFoundException(r)
        elif not r.ok or r.status_code != 200:
            raise Exception(r.url, r.reason, r.status_code)

        if r.content:
            ret = DotDict(r.json())
            return ret
        else:
            return r

    def call_with_api_url(self, api_url='', method='GET', returnResponse=False, post_data=None):
        full_url = '%s/%s' % (self.get_api_url_prefix().strip('/'), api_url.strip('/'))
        return self.call_with_full_url(request_url=full_url, method=method, returnResponse=returnResponse, post_data=post_data)

    def get_list_results(self, api_url='', only_first=False):
        result = self.call_with_api_url(api_url=api_url)
        list_results = result.get('results')
        if not only_first:
            next_url = result.get('next')
            while next_url:
                result = self.call_with_full_url(request_url=next_url)
                next_url = result.get('next')
                list_results.extend(result.get('results'))
        return list_results

    @abstractmethod
    def get_api_url_prefix(sefl):
        """Return the url prefix, which we could use with the api url directly"""
        """Should never be called."""
        raise NotImplementedError('%s.get_api_url_prefix should never be called directly' % self.__class__.__name__)


class JenkinsApi(RESTFullApi):
    def get_api_url_prefix(self, detail_url):
        # https://ci.linaro.org/job/trigger-lkft-aosp-mainline/api/json
        return 'https://%s/job/%s/api/json/' % (self.domain, detail_url)

    def get_last_build(self, cijob_name=''):
        if not cijob_name:
            return None
        full_url = self.get_api_url_prefix(detail_url=cijob_name)
        result = self.call_with_full_url(request_url=full_url)
        if result:
            return result.get('lastBuild')
        else:
            return None

    def is_build_disabled(self, cibuild_name):
        build_details = self.get_build_details_with_cibuild_name(cibuild_name)
        return not build_details.get('buildable')

    def get_build_details_with_cibuild_name(self, cibuild_name):
        full_api_url = self.get_api_url_prefix(detail_url=cibuild_name)
        return self.call_with_full_url(request_url=full_api_url)

    def get_build_details_with_job_url(self, job_url):
        full_api_url = self.get_api_url_prefix(detail_url=job_url)
        return self.call_with_full_url(request_url=full_api_url)

    def get_build_details_with_full_url(self, build_url):
        full_api_url = '%s/api/json/' % build_url
        return self.call_with_full_url(request_url=full_api_url)

    def get_job_url(self, name=None, number=None):
        if name is None:
            return "https://%s" % (self.domain)
        elif number is None:
            return "https://%s/job/%s/" % (self.domain, name)
        else:
            return "https://%s/job/%s/%s/" % (self.domain, name, number)

    def get_queued_items(self):
        # https://ci.linaro.org/queue/api/json?pretty=true
        queue_api = 'https://%s/queue/api/json/' % (self.domain)
        result = self.call_with_full_url(request_url=queue_api)
        if result:
            queued_items = result.get('items')
            items_tobe_returned = []
            for item in queued_items:
                cibuild_name = item.get('task').get('name')
                if not cibuild_name.startswith('lkft-'):
                    continue
                params_list = item.get('params').strip().split('\n')
                params_dict = {}
                for key_val_str in params_list:
                    (key, value) = key_val_str.split('=')
                    if key is not None:
                        params_dict[key] = value
                if not params_dict.get('KERNEL_DESCRIBE'):
                    continue
                item['KERNEL_DESCRIBE'] = params_dict.get('KERNEL_DESCRIBE')
                item['build_name'] = cibuild_name
                items_tobe_returned.append(item)

            return items_tobe_returned
        else:
            return []


class LAVAApi(RESTFullApi):
    def get_api_url_prefix(self):
        return 'https://%s/api/v0.1/' % self.domain


    def get_job(self, job_id=None):
        api_url = "/jobs/%s" % job_id
        return self.call_with_api_url(api_url=api_url)


class QAReportApi(RESTFullApi):
    def get_api_url_prefix(self):
        if self.domain.startswith('http'):
            return '%s/' % self.domain.strip('/')
        else:
            return 'https://%s/' % self.domain.strip('/')


    def get_projects(self):
        api_url = "/api/projects/"
        return self.get_list_results(api_url=api_url)


    def get_project(self, project_id):
        api_url = "/api/projects/%s" % project_id
        return self.call_with_api_url(api_url=api_url)


    def get_project_with_url(self, project_url):
        return self.call_with_full_url(request_url=project_url)


    def get_all_builds(self, project_id, only_first=False):
        builds_api_url = "api/projects/%s/builds" % project_id
        return self.get_list_results(api_url=builds_api_url, only_first=only_first)


    def get_build(self, build_id):
        builds_api_url = "api/builds/%s" % build_id
        return self.call_with_api_url(api_url=builds_api_url)


    def get_build_with_url(self, build_url):
        return self.call_with_full_url(request_url=build_url)


    def get_build_with_version(self, build_version, project_id):
        for build in self.get_all_builds(project_id):
            if build.get('version') == build_version:
                return build
        return None


    def get_jobs_for_build(self, build_id):
        api_url = "api/builds/%s/testjobs" % build_id
        return self.get_list_results(api_url=api_url)


    def get_project_with_name(self, project_name):
        for project in self.get_projects():
            if project.get('full_name') == project_name:
                return project
        return None


    def get_builds_with_project_name(self, project_name):
        qa_report_project = self.get_project_with_name(project_name)
        if not qa_report_project:
            logger.info("qa report project for build %s not found" % project_name)
            return []
        return self.get_all_builds(qa_report_project.get('id'))


    def get_jobs_with_project_name_build_version(self, project_name, build_version):
        qa_report_project = self.get_project_with_name(project_name)
        if not qa_report_project:
            logger.info("qa report project for build %s not found" % project_name)
            return []
        build = self.get_build_with_version(build_version, qa_report_project.get('id'))
        if not build:
            logger.info("qa report build for project(%s) with build no(%s) not found" % (project_name, build_version))
            return []
        return self.get_jobs_for_build(build.get('id'))


    def create_build(self, team, project, build_version):
        api_url = "api/createbuild/%s/%s/%s" % (team, project, build_version)
        return self.call_with_api_url(api_url=api_url, method='POST', returnResponse=True)


    def submit_test_result(self, team, project, build_version, environment,
            tests_data_dict={}, metadata_dict={}, metrics_dict={}):
        '''
        tests_data_dict': {
            "test_suite1/test_case1": "fail",
            "test_suite1/test_case2": "pass",
            "test_suite2/test_case1": "fail",
            "test_suite2/test_case2": "pass",
        }
        metadata_dict = {
            'job_id': '12345',  # job_id is mandatory here, and need to be string
            'test_metadata': 'xxxx',
        }
        metrics_dict = {
            'metrics_suite1/test_metric1': [1, 2, 3, 4, 5],
            'metrics_suite1/test_metric21': 10,
        }
        '''

        if type(tests_data_dict) != dict or not tests_data_dict:
            raise ParameterInvalidException("tests_data_dict must be a dictionary for test cases, and should not be empty")

        if type(metadata_dict) != dict:
            raise ParameterInvalidException("metadata_dict must be a dictionary for test cases")

        if type(metrics_dict) != dict:
            raise ParameterInvalidException("metrics_dict must be a dictionary for test cases")

        post_data={
            'tests': json.dumps(tests_data_dict)
        }
        if metadata_dict:
            post_data[metadata] = json.dumps(metadata_dict),

        if metrics_dict:
            post_data['metrics'] = json.dumps(metrics_dict),

        api_url = "api/submit/%s/%s/%s/%s" % (team, project, build_version, environment)
        return self.call_with_api_url(api_url=api_url, method='POST', returnResponse=True, post_data=post_data)


    def forceresubmit(self, qa_job_id):
        api_url = 'api/forceresubmit/%s' % qa_job_id
        return self.call_with_api_url(api_url=api_url, method='POST', returnResponse=True)

    def get_job_with_id(self, qa_job_id):
        api_url = 'api/testjobs/%s' % qa_job_id
        return self.call_with_api_url(api_url=api_url)

    def get_job_api_url(self, qa_job_id):
        api_url = '%s/api/testjobs/%s' % (self.get_api_url_prefix().strip('/'), qa_job_id)
        return api_url

    def get_build_meta_with_url(self, build_meta_url):
        return self.call_with_full_url(request_url=build_meta_url)

    def get_qa_job_id_with_url(self, job_url):
        return job_url.strip('/').split('/')[-1]

    def get_lkft_qa_report_projects(self):
        projects = []
        for project in self.get_projects():
            if project.get('is_archived'):
                continue

            project_full_name = project.get('full_name')
            if not project_full_name.startswith('android-lkft/') \
                and not project_full_name.startswith('android-lkft-rc/'):
                continue

            projects.append(project)

        return projects

    def get_aware_datetime_from_str(self, datetime_str):
        import datetime
        import pytz
        # from python3.7, pytz is not necessary, we could use %z to get the timezone info
        #https://stackoverflow.com/questions/53291250/python-3-6-datetime-strptime-returns-error-while-python-3-7-works-well
        navie_datetime = datetime.datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        return pytz.utc.localize(navie_datetime)

    def get_aware_datetime_from_timestamp(self, timestamp_in_secs):
        import datetime
        from django.utils import timezone

        return datetime.datetime.fromtimestamp(timestamp_in_secs, tz=timezone.utc)


class TestNumbers():
    number_passed = 0
    number_failed = 0
    number_total = 0
    modules_done = 0
    modules_total = 0

    def addWithHash(self, numbers_of_result):
        self.number_passed = self.number_passed + numbers_of_result.get('number_passed')
        self.number_failed = self.number_failed + numbers_of_result.get('number_failed')
        self.number_total = self.number_total + numbers_of_result.get('number_total')
        self.modules_done = self.modules_done + numbers_of_result.get('modules_done')
        self.modules_total = self.modules_total + numbers_of_result.get('modules_total')

    def addWithTestNumbers(self, testNumbers):
        self.number_passed = self.number_passed + testNumbers.number_passed
        self.number_failed = self.number_failed + testNumbers.number_failed
        self.number_total = self.number_total + testNumbers.number_total
        self.modules_done = self.modules_done + testNumbers.modules_done
        self.modules_total = self.modules_total + testNumbers.modules_total
