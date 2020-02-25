# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re

citrigger_lkft = {
    'lkft-aosp-master-cts-vts': {
        'aosp-master-tracking':'lkft-aosp-master-tracking',
        'aosp-master-tracking-x15':'lkft-aosp-master-x15',
        },

    'trigger-lkft-android-common': {
        '5.4-gki-aosp-master-hikey': 'lkft-hikey-aosp-master-5.4',
        '5.4-gki-aosp-master-hikey960': 'lkft-hikey960-aosp-master-5.4',
        '5.4-gki-aosp-master-db845c': 'lkft-db845c-aosp-master-5.4',

        'mainline-aosp-master-x15': 'lkft-x15-aosp-master-mainline',
        'mainline-gki-aosp-master-db845c': 'lkft-db845c-aosp-master-mainline',
        'mainline-gki-aosp-master-hikey960': 'lkft-hikey960-aosp-master-mainline-gki',
        },

    # configs for TI 4.14 and 4.19 kernels
    'trigger-lkft-ti-4.19': {
        '4.19-9.0-x15': 'lkft-x15-android-9.0-4.19',
        '4.19-9.0-x15-auto': 'lkft-x15-android-9.0-4.19',
        '4.19-10.0-gsi-x15': 'lkft-x15-10.0-gsi-4.19',
        '4.19-9.0-am65x': 'lkft-am65x-android-9.0-4.19',
        '4.19-9.0-am65x-auto': 'lkft-am65x-android-9.0-4.19',
        },

    'trigger-lkft-x15-4.14': {
        '4.14-8.1-x15': 'lkft-x15-android-8.1-4.14',
        },

    # configs for 4.14 kernels
    'trigger-lkft-hikey-4.14': {
        '4.14-8.1-hikey': 'lkft-hikey-android-8.1-4.14',
        },

    # configs for hikey kernels
    'trigger-lkft-aosp-hikey': {
        '4.14-master-hikey': 'lkft-hikey-aosp-master-4.14',
        '4.14-master-hikey960': 'lkft-hikey-aosp-master-4.14',

        '4.19-master-hikey': 'lkft-hikey-aosp-master-4.19',
        '4.19-master-hikey960': 'lkft-hikey-aosp-master-4.19',
        },

    # configs for hikey kernels
    'trigger-lkft-hikey-stable': {
        '4.4o-8.1-hikey': 'lkft-hikey-4.4-o',
        '4.4o-9.0-lcr-hikey': 'lkft-hikey-4.4-o',
        '4.4o-10.0-gsi-hikey': 'lkft-hikey-4.4-o',

        '4.4p-9.0-hikey': 'lkft-hikey-4.4-p',
        '4.4p-10.0-gsi-hikey': 'lkft-hikey-4.4-p',

        '4.9o-8.1-hikey': 'lkft-hikey-4.9-o',
        '4.9o-9.0-lcr-hikey': 'lkft-hikey-4.9-o',
        '4.9o-10.0-gsi-hikey': 'lkft-hikey-4.9-o',
        '4.9o-10.0-gsi-hikey960': 'lkft-hikey-4.9-o',

        '4.9p-9.0-hikey': 'lkft-hikey-aosp-4.9-premerge-ci',
        '4.9p-9.0-hikey960': 'lkft-hikey-aosp-4.9-premerge-ci',
        '4.9p-10.0-gsi-hikey': 'lkft-hikey-aosp-4.9-premerge-ci',
        '4.9p-10.0-gsi-hikey960': 'lkft-hikey-aosp-4.9-premerge-ci',

        '4.9q-10.0-gsi-hikey': 'lkft-hikey-10.0-4.9-q',
        '4.9q-10.0-gsi-hikey960': 'lkft-hikey-10.0-4.9-q',

        '4.14p-9.0-hikey': 'lkft-hikey-aosp-4.14-premerge-ci',
        '4.14p-9.0-hikey960': 'lkft-hikey-aosp-4.14-premerge-ci',
        '4.14p-10.0-gsi-hikey': 'lkft-hikey-aosp-4.14-premerge-ci',
        '4.14p-10.0-gsi-hikey960': 'lkft-hikey-aosp-4.14-premerge-ci',

        '4.14q-10.0-gsi-hikey': 'lkft-hikey-10.0-4.14-q',
        '4.14q-10.0-gsi-hikey960': 'lkft-hikey-10.0-4.14-q',

        '4.19q-10.0-gsi-hikey': 'lkft-hikey-android-10.0-gsi-4.19',
        '4.19q-10.0-gsi-hikey960': 'lkft-hikey-android-10.0-gsi-4.19',
        },
}


citrigger_lkft_rcs = {
    # configs for hikey kernels
    'trigger-linux-stable-rc': {
        '4.14-q-10gsi-hikey': 'lkft-hikey-4.14-rc',
        '4.14-q-10gsi-hikey960': 'lkft-hikey-4.14-rc',

        '4.19-q-10gsi-hikey': 'lkft-hikey-4.19-rc',
        '4.19-q-10gsi-hikey960': 'lkft-hikey-4.19-rc',

        '4.4-p-10gsi-hikey': 'lkft-hikey-4.4-rc-p',
        '4.4-p-9LCR-hikey': 'lkft-hikey-4.4-rc-p',

        '4.9-p-10gsi-hikey': 'lkft-hikey-4.9-rc',
        '4.9-p-10gsi-hikey960': 'lkft-hikey-4.9-rc',

        '5.4-gki-aosp-master-db845c': 'lkft-db845c-5.4-rc',
        },
}


def find_expect_cibuilds(trigger_name=None):
    if not trigger_name:
        return None
    lkft_builds = citrigger_lkft.get(trigger_name)
    lkft_rc_builds = citrigger_lkft_rcs.get(trigger_name)
    if lkft_builds is not None:
        return set(lkft_builds.values())
    else:
        return set(lkft_rc_builds.values())

def get_ci_trigger_info(project=None):
    if not project.get('full_name'):
        return (None, None, None)

    group_project_names = project.get('full_name').split('/')
    group_name = group_project_names[0]
    lkft_pname = project.get('name')
    citrigger_info = citrigger_lkft
    if group_name == "android-lkft-rc":
        citrigger_info = citrigger_lkft_rcs
    return (group_name, lkft_pname, citrigger_info)

def find_trigger_and_build(project):
    (group_name, lkft_pname, citrigger_info) = get_ci_trigger_info(project=project)
    for trigger_name, lkft_pnames in citrigger_info.items():
        if lkft_pname in lkft_pnames.keys():
            return (trigger_name, lkft_pnames.get(lkft_pname))
    return (None, None)

def find_citrigger(project=None):
    (trigger_name, build_name) = find_trigger_and_build(project)
    return trigger_name

def find_cibuild(project=None):
    (trigger_name, build_name) = find_trigger_and_build(project)
    return build_name

def get_hardware_from_pname(pname=None, env=''):
    if not pname:
        # for aosp master build
        if env.find('hi6220-hikey')>=0:
            return 'HiKey'
        else:
            return None
    if pname.find('hikey960') >= 0:
        return 'HiKey960'
    elif pname.find('hikey') >= 0:
        return 'HiKey'
    elif pname.find('x15') >= 0:
        return 'BeagleBoard-X15'
    elif pname.find('am65x') >= 0:
        return 'AM65X'

def get_version_from_pname(pname=None):
    if pname.find('10.0') >= 0:
        return 'ANDROID-10'
    elif pname.find('8.1') >= 0:
        return 'OREO-8.1'
    elif pname.find('9.0') >= 0:
        return 'PIE-9.0'
    else:
        return 'Master'

def get_kver_with_pname_env(prj_name='', env=''):
    if prj_name == 'aosp-master-tracking':
        # for project aosp-master-tracking
        kernel_version = env.replace('hi6220-hikey_', '')
    elif prj_name == 'aosp-master-tracking-x15':
        kernel_version = env.replace('x15_', '')
    elif prj_name.startswith('mainline-gki'):
        kernel_version = 'mainline-gki'
    else:
        kernel_version = prj_name.split('-')[0]

    return kernel_version


def get_url_content(url=None):
    import urllib2
    try:
        response = urllib2.urlopen(url)
        return response.read()
    except urllib2.HTTPError:
        pass

    return None


def get_configs(ci_build=None):
    build_name = ci_build.get('name')
    configs = []
    ci_config_file_url = "https://git.linaro.org/ci/job/configs.git/plain/%s.yaml" % build_name
    content = get_url_content(url=ci_config_file_url)
    if content is not None:
        pat_configs = re.compile("\n\s+name:\s*ANDROID_BUILD_CONFIG\n\s+default:\s*'(?P<value>[a-zA-Z0-9\ -_.]+)'\s*\n")
        configs_str = pat_configs.findall(content)
        if len(configs_str) > 0:
            for config in ' '.join(configs_str[0].split()).split():
                configs.append((config, ci_build))

    return configs

def get_qa_server_project(lkft_build_config_name=None):
    #TEST_QA_SERVER=https://qa-reports.linaro.org
    #TEST_QA_SERVER_PROJECT=mainline-gki-aosp-master-hikey960
    #TEST_QA_SERVER_TEAM=android-lkft-rc
    url_build_config = "https://android-git.linaro.org/android-build-configs.git/plain/lkft/%s?h=lkft" % lkft_build_config_name
    content = get_url_content(url_build_config)
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