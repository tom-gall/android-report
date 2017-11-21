from django.conf.urls import url

from . import views
from . import accountviews

urlpatterns = [
    url(r'^$', views.index, name='home'),
    url(r'^jobs/.*$', views.jobs, name='jobs'),
    url(r'^resubmit-job/.*$', views.resubmit_job, name='resubmit_job'),
    url(r'^compare/.*$', views.compare, name='compare'),
    url(r'^checklist/.*$', views.checklist, name='checklist'),
    url(r'^submit-jobs/.*$', views.submit_lava_jobs, name='submit_jobs'),
    url(r'^test-report/.*$', views.test_report, name='test_report'),
    url(r'^add-bug/.*$', views.add_bug, name='add_bug'),

    url(r'^accounts/register/$', accountviews.SignUpView.as_view(), name='signup'),
    url(r'^accounts/login/$', accountviews.LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', accountviews.LogOutView.as_view(), name='logout'),
]
