## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/


import datetime
import re
import urllib2
import yaml

from django.core.management.base import BaseCommand, CommandError
from lkft.models import KernelChange, CiBuild

from lcr import qa_report

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT

from lkft.views import get_test_result_number_for_build, get_lkft_build_status

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)

class Command(BaseCommand):
    help = 'Check the build and test results for kernel changes, and send report if the jobs finished'

#    def add_arguments(self, parser):
#        parser.add_argument('git_describes', nargs='+', type=str)

    def get_url_content(self, url=None):
        try:
            response = urllib2.urlopen(url)
            return response.read()
        except urllib2.HTTPError:
            pass

        return None


    def get_configs(self, build_name=None):
        configs = []
        ci_config_file_url = "https://git.linaro.org/ci/job/configs.git/plain/%s.yaml" % build_name
        content = self.get_url_content(url=ci_config_file_url)
        if content is not None:
            pat_configs = re.compile("\n\s+name:\s*ANDROID_BUILD_CONFIG\n\s+default:\s*'(?P<value>[a-zA-Z0-9\ -_.]+)'\s*\n")
            configs_str = pat_configs.findall(content)
            if len(configs_str) > 0:
                configs = ' '.join(configs_str[0].split()).split()

        return configs

    def get_qa_server_project(self, lkft_build_config_name=None):
        #TEST_QA_SERVER=https://qa-reports.linaro.org
        #TEST_QA_SERVER_PROJECT=mainline-gki-aosp-master-hikey960
        #TEST_QA_SERVER_TEAM=android-lkft-rc
        url_build_config = "https://android-git.linaro.org/android-build-configs.git/plain/lkft/%s?h=lkft" % lkft_build_config_name
        content = self.get_url_content(url_build_config)
        pat_project = re.compile("\nTEST_QA_SERVER_PROJECT=(?P<value>[a-zA-Z0-9\ -_.]+)\n")
        project_str = pat_project.findall(content)
        if len(project_str) > 0:
            project = project_str[0]
        else:
            project = None

        pat_team=re.compile("\nTEST_QA_SERVER_TEAM=(?P<value>[a-zA-Z0-9\ -_.]+)\n")
        team_str = pat_team.findall(content)
        if len(team_str) > 0:
            team = team_str[0]
        else:
            team = "android-lkft"

        return (team, project)


    def get_lkft_qa_report_projects(self):
        projects = []
        for project in qa_report_api.get_projects():
            project_full_name = project.get('full_name')
            if not project_full_name.startswith('android-lkft/') \
                or project.get('is_archived'):
                continue

            projects.append(project)

        return projects

    def handle(self, *args, **options):

        total_reports = []

        lkft_projects = self.get_lkft_qa_report_projects()
        kernel_changes = KernelChange.objects_needs_report.all()
        for kernel_change in kernel_changes:
            lkft_build_configs = []
            trigger_url = jenkins_api.get_job_url(name=kernel_change.trigger_name, number=kernel_change.trigger_number)
            trigger_build = jenkins_api.get_build_details_with_full_url(build_url=trigger_url)
            trigger_build['start_timestamp'] = datetime.datetime.fromtimestamp(int(trigger_build['timestamp'])/1000)
            trigger_build['duration'] = datetime.timedelta(milliseconds=trigger_build['duration'])


            ci_builds = CiBuild.objects_kernel_change.get_builds_per_kernel_change(kernel_change=kernel_change)
            jenkins_ci_builds = []
            for ci_build in ci_builds:
                build_url = jenkins_api.get_job_url(name=ci_build.name, number=ci_build.number)
                build = jenkins_api.get_build_details_with_full_url(build_url=build_url)
                build['start_timestamp'] = datetime.datetime.fromtimestamp(int(build['timestamp'])/1000)
                build['db_ci_build'] = ci_build

                if build.get('building'):
                    build_status = 'INPROGRESS'
                else:
                    build_status = build.get('result') # null or SUCCESS, FAILURE, ABORTED
                    build['duration'] = datetime.timedelta(milliseconds=build['duration'])

                build['status'] = build_status
                jenkins_ci_builds.append(build)
                configs = self.get_configs(build_name=ci_build.name)
                lkft_build_configs.extend(configs)

            qa_report_builds = []
            for lkft_build_config in lkft_build_configs:
                (team, project) = self.get_qa_server_project(lkft_build_config_name=lkft_build_config)
                target_lkft_project_full_name = "%s/%s" % (team, project)
                for lkft_project in lkft_projects:
                    if lkft_project.get('full_name') == target_lkft_project_full_name:
                        builds = qa_report_api.get_all_builds(lkft_project.get('id'))
                        for build in builds:
                            if build.get('version') == kernel_change.describe:
                                created_str = build.get('created_at')
                                build['created_at'] = datetime.datetime.strptime(str(created_str), '%Y-%m-%dT%H:%M:%S.%fZ')

                                jobs = qa_report_api.get_jobs_for_build(build.get("id"))
                                build_status = get_lkft_build_status(build, jobs)
                                if build_status['has_unsubmitted']:
                                    build['build_status'] = "JOBSNOTSUBMITTED"
                                elif build_status['is_inprogress']:
                                    build['build_status'] = "JOBSINPROGRESS"
                                else:
                                    build['build_status'] = "JOBSCOMPLETED"
                                    build['last_fetched_timestamp'] = build_status['last_fetched_timestamp']

                                build['numbers_of_result'] = get_test_result_number_for_build(build, jobs)
                                build['qa_report_project'] = lkft_project
                                qa_report_builds.append(build)

            kernel_change_report = {
                    'kernel_change': kernel_change,
                    'trigger_build': trigger_build,
                    'jenkins_ci_builds': jenkins_ci_builds,
                    'qa_report_builds': qa_report_builds,
                }

            total_reports.append(kernel_change_report)

        # print out the reports
        print "########## REPORTS FOR KERNEL CHANGES#################"
        for kernel_change_report in total_reports:
            kernel_change = kernel_change_report.get('kernel_change')
            trigger_build = kernel_change_report.get('trigger_build')
            jenkins_ci_builds = kernel_change_report.get('jenkins_ci_builds')
            qa_report_builds = kernel_change_report.get('qa_report_builds')
            print "%s started at %s, took %s" % (kernel_change, trigger_build['start_timestamp'], trigger_build['duration'])

            print "\t Reports for CI Builds:"
            for build in jenkins_ci_builds:
                db_ci_build = build.get('db_ci_build')
                print "\t\t %s %s, started at %s, took %s" % (db_ci_build.name,
                                                             build.get('status'),
                                                             build.get('start_timestamp'),
                                                             build.get('duration'))

            print "\t Summary of Builds Status:"
            for build in qa_report_builds:
                qa_report_project = build.get('qa_report_project')
                print "\t\t %s %s %s" % (qa_report_project.get('full_name'),
                                            build.get('build_status'),
                                            build.get('created_at'))
                numbers_of_result = build.get('numbers_of_result')
                str_numbers = "\t\t\t modules_total=%s, modules_done=%s, number_total=%s, number_failed=%s"
                print str_numbers % (numbers_of_result.get('modules_total'),
                                        numbers_of_result.get('modules_done'),
                                        numbers_of_result.get('number_total'),
                                        numbers_of_result.get('number_failed'))

            print "\t Summary of Jobs status:"
            print "\t Failures Not Reported:"
            print "\t Failures Reproduced:"
            print "\t Failures Not Reproduced:"
