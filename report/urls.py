from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^jobs/.*$', views.jobs, name='jobs'),
    url(r'^resubmit-job/.*$', views.resubmit_job, name='resubmit_job'),
    url(r'^compare/.*$', views.compare, name='compare'),
    url(r'^checklist/.*$', views.checklist, name='checklist'),
    url(r'^submit-jobs/.*$', views.submit_lava_jobs, name='submit_jobs'),
    url(r'^test-report/.*$', views.test_report, name='test_report'),
]
