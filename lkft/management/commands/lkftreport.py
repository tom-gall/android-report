## https://docs.djangoproject.com/en/1.11/topics/db/managers/
## https://docs.djangoproject.com/en/dev/howto/custom-management-commands/#howto-custom-management-commands
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-1-62d6b6dc24f8
## https://medium.com/@bencleary/django-scheduled-tasks-queues-part-2-fc1fb810b81d
## https://medium.com/@kevin.michael.horan/scheduling-tasks-in-django-with-the-advanced-python-scheduler-663f17e868e6
## https://django-background-tasks.readthedocs.io/en/latest/


import datetime

from django.core.management.base import BaseCommand, CommandError
from lkft.models import KernelChange, CiBuild

from lcr import qa_report

jenkins_api = qa_report.JenkinsApi('ci.linaro.org', None)

class Command(BaseCommand):
    help = 'Check the build and test results for kernel changes, and send report if the jobs finished'

#    def add_arguments(self, parser):
#        parser.add_argument('git_describes', nargs='+', type=str)

    def handle(self, *args, **options):
        kernel_changes = KernelChange.objects_needs_report.all()
        for kernel_change in kernel_changes:
            trigger_url = jenkins_api.get_job_url(name=kernel_change.trigger_name, number=kernel_change.trigger_number)
            trigger_build = jenkins_api.get_build_details_with_full_url(build_url=trigger_url)
            trigger_build['start_timestamp'] = datetime.datetime.fromtimestamp(int(trigger_build['timestamp'])/1000)
            trigger_build['duration'] = datetime.timedelta(milliseconds=trigger_build['duration'])

            print "%s started at %s, took %s" % (kernel_change, trigger_build['start_timestamp'], trigger_build['duration'])
            ci_builds = CiBuild.objects_kernel_change.get_builds_per_kernel_change(kernel_change=kernel_change)
            for ci_build in ci_builds:
                build_url = jenkins_api.get_job_url(name=ci_build.name, number=ci_build.number)
                build = jenkins_api.get_build_details_with_full_url(build_url=build_url)
                build['start_timestamp'] = datetime.datetime.fromtimestamp(int(build['timestamp'])/1000)

                if build.get('building'):
                    build_status = 'INPROGRESS'
                else:
                    build_status = build.get('result') # null or SUCCESS, FAILURE, ABORTED
                    build['duration'] = datetime.timedelta(milliseconds=build['duration'])

                print "\t %s %s started at %s, took %s" % (ci_build, build_status, build['start_timestamp'], build['duration'])
