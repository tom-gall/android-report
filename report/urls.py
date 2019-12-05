from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='home'),
    url(r'^jobs/.*$', views.jobs, name='jobs'),
    url(r'^resubmit-job/.*$', views.resubmit_job, name='resubmit_job'),
    url(r'^compare/.*$', views.compare, name='compare'),
    url(r'^checklist/.*$', views.checklist, name='checklist'),
    url(r'^submit-jobs/.*$', views.submit_lava_jobs, name='submit_jobs'),
    url(r'^test-report/.*$', views.test_report, name='test_report'),
    url(r'^add-bug/.*$', views.add_bug, name='add_bug'),
    url(r'^add-comment/.*$', views.add_comment, name='add_comment'),
    url(r'^show-trend/.*$', views.show_trend, name='show_trend'),
    url(r'^show-cts-vts-failures/.*$', views.show_cts_vts_failures, name='show_cts_vts_failures'),
    url(r'^file-bug/.*$', views.file_bug, name='file_bug'),
]
