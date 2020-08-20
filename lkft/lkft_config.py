# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import logging

logger = logging.getLogger(__name__)

'''
    {
        trigger_build: {
            qa_project: ci_build,
        },
    }
'''
citrigger_lkft = {
    'lkft-aosp-master-cts-vts': {
        'aosp-master-tracking':'lkft-aosp-master-tracking',
        'aosp-master-tracking-x15':'lkft-aosp-master-x15',
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

    # The above configs should be deleted
    'trigger-lkft-omap': {
        '4.14-master-x15': 'lkft-generic-omap-build',
        '4.19-master-x15': 'lkft-generic-omap-build',
        },

    'trigger-lkft-linaro-omap': {
        '4.14-stable-master-x15-lkft': 'lkft-generic-omap-build',
        '4.19-stable-master-x15-lkft': 'lkft-generic-omap-build',
        },

    'trigger-lkft-linaro-hikey': {
        '4.14-stable-master-hikey-lkft': 'lkft-generic-mirror-build',
        '4.14-stable-master-hikey960-lkft': 'lkft-generic-mirror-build',
        '4.19-stable-master-hikey-lkft': 'lkft-generic-mirror-build',
        '4.19-stable-master-hikey960-lkft': 'lkft-generic-mirror-build',
        },

    'trigger-lkft-android-common': {
        '5.4-android12-aosp-master-x15': 'lkft-generic-omap-build',
        '5.4-gki-android12-aosp-master-hikey': 'lkft-hikey-aosp-master-5.4',
        '5.4-gki-android12-aosp-master-hikey960': 'lkft-generic-build',
        '5.4-gki-android12-aosp-master-db845c': 'lkft-generic-build',
        '5.4-gki-android12-aosp-master-db845c-presubmit': 'lkft-generic-build',
        '5.4-gki-android12-aosp-master-db845c-full-cts-vts': 'lkft-generic-build',
        '5.4-gki-android12-aosp-master-hikey960-full-cts-vts': 'lkft-generic-build',


        'mainline-aosp-master-x15': 'lkft-x15-aosp-master-mainline',
        'mainline-gki-aosp-master-db845c': 'lkft-generic-build',
        'mainline-gki-aosp-master-db845c-full-cts-vts': 'lkft-generic-build',
        'mainline-gki-aosp-master-hikey960': 'lkft-generic-build',
        'mainline-gki-aosp-master-hikey960-full-cts-vts': 'lkft-generic-build',
        },

    'trigger-lkft-prebuilts': {
        'mainline-gki-aosp-master-db845c-prebuilts': 'lkft-generic-build',
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

'''
    trigger :{
        branch: [ci_build, ci_build]
    }
'''
trigger_branch_builds_info = {
    'trigger-lkft-prebuilts':{
        'android-mainline-prebuilts': ['lkft-generic-build'],
    },

    'trigger-lkft-android-common-weekly':{
        'android12-5.4-weekly': ['lkft-generic-build'],
    },

    'trigger-lkft-android-common':{
        'android12-5.4': ['lkft-hikey-aosp-master-5.4',
                        'lkft-generic-build',
                        'lkft-generic-omap-build'],

        'android11-5.4': ['lkft-generic-build'],

        'android-mainline': ['lkft-generic-build',
                             'lkft-generic-omap-build'],
    },

    # configs for hikey kernels
    'trigger-linux-stable-rc': {
        'linux-4.4.y': ['lkft-hikey-4.4-rc-p'],
        'linux-4.9.y': ['lkft-hikey-4.9-rc'],
        'linux-4.14.y': ['lkft-hikey-4.14-rc'],
        'linux-4.19.y': ['lkft-hikey-4.19-rc'],
        'linux-5.4.y': ['lkft-db845c-5.4-rc'],
        },

    # configs for hikey kernels
    'trigger-lkft-hikey-stable': {
        'android-4.4-o-hikey': ['lkft-hikey-4.4-o'],
        'android-4.4-p-hikey': ['lkft-hikey-4.4-p'],
        'android-4.9-o-hikey': ['lkft-hikey-4.9-o'],
        'android-4.9-p-hikey': ['lkft-hikey-aosp-4.9-premerge-ci'],
        'android-4.9-q-hikey': ['lkft-hikey-10.0-4.9-q'],
        'android-4.14-p-hikey': ['lkft-hikey-aosp-4.14-premerge-ci'],
        'android-4.14-q-hikey': ['lkft-hikey-10.0-4.14-q'],
        'android-4.19-q-hikey': ['lkft-hikey-android-10.0-gsi-4.19']
        },

    # configs for 4.14 kernels
    'trigger-lkft-hikey-4.14': {
        'android-hikey-linaro-4.14': ['lkft-hikey-android-8.1-4.14'],
        },

    # configs for hikey kernels
    'trigger-lkft-linaro-hikey': {
        'android-hikey-linaro-4.14-stable-lkft': ['lkft-generic-mirror-build'],
        'android-hikey-linaro-4.19-stable-lkft': ['lkft-generic-mirror-build'],
        },

    # configs for omap kernels
    'trigger-lkft-linaro-omap': {
        'android-beagle-x15-4.14-stable-lkft': ['lkft-generic-omap-build'],
        'android-beagle-x15-4.19-stable-lkft': ['lkft-generic-omap-build'],
        },

    'trigger-lkft-omap': {
        'android-beagle-x15-4.14': ['lkft-generic-omap-build'],
        'android-beagle-x15-4.19': ['lkft-generic-omap-build'],
        },
}

def get_supported_branches():
    branches = []
    triggers = trigger_branch_builds_info.keys()
    for trigger in triggers:
        trigger_branches = trigger_branch_builds_info.get(trigger)
        branches.extend(trigger_branches.keys())
    return branches

def find_expect_cibuilds(trigger_name=None, branch_name=None):
    if not trigger_name:
        return set([])
    branches = trigger_branch_builds_info.get(trigger_name)
    if branches is None:
        return set([])
    builds = branches.get(branch_name)
    if builds is None:
        return set([])
    return set(builds)

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
    elif pname.find('db845c') >= 0:
        return 'Dragonboard 845c'
    else:
        return 'Other'

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
    try:
        # For Python 3.0 and later
        from urllib.request import urlopen
        from urllib.error import HTTPError
    except ImportError:
        # Fall back to Python 2's urllib2
        from urllib2 import urlopen
        from urllib2 import HTTPError

    try:
        response = urlopen(url)
        return response.read().decode('utf-8')
    except HTTPError:
        pass

    return None


def get_configs(ci_build=None):
    build_name = ci_build.get('name')
    configs = []
    ci_build_actions = ci_build.get('actions')
    for action in ci_build_actions:
        class_name = action.get('_class')
        if class_name != 'hudson.model.ParametersAction':
            continue
        parameters = action.get('parameters')
        for parameter in parameters:
            para_class = parameter.get('_class')
            para_name = parameter.get('name')
            if para_class == 'hudson.model.StringParameterValue' \
                and para_name == 'ANDROID_BUILD_CONFIG':
                value = parameter.get('value')
                for config in ' '.join(value.split()).split():
                    configs.append((config, ci_build))

    return configs


def get_qa_server_project(lkft_build_config_name=None):
    # TEST_QA_SERVER=https://qa-reports.linaro.org
    # TEST_QA_SERVER_PROJECT=mainline-gki-aosp-master-hikey960
    # TEST_QA_SERVER_TEAM=android-lkft-rc
    # TEST_OTHER_PLANS="EXTRAS"
    # TEST_TEMPLATES_EXTRAS="template-cts-presubmit.yaml template-cts-presubmit-CtsDeqpTestCases.yaml template-cts-presubmit-CtsLibcoreOjTestCases.yaml"
    # TEST_QA_SERVER_PROJECT_EXTRAS=5.4-stable-gki-aosp-master-db845c-presubmit

    projects=[]

    url_build_config = "https://android-git.linaro.org/android-build-configs.git/plain/lkft/%s?h=lkft" % lkft_build_config_name
    content = get_url_content(url_build_config)
    if content is None:
        # the project had been deleted or not specified(like the gki build)
        return []

    content_dict={}
    for line in content.split('\n'):
        if line.startswith("#") or not line:
            continue
        key_value_array = line.split("=")
        key = key_value_array[0]
        value = " ".join(key_value_array[1:]).strip('"')
        content_dict[key.strip()] = value.strip()

    def_project = content_dict.get('TEST_QA_SERVER_PROJECT')
    def_team = content_dict.get('TEST_QA_SERVER_TEAM', 'android-lkft')
    if def_project is None:
        return projects
    else:
        projects.append((def_team, def_project))

    other_plans = content_dict.get('TEST_OTHER_PLANS')
    if other_plans is not None:
        for other_plan in other_plans.split(" "):
            project_key_name = "TEST_QA_SERVER_PROJECT_%s" % other_plan
            team_key_name = "TEST_QA_SERVER_TEAM_%s" % other_plan
            other_plan_project = content_dict.get(project_key_name)
            other_plan_team = content_dict.get(team_key_name, 'android-lkft')
            if other_plan_project is not None:
                projects.append((other_plan_team, other_plan_project))

    return projects
