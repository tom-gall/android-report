from django.conf.urls import url

from . import views

basic_pat = '[a-zA-Z0-9][a-zA-Z0-9_.-]+'
urlpatterns = [
    url(r'^$', views.list_projects, name='home'),
    url(r'^rc-projects/.*$', views.list_rc_projects, name='list_rc_projects'),
    url(r'^projects/.*$', views.list_projects, name='list_projects'),
    url(r'^kernel-changes/.*$', views.list_kernel_changes, name='list_kernel_changes'),
    url(r'^builds/.*$', views.list_builds, name='list_builds'),
    url(r'^jobs/.*$', views.list_jobs, name='list_jobs'),
    url(r'^file-bug/.*$', views.file_bug, name='file_bug'),
    url(r'^resubmit-job/.*$', views.resubmit_job, name='resubmit_job'),
    # newchanges/$branch/$describe/$build_name/$build_number
    url(r'^newchanges/(%s)/(%s)/(%s)/([0-9]+)' % (basic_pat, basic_pat, basic_pat), views.new_kernel_changes),
    # newchanges/$branch/$describe/$build_name/$build_number
    url(r'^newbuild/(%s)/(%s)/(%s)/([0-9]+)' % (basic_pat, basic_pat, basic_pat), views.new_build, name='new_build'),
]
