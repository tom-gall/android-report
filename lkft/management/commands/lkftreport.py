## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/


import datetime
import json
import os
import re
import urllib2
import yaml

from django.core.management.base import BaseCommand, CommandError

from django.utils.timesince import timesince

from lkft.models import KernelChange, CiBuild, ReportBuild

from lcr import qa_report

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT

from lkft.views import get_test_result_number_for_build, get_lkft_build_status
from lkft.views import extract
from lkft.views import get_lkft_bugs, get_hardware_from_pname, get_result_file_path, get_kver_with_pname_env
from lkft.lkft_config import find_expect_cibuilds

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


    def get_configs(self, ci_build=None):
        build_name = ci_build.get('name')
        configs = []
        ci_config_file_url = "https://git.linaro.org/ci/job/configs.git/plain/%s.yaml" % build_name
        content = self.get_url_content(url=ci_config_file_url)
        if content is not None:
            pat_configs = re.compile("\n\s+name:\s*ANDROID_BUILD_CONFIG\n\s+default:\s*'(?P<value>[a-zA-Z0-9\ -_.]+)'\s*\n")
            configs_str = pat_configs.findall(content)
            if len(configs_str) > 0:
                for config in ' '.join(configs_str[0].split()).split():
                    configs.append((config, ci_build))

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


    def classify_bugs_and_failures(self, bugs=[], failures=[]):
        bugs_reproduced = []
        bugs_not_reproduced = []
        new_failures = []

        for module_name in sorted(failures.keys()):
            failures_in_module = failures.get(module_name)
            for test_name in sorted(failures_in_module.keys()):
                failure = failures_in_module.get(test_name)

                for bug in bugs:
                    if test_name.find(module_name) >=0:
                        # vts test, module name is the same as the test name.
                        search_key = test_name
                    else:
                        search_key = '%s %s' % (module_name, test_name)

                    if bug.summary.find(search_key) >= 0:
                        bugs_reproduced.append(bug)
                        if failure.get('bugs'):
                            failure['bugs'].append(bug)
                        else:
                            failure['bugs'] = [bug]

                if failure.get('bugs') is None or len(failure.get('bugs')) == 0:
                    new_failures.append(failure)

        bugs_not_reproduced = [ bug for bug in bugs if not (bug in bugs_reproduced) ]

        return {
                'bugs_reproduced': bugs_reproduced,
                'bugs_not_reproduced': bugs_not_reproduced,
                'new_failures': new_failures,
                }


    def handle(self, *args, **options):

        total_reports = []

        lkft_projects = self.get_lkft_qa_report_projects()
        queued_ci_items = jenkins_api.get_queued_items()
        kernel_changes = KernelChange.objects_needs_report.all()
        for kernel_change in kernel_changes:
            lkft_build_configs = []
            trigger_url = jenkins_api.get_job_url(name=kernel_change.trigger_name, number=kernel_change.trigger_number)
            trigger_build = jenkins_api.get_build_details_with_full_url(build_url=trigger_url)
            trigger_build['start_timestamp'] = datetime.datetime.fromtimestamp(int(trigger_build['timestamp'])/1000)
            trigger_build['duration'] = datetime.timedelta(milliseconds=trigger_build['duration'])
            trigger_build['name'] = kernel_change.trigger_name
            trigger_build['kernel_change'] = kernel_change
            kernel_change_finished_timestamp = trigger_build['start_timestamp']

            kernel_change_status = "TRIGGER_BUILD_COMPLETED"

            dbci_builds = CiBuild.objects_kernel_change.get_builds_per_kernel_change(kernel_change=kernel_change).order_by('name', '-number')

            ## TODO: how to check if a ci build is still in queue?
            ##       check which ci build should be started from the information of the trigger build?
            expect_build_names = find_expect_cibuilds(trigger_name=kernel_change.trigger_name)

            jenkins_ci_builds = []
            ci_build_names = []
            has_build_inprogress = False
            for dbci_build in dbci_builds:
                if dbci_build.name in ci_build_names:
                    continue
                else:
                    ci_build_names.append(dbci_build.name)

                build_url = jenkins_api.get_job_url(name=dbci_build.name, number=dbci_build.number)
                build = jenkins_api.get_build_details_with_full_url(build_url=build_url)
                build['start_timestamp'] = datetime.datetime.fromtimestamp(int(build['timestamp'])/1000)
                build['dbci_build'] = dbci_build

                if build.get('building'):
                    build_status = 'INPROGRESS'
                    has_build_inprogress = True
                else:
                    build_status = build.get('result') # null or SUCCESS, FAILURE, ABORTED
                    build['duration'] = datetime.timedelta(milliseconds=build['duration'])

                build['status'] = build_status
                build['name'] = dbci_build.name
                jenkins_ci_builds.append(build)
                configs = self.get_configs(ci_build=build)
                lkft_build_configs.extend(configs)

            not_started_ci_builds = expect_build_names - set(ci_build_names)

            queued_ci_builds = []
            diabled_ci_builds = []
            not_reported_ci_builds = []
            if len(not_started_ci_builds) > 0:
                for cibuild_name in not_started_ci_builds:
                    is_queued_build = False
                    for queued_item in queued_ci_items:
                        if cibuild_name == queued_item.get('build_name') and \
                            kernel_change.describe == queued_item.get('KERNEL_DESCRIBE'):
                                is_queued_build = True
                                queued_ci_builds.append(queued_item)
                    if is_queued_build:
                        continue

                    if jenkins_api.is_build_disabled(cibuild_name):
                        diabled_ci_builds.append(cibuild_name)
                    else:
                        not_reported_ci_builds.append(cibuild_name)

            if queued_ci_builds:
                kernel_change_status = "CI_BUILDS_IN_QUEUE"
            elif not_reported_ci_builds:
                kernel_change_status = "CI_BUILDS_NOT_REPORTED"
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
            for lkft_build_config, ci_build in lkft_build_configs:
                if ci_build.get('status') != 'SUCCESS':
                    # no need to check the build/job results as the ci build not finished successfully yet
                    continue

                (project_group, project_name) = self.get_qa_server_project(lkft_build_config_name=lkft_build_config)
                target_lkft_project_full_name = "%s/%s" % (project_group, project_name)

                target_qareport_project = None
                for lkft_project in lkft_projects:
                    if lkft_project.get('full_name') == target_lkft_project_full_name:
                        target_qareport_project = lkft_project
                        break

                if target_qareport_project is None:
                    qareport_project_not_found_configs.append(lkft_build_config)
                    continue

                target_qareport_build = None
                builds = qa_report_api.get_all_builds(target_qareport_project.get('id'))
                for build in builds:
                    if build.get('version') == kernel_change.describe:
                        target_qareport_build = build
                        break

                if target_qareport_build is None:
                    qareport_build_not_found_configs.append(lkft_build_config)
                    continue

                created_str = target_qareport_build.get('created_at')
                target_qareport_build['created_at'] = datetime.datetime.strptime(str(created_str), '%Y-%m-%dT%H:%M:%S.%fZ')
                target_qareport_build['project_name'] = project_name
                target_qareport_build['project_group'] = project_group

                jobs = qa_report_api.get_jobs_for_build(target_qareport_build.get("id"))
                build_status = get_lkft_build_status(target_qareport_build, jobs)
                if build_status['has_unsubmitted']:
                    target_qareport_build['build_status'] = "JOBSNOTSUBMITTED"
                    has_jobs_not_submitted = True
                elif build_status['is_inprogress']:
                    target_qareport_build['build_status'] = "JOBSINPROGRESS"
                    has_jobs_in_progress = True
                else:
                    target_qareport_build['build_status'] = "JOBSCOMPLETED"
                    target_qareport_build['last_fetched_timestamp'] = build_status['last_fetched_timestamp']
                    if kernel_change_finished_timestamp is None or \
                        kernel_change_finished_timestamp < build_status['last_fetched_timestamp']:
                        kernel_change_finished_timestamp = build_status['last_fetched_timestamp']
                    target_qareport_build['duration'] = build_status['last_fetched_timestamp'] - target_qareport_build['created_at']

                target_qareport_build['numbers_of_result'] = get_test_result_number_for_build(target_qareport_build, jobs)
                target_qareport_build['qa_report_project'] = target_qareport_project
                final_jobs = []
                resubmitted_or_duplicated_jobs = []
                for job in jobs:
                    is_resubmited_job = job.get('resubmitted')
                    is_duplicated_job = job.get('duplicated')
                    if is_resubmited_job is None and is_duplicated_job is None:
                        final_jobs.append(job)
                    else:
                        resubmitted_or_duplicated_jobs.append(job)

                target_qareport_build['final_jobs'] = final_jobs
                target_qareport_build['resubmitted_or_duplicated_jobs'] = resubmitted_or_duplicated_jobs
                qa_report_builds.append(target_qareport_build)

                project_name = target_qareport_project.get('name')
                bugs = get_lkft_bugs(summary_keyword=project_name, platform=get_hardware_from_pname(project_name))
                build['bugs'] = bugs

                failures = {}
                for job in final_jobs:
                    if job.get('job_status') is None and \
                        job.get('submitted') and \
                        not job.get('fetched'):
                        job['job_status'] = 'Submitted'
                    if job.get('failure'):
                        failure = job.get('failure')
                        new_str = failure.replace('"', '\\"').replace('\'', '"')
                        try:
                            failure_dict = json.loads(new_str)
                        except ValueError:
                            failure_dict = {'error_msg': new_str}


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
                    extract(result_file_path, failed_testcases_all=failures, metadata=metadata)

                target_qareport_build['failures'] = failures
                classification = self.classify_bugs_and_failures(bugs=bugs, failures=failures)
                target_qareport_build['classification'] = classification
                target_qareport_build['ci_build'] = ci_build

            has_error = False
            error_dict = {}
            if kernel_change_status == "CI_BUILDS_COMPLETED":
                if qareport_project_not_found_configs or qareport_build_not_found_configs:
                    has_error = True
                    if qareport_project_not_found_configs:
                        kernel_change_status = 'HAS_QA_PROJECT_NOT_FOUND'
                        error_dict['qareport_project_not_found_configs'] = qareport_project_not_found_configs
                    if qareport_build_not_found_configs:
                        kernel_change_status = 'HAS_QA_BUILD_NOT_FOUND'
                        error_dict['qareport_build_not_found_configs'] = qareport_build_not_found_configs
                elif has_jobs_not_submitted:
                    kernel_change_status = 'HAS_JOBS_NOT_SUBMITTED'
                elif has_jobs_in_progress:
                    kernel_change_status = 'HAS_JOBS_IN_PROGRESS'
                else:
                    kernel_change_status = 'ALL_COMPLETED'

            kernel_change_report = {
                    'kernel_change': kernel_change,
                    'trigger_build': trigger_build,
                    'jenkins_ci_builds': jenkins_ci_builds,
                    'qa_report_builds': qa_report_builds,
                    'kernel_change_status': kernel_change_status,
                    'error_dict': error_dict,
                    'queued_ci_builds': queued_ci_builds,
                    'diabled_ci_builds': diabled_ci_builds,
                    'not_reported_ci_builds': not_reported_ci_builds,
                    'finished_timestamp': kernel_change_finished_timestamp,
                }

            total_reports.append(kernel_change_report)

        ## cache to database
        for kernel_change_report in total_reports:
            status = kernel_change_report.get('kernel_change_status')
            if status != 'ALL_COMPLETED':
                continue

            kernel_change = kernel_change_report.get('kernel_change')
            kernel_change.reported = True
            kernel_change.save()

            trigger_build = kernel_change_report.get('trigger_build')
            if not trigger_build.get('building'):
                # should always be here
                CiBuild.objects.filter(name=trigger_build.get('name'),
                                        number=trigger_build.get('number')
                                    ).update(duration=trigger_build.get('duration').total_seconds(),
                                            timestamp=trigger_build.get('start_timestamp'),
                                            result=trigger_build.get('result'))

            jenkins_ci_builds = kernel_change_report.get('jenkins_ci_builds')
            for ci_build in jenkins_ci_builds:
                if build.get('building'):
                    # there should be no such case
                    continue
                CiBuild.objects.filter(name=ci_build.get('name'),
                                     number=ci_build.get('number')
                                 ).update(duration=ci_build.get('duration').total_seconds(),
                                     timestamp=ci_build.get('start_timestamp'),
                                     result=ci_build.get('result'))

            for qareport_build in kernel_change_report.get('qa_report_builds'):
                jenkins_ci_build = qareport_build.get('ci_build')
                dbci_build = jenkins_ci_build.get('dbci_build')
                result_numbers = qareport_build.get('numbers_of_result')

                try:
                    report_build = ReportBuild.objects.get(group=qareport_build.get('project_group'),
                                                            name=qareport_build.get('project_name'),
                                                            version=kernel_change.describe)
                    report_build.kernel_change = kernel_change
                    report_build.ci_build = dbci_build
                    report_build.ci_trigger_build = CiBuild.objects.get(name=trigger_build.get('name'), number=trigger_build.get('number'))
                    report_build.number_passed = result_numbers.get('number_passed')
                    report_build.number_failed = result_numbers.get('number_failed')
                    report_build.number_total = result_numbers.get('number_total')
                    report_build.modules_done = result_numbers.get('modules_done')
                    report_build.modules_total = result_numbers.get('modules_total')
                    report_build.started_at = trigger_build.get('start_timestamp')
                    report_build.fetched_at = qareport_build.get('last_fetched_timestamp')
                    report_build.save()
                except KernelChange.DoesNotExist:
                    ReportBuild.objects.create(group=qareport_build.get('project_group'),
                                        name=qareport_build.get('project_name'),
                                        version=kernel_change.describe,
                                        kernel_change=kernel_change,
                                        ci_build=dbci_build,
                                        ci_trigger_build=CiBuild.objects.get(name=trigger_build.get('name'), number=trigger_build.get('number')),
                                        number_passed=result_numbers.get('number_passed'),
                                        number_failed=result_numbers.get('number_failed'),
                                        number_total=result_numbers.get('number_total'),
                                        modules_done=result_numbers.get('modules_done'),
                                        modules_total=result_numbers.get('modules_total'),
                                        started_at=trigger_build.get('start_timestamp'),
                                        fetched_at=qareport_build.get('last_fetched_timestamp'))


        # print out the reports
        print "########## REPORTS FOR KERNEL CHANGES#################"
        for kernel_change_report in total_reports:
            kernel_change = kernel_change_report.get('kernel_change')
            trigger_build = kernel_change_report.get('trigger_build')
            jenkins_ci_builds = kernel_change_report.get('jenkins_ci_builds')
            qa_report_builds = kernel_change_report.get('qa_report_builds')
            status = kernel_change_report.get('kernel_change_status')
            trigger_starttimestamp = trigger_build['start_timestamp']
            finished_timestamp = kernel_change_report.get('finished_timestamp')
            if status == "ALL_COMPLETED":
                print "%s started at %s, %s ago, took %s" % (kernel_change, trigger_starttimestamp, timesince(trigger_starttimestamp), finished_timestamp - trigger_starttimestamp)
            else:
                print "%s started at %s, %s ago, %s" % (kernel_change, trigger_starttimestamp, timesince(trigger_starttimestamp), status)

            print "\t Reports for CI Builds:"
            for build in jenkins_ci_builds:
                dbci_build = build.get('dbci_build')
                if build.get('status') == 'INPROGRESS':
                    print "\t\t %s#%s %s, started at %s, %s ago" % (dbci_build.name, dbci_build.number,
                                                             build.get('status'),
                                                             build.get('start_timestamp'),
                                                             timesince(build.get('start_timestamp')))
                else:
                    print "\t\t %s#%s %s, started at %s, %s ago, took %s" % (dbci_build.name, dbci_build.number,
                                                             build.get('status'),
                                                             build.get('start_timestamp'),
                                                             timesince(build.get('start_timestamp')),
                                                             build.get('duration'))

            queued_ci_builds = kernel_change_report.get('queued_ci_builds')
            for build in  queued_ci_builds:
                inqueuesince = datetime.datetime.fromtimestamp(int(build.get('inQueueSince')/1000))
                #duration = datetime_now - inqueuesince
                print "\t\t %s: still in queue since %s ago" % (build.get('build_name'), timesince(inqueuesince))

            not_reported_ci_builds = kernel_change_report.get('not_reported_ci_builds')
            for build in not_reported_ci_builds:
                print "\t\t %s: not reported" % (str(build))

            diabled_ci_builds = kernel_change_report.get('diabled_ci_builds')
            for build in diabled_ci_builds:
                print "\t\t %s: disabled" % (str(build))

            print "\t Summary of Projects Status:"
            for build in qa_report_builds:
                qa_report_project = build.get('qa_report_project')
                if build.get('build_status') == "JOBSCOMPLETED":
                    print "\t\t %s %s, created at %s, %s ago, took %s" % (qa_report_project.get('full_name'),
                                                build.get('build_status'),
                                                build.get('created_at'),
                                                timesince(build.get('created_at')),
                                                build.get('duration'))
                else:
                    print "\t\t %s %s, created at %s, %s ago" % (qa_report_project.get('full_name'),
                                                build.get('build_status'),
                                                build.get('created_at'),
                                                timesince(build.get('created_at')))

                numbers_of_result = build.get('numbers_of_result')
                str_numbers = "\t\t\t Summary: modules_total=%s, modules_done=%s, number_total=%s, number_failed=%s"
                print str_numbers % (numbers_of_result.get('modules_total'),
                                        numbers_of_result.get('modules_done'),
                                        numbers_of_result.get('number_total'),
                                        numbers_of_result.get('number_failed'))
                str_numbers = "\t\t\t %s: modules_total=%s, modules_done=%s, number_total=%s, number_failed=%s"
                final_jobs = build.get('final_jobs')
                def get_job_name(item):
                    return item.get('name')
                sorted_jobs = sorted(final_jobs, key=get_job_name)

                for job in sorted_jobs:
                    job_name = job.get('name')
                    numbers_of_result = job.get('numbers')
                    if numbers_of_result is not None:
                        print str_numbers % ("%s#%s %s" % (job_name, job.get('job_id'), job.get('job_status')),
                                            numbers_of_result.get('modules_total'),
                                            numbers_of_result.get('modules_done'),
                                            numbers_of_result.get('number_total'),
                                            numbers_of_result.get('number_failed'))


            print "\t Failures and Bugs:"
            for build in qa_report_builds:
                qa_report_project = build.get('qa_report_project')
                print "\t\t %s %s %s" % (qa_report_project.get('full_name'),
                                            build.get('build_status'),
                                            build.get('created_at'))

                classification = build.get('classification')
                bugs_reproduced = classification.get('bugs_reproduced')
                bugs_not_reproduced = classification.get('bugs_not_reproduced')
                new_failures = classification.get('new_failures')

                print "\t\t\t Bugs Reproduced: %s" % (len(bugs_reproduced))
                for bug in bugs_reproduced:
                    print "\t\t\t\t %s %s %s" % (bug.id, bug.summary, bug.status)

                print "\t\t\t Bugs Not Reproduced: %s" % (len(bugs_not_reproduced))
                for bug in bugs_not_reproduced:
                    print "\t\t\t\t %s %s %s" % (bug.id, bug.summary, bug.status)

                print "\t\t\t Failures Not Reported: %s" % (len(new_failures))
                for failure in new_failures:
                    print "\t\t\t\t %s %s: %s" % (failure.get('module_name'), failure.get('test_name'), failure.get('message'))
