# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import requests

from abc import abstractmethod

logger = logging.getLogger(__name__)

class DotDict(dict):
    '''dict.item notation for dict()'s'''
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


class RESTFullApi():
    def __init__(self, domain, api_token):
        self.domain = domain
        self.api_token = api_token

    def call_with_full_url(self, request_url='', method='GET', returnResponse=False):
        headers = { 
                'Content-Type': 'application/json',
                }
        if self.api_token:
            headers['Authorization'] = 'Token %s' % self.api_token
            headers['Auth-Token'] = self.api_token

        if method == 'GET':
            r = requests.get(request_url, headers=headers)
        else:
            r = requests.post(request_url, headers=headers)

        if returnResponse:
            return r

        if not r.ok:
            raise Exception(r.url, r.reason, r.status_code)

        if r.content:
            ret = DotDict(r.json())
            return ret
        else:
            return r

    def call_with_api_url(self, api_url='', method='GET', returnResponse=False):
        full_url = '%s/%s' % (self.get_api_url_prefix().strip('/'), api_url.strip('/'))
        return self.call_with_full_url(request_url=full_url, method=method, returnResponse=returnResponse)

    def get_list_results(self, api_url=''):
        result = self.call_with_api_url(api_url=api_url)
        list_results = result.get('results')
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

    def get_build_details_with_job_url(self, job_url):
        full_api_url = self.get_api_url_prefix(detail_url=job_url)
        return self.call_with_full_url(request_url=full_api_url)

    def get_build_details_with_full_url(self, build_url):
        full_api_url = '%s/api/json/' % build_url
        return self.call_with_full_url(request_url=full_api_url)


class LAVAApi(RESTFullApi):
    def get_api_url_prefix(self):
        return 'https://%s/api/v0.1/' % self.domain


    def get_job(self, job_id=None):
        api_url = "/jobs/%s" % job_id
        return self.call_with_api_url(api_url=api_url)


class QAReportApi(RESTFullApi):
    def get_api_url_prefix(self):
        return 'https://%s/' % self.domain.strip('/')


    def get_projects(self):
        api_url = "/api/projects/"
        return self.get_list_results(api_url=api_url)


    def get_project(self, project_id):
        api_url = "/api/projects/%s" % project_id
        return self.call_with_api_url(api_url=api_url)


    def get_project_with_url(self, project_url):
        return self.call_with_full_url(request_url=project_url)


    def get_all_builds(self, project_id):
        builds_api_url = "api/projects/%s/builds" % project_id
        return self.get_list_results(api_url=builds_api_url)


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