from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.list_projects, name='home'),
    url(r'^projects/.*$', views.list_projects, name='list_projects'),
    url(r'^builds/.*$', views.list_builds, name='list_builds'),
    url(r'^jobs/.*$', views.list_jobs, name='list_jobs'),
    url(r'^file-bug/.*$', views.file_bug, name='file_bug'),
]
