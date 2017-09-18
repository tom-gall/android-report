from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.jobs, name='jobs'),
    url(r'^resubmit-job/.*$', views.resubmit_job, name='resubmit_job'),
    url(r'^compare/.*$', views.compare, name='compare'),
    url(r'^checklist/.*$', views.checklist, name='checklist'),
]

