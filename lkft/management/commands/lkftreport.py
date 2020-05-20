## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/


import datetime
import json
import logging
import os
import re
import yaml

from django.core.management.base import BaseCommand, CommandError

from django.utils.timesince import timesince

from lkft.models import KernelChange, CiBuild, ReportBuild, ReportProject

from lcr import qa_report
from lcr.irc import IRC

from lcr.settings import QA_REPORT, QA_REPORT_DEFAULT

from lkft.views import get_test_result_number_for_build, get_lkft_build_status, get_ci_build_info
from lkft.views import extract
from lkft.views import get_lkft_bugs, get_hardware_from_pname, get_result_file_path, get_kver_with_pname_env
from lkft.lkft_config import find_expect_cibuilds

from lkft.lkft_config import get_configs, get_qa_server_project

logger = logging.getLogger(__name__)

qa_report_def = QA_REPORT[QA_REPORT_DEFAULT]
qa_report_api = qa_report.QAReportApi(qa_report_def.get('domain'), qa_report_def.get('token'))
jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)
irc = IRC.getInstance()

class Command(BaseCommand):
    help = 'Check the build and test results for kernel changes, and send report if the jobs finished'

#    def add_arguments(self, parser):
#        parser.add_argument('git_describes', nargs='+', type=str)

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


    def get_qareport_build(self, build_version, qaproject_name, cached_qaprojects=[], cached_qareport_builds=[]):
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
                logger.info("%s %s %s" % (build.get('version'),
                                             build.get('created_at'),
                                             build.get('project'),
                                             ))
                break

        return (target_qareport_project, target_qareport_build)


    def handle(self, *args, **options):
        queued_ci_items = jenkins_api.get_queued_items()
        lkft_projects = qa_report_api.get_lkft_qa_report_projects()
        total_reports = []
        # add the same project might have several kernel changes not finished yet
        project_builds = {} # cache builds for the project
        project_platform_bugs = {} #cache bugs for the project and the platform

        # db_kernelchanges = KernelChange.objects_needs_report.all().filter(branch="android-mainline")
        db_kernelchanges = KernelChange.objects_needs_report.all()
        number_kernelchanges = len(db_kernelchanges)
        index = 0
        logger.info("length of kernel changes: %s" % number_kernelchanges)
        for db_kernelchange in db_kernelchanges:
            index = index +1
            logger.info("%d/%d: Try to get info for kernel change: %s %s %s %s" % (index, number_kernelchanges, db_kernelchange.branch, db_kernelchange.describe, db_kernelchange.result, timesince(db_kernelchange.timestamp)))
            test_numbers = qa_report.TestNumbers()
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
                (target_qareport_project, target_qareport_build) = self.get_qareport_build(db_kernelchange.describe,
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

                numbers_of_result = get_test_result_number_for_build(target_qareport_build, jobs)
                target_qareport_build['numbers_of_result'] = numbers_of_result
                target_qareport_build['qa_report_project'] = target_qareport_project

                test_numbers.addWithHash(numbers_of_result)

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
                platform_name = get_hardware_from_pname(project_name)
                project_platform_key = "%s#%s" % (project_name, platform_name)
                bugs = project_platform_bugs.get(project_platform_key)
                if bugs is None:
                    bugs = get_lkft_bugs(summary_keyword=project_name, platform=platform_name)
                    project_platform_bugs[project_platform_key] = bugs

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

            kernel_change_report = {
                    'kernel_change': db_kernelchange,
                    'trigger_build': trigger_build,
                    'jenkins_ci_builds': jenkins_ci_builds,
                    'qa_report_builds': qa_report_builds,
                    'kernel_change_status': kernel_change_status,
                    'error_dict': error_dict,
                    'queued_ci_builds': queued_ci_builds,
                    'disabled_ci_builds': disabled_ci_builds,
                    'not_reported_ci_builds': not_reported_ci_builds,
                    'start_timestamp': trigger_build.get('start_timestamp'),
                    'finished_timestamp': kernel_change_finished_timestamp,
                    'test_numbers': test_numbers,
                }

            total_reports.append(kernel_change_report)

        ## cache to database
        for kernel_change_report in total_reports:
            status = kernel_change_report.get('kernel_change_status')
            trigger_build = kernel_change_report.get('trigger_build')
            kernel_change = kernel_change_report.get('kernel_change')
            # Try to cache Trigger build information to database

            try:
                trigger_dbci_build = CiBuild.objects.get(name=trigger_build.get('name'), kernel_change=kernel_change)
                trigger_dbci_build.duration = trigger_build.get('duration').total_seconds()
                trigger_dbci_build.timestamp = trigger_build.get('start_timestamp')
                trigger_dbci_build.result = trigger_build.get('status')
                trigger_dbci_build.save()
            except CiBuild.DoesNotExist:
                CiBuild.objects.create(name=trigger_build.get('name'),
                                        number=trigger_build.get('number'),
                                        kernel_change=kernel_change,
                                        duration=trigger_build.get('duration').total_seconds(),
                                        timestamp=trigger_build.get('start_timestamp'),
                                        result=trigger_build.get('status'))


            # Try to cache CI build information to database
            jenkins_ci_builds = kernel_change_report.get('jenkins_ci_builds')
            for ci_build in jenkins_ci_builds:
                CiBuild.objects.filter(name=ci_build.get('name'),
                                     number=ci_build.get('number')
                                 ).update(duration=ci_build.get('duration').total_seconds(),
                                     timestamp=ci_build.get('start_timestamp'),
                                     result=ci_build.get('status'))

            # Try to cache kernel change result informtion to database
            finished_timestamp = kernel_change_report.get('finished_timestamp')
            start_timestamp = kernel_change_report.get('start_timestamp')
            test_numbers = kernel_change_report.get('test_numbers')

            kernel_change = kernel_change_report.get('kernel_change')
            kernel_change.reported = (status == 'ALL_COMPLETED') or (status == 'TRIGGER_BUILD_DELETED')
            kernel_change.result = status
            kernel_change.timestamp = start_timestamp
            kernel_change.duration = (finished_timestamp - start_timestamp).total_seconds()
            kernel_change.number_passed = test_numbers.number_passed
            kernel_change.number_failed = test_numbers.number_failed
            kernel_change.number_total = test_numbers.number_total
            kernel_change.modules_done = test_numbers.modules_done
            kernel_change.modules_total = test_numbers.modules_total
            kernel_change.save()

            # Try to cache report build informtion to database
            for qareport_build in kernel_change_report.get('qa_report_builds'):
                jenkins_ci_build = qareport_build.get('ci_build')
                dbci_build = jenkins_ci_build.get('dbci_build')
                result_numbers = qareport_build.get('numbers_of_result')

                trigger_dbci_build = CiBuild.objects.get(name=trigger_build.get('name'), number=trigger_build.get('number'))

                qa_project_group = qareport_build.get('project_group')
                qa_project_name = qareport_build.get('project_name')
                qa_project_slug = qareport_build.get('project_slug')
                qa_project_id = qareport_build.get('project_id')
                try:
                    qa_project = ReportProject.objects.get(group=qa_project_group, name=qa_project_name)
                except ReportProject.DoesNotExist:
                    qa_project = ReportProject.objects.create(group=qa_project_group,
                                                name=qa_project_name,
                                                slug=qa_project_slug,
                                                project_id=qa_project_id)

                try:
                    report_build = ReportBuild.objects.get(qa_project=qa_project,
                                                            version=kernel_change.describe)
                    report_build.kernel_change = kernel_change
                    report_build.ci_build = dbci_build
                    report_build.ci_trigger_build = trigger_dbci_build
                    report_build.number_passed = result_numbers.get('number_passed')
                    report_build.number_failed = result_numbers.get('number_failed')
                    report_build.number_total = result_numbers.get('number_total')
                    report_build.modules_done = result_numbers.get('modules_done')
                    report_build.modules_total = result_numbers.get('modules_total')
                    report_build.started_at = trigger_build.get('start_timestamp')
                    report_build.fetched_at = qareport_build.get('last_fetched_timestamp')
                    report_build.qa_build_id = qareport_build.get('id')
                    report_build.status = qareport_build.get('build_status')
                    report_build.save()
                except ReportBuild.DoesNotExist:
                    ReportBuild.objects.create(qa_project=qa_project,
                                        version=kernel_change.describe,
                                        kernel_change=kernel_change,
                                        ci_build=dbci_build,
                                        ci_trigger_build=trigger_dbci_build,
                                        number_passed=result_numbers.get('number_passed'),
                                        number_failed=result_numbers.get('number_failed'),
                                        number_total=result_numbers.get('number_total'),
                                        modules_done=result_numbers.get('modules_done'),
                                        modules_total=result_numbers.get('modules_total'),
                                        started_at=trigger_build.get('start_timestamp'),
                                        fetched_at=qareport_build.get('last_fetched_timestamp'),
                                        status=qareport_build.get('build_status'),
                                        qa_build_id=qareport_build.get('id'))

        # print out the reports
        print("########## REPORTS FOR KERNEL CHANGES#################")
        num_kernelchanges = len(total_reports)
        index = 0
        irc.send("KERNEL CHANGES STATUS REPORT STARTED: %d in total" % num_kernelchanges)
        for kernel_change_report in total_reports:
            kernel_change = kernel_change_report.get('kernel_change')
            index = index + 1
            irc.send("%d/%d: %s %s %s %s" % (index, num_kernelchanges, kernel_change.branch, kernel_change.describe, kernel_change.result, timesince(kernel_change.timestamp)))
            continue

            trigger_build = kernel_change_report.get('trigger_build')
            jenkins_ci_builds = kernel_change_report.get('jenkins_ci_builds')
            qa_report_builds = kernel_change_report.get('qa_report_builds')
            status = kernel_change_report.get('kernel_change_status')
            trigger_starttimestamp = trigger_build['start_timestamp']
            finished_timestamp = kernel_change_report.get('finished_timestamp')
            if status == "ALL_COMPLETED":
                print("%s started at %s, %s ago, took %s" % (kernel_change, trigger_starttimestamp, timesince(trigger_starttimestamp), finished_timestamp - trigger_starttimestamp))
            else:
                print("%s started at %s, %s ago, %s" % (kernel_change, trigger_starttimestamp, timesince(trigger_starttimestamp), status))

            print("\t Reports for CI Builds:")
            for build in jenkins_ci_builds:
                dbci_build = build.get('dbci_build')
                if build.get('status') == 'INPROGRESS':
                    print("\t\t %s#%s %s, started at %s, %s ago" % (dbci_build.name, dbci_build.number,
                                                             build.get('status'),
                                                             build.get('start_timestamp'),
                                                             timesince(build.get('start_timestamp'))))
                else:
                    print("\t\t %s#%s %s, started at %s, %s ago, took %s" % (dbci_build.name, dbci_build.number,
                                                             build.get('status'),
                                                             build.get('start_timestamp'),
                                                             timesince(build.get('start_timestamp')),
                                                             build.get('duration')))

            queued_ci_builds = kernel_change_report.get('queued_ci_builds')
            for build in  queued_ci_builds:
                inqueuesince = datetime.datetime.fromtimestamp(int(build.get('inQueueSince')/1000), tz=timezone.utc)
                #duration = datetime_now - inqueuesince
                print("\t\t %s: still in queue since %s ago" % (build.get('build_name'), timesince(inqueuesince)))

            not_reported_ci_builds = kernel_change_report.get('not_reported_ci_builds')
            for build in not_reported_ci_builds:
                print("\t\t %s: not reported" % (str(build)))

            disabled_ci_builds = kernel_change_report.get('disabled_ci_builds')
            for build in disabled_ci_builds:
                print("\t\t %s: disabled" % (str(build)))

            print("\t Summary of Projects Status:")
            for build in qa_report_builds:
                qa_report_project = build.get('qa_report_project')
                if build.get('build_status') == "JOBSCOMPLETED":
                    print("\t\t %s %s, created at %s, %s ago, took %s" % (qa_report_project.get('full_name'),
                                                build.get('build_status'),
                                                build.get('created_at'),
                                                timesince(build.get('created_at')),
                                                build.get('duration')))
                else:
                    print("\t\t %s %s, created at %s, %s ago" % (qa_report_project.get('full_name'),
                                                build.get('build_status'),
                                                build.get('created_at'),
                                                timesince(build.get('created_at'))))

                numbers_of_result = build.get('numbers_of_result')
                str_numbers = "\t\t\t Summary: modules_total=%s, modules_done=%s, number_total=%s, number_failed=%s"
                print(str_numbers % (numbers_of_result.get('modules_total'),
                                        numbers_of_result.get('modules_done'),
                                        numbers_of_result.get('number_total'),
                                        numbers_of_result.get('number_failed')))
                str_numbers = "\t\t\t %s: modules_total=%s, modules_done=%s, number_total=%s, number_failed=%s"
                final_jobs = build.get('final_jobs')
                def get_job_name(item):
                    return item.get('name')
                sorted_jobs = sorted(final_jobs, key=get_job_name)

                for job in sorted_jobs:
                    job_name = job.get('name')
                    numbers_of_result = job.get('numbers')
                    if numbers_of_result is not None:
                        print(str_numbers % ("%s#%s %s" % (job_name, job.get('job_id'), job.get('job_status')),
                                            numbers_of_result.get('modules_total'),
                                            numbers_of_result.get('modules_done'),
                                            numbers_of_result.get('number_total'),
                                            numbers_of_result.get('number_failed')))

            print("\t Failures and Bugs:")
            for build in qa_report_builds:
                qa_report_project = build.get('qa_report_project')
                print("\t\t %s %s %s" % (qa_report_project.get('full_name'),
                                            build.get('build_status'),
                                            build.get('created_at')))

                classification = build.get('classification')
                bugs_reproduced = classification.get('bugs_reproduced')
                bugs_not_reproduced = classification.get('bugs_not_reproduced')
                new_failures = classification.get('new_failures')

                print("\t\t\t Bugs Reproduced: %s" % (len(bugs_reproduced)))
                for bug in bugs_reproduced:
                    print("\t\t\t\t %s %s %s" % (bug.id, bug.summary, bug.status))

                print("\t\t\t Bugs Not Reproduced: %s" % (len(bugs_not_reproduced)))
                for bug in bugs_not_reproduced:
                    print("\t\t\t\t %s %s %s" % (bug.id, bug.summary, bug.status))

                print("\t\t\t Failures Not Reported: %s" % (len(new_failures)))
                for failure in new_failures:
                    print("\t\t\t\t %s %s: %s" % (failure.get('module_name'), failure.get('test_name'), failure.get('message')))

        irc.send("KERNEL CHANGES STATUS REPORT FINISHED: %d in total" % num_kernelchanges)
