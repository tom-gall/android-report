# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re

citrigger_lkft = {
    'lkft-aosp-master-cts-vts': {
        'aosp-master-tracking':'lkft-aosp-master-tracking',
        'aosp-master-tracking-x15':'lkft-aosp-master-x15',
        },

    'trigger-lkft-aosp-mainline': {
        'mainline-9.0-x15': 'lkft-android-9.0-mainline-x15',
        'mainline-9.0-x15-auto': 'lkft-android-9.0-mainline-x15',
        'mainline-aosp-master-x15': 'lkft-x15-aosp-master-mainline',

        'mainline-gki-aosp-master-db845c': 'lkft-db845c-aosp-master-mainline',
        'mainline-aosp-master-db845c': 'lkft-db845c-aosp-master-mainline',

        'mainline-gki-aosp-master-hikey': 'lkft-hikey-aosp-master-mainline-gki',
        'mainline-aosp-master-hikey': 'lkft-hikey-aosp-master-mainline-gki',
        'mainline-gki-aosp-master-hikey960': 'lkft-hikey960-aosp-master-mainline-gki',
        'mainline-aosp-master-hikey960': 'lkft-hikey960-aosp-master-mainline-gki',
        },

    'trigger-lkft-android-common': {
        '5.4-gki-aosp-master-hikey': 'lkft-hikey-aosp-master-5.4',
        '5.4-gki-aosp-master-hikey960': 'lkft-hikey960-aosp-master-5.4',
        '5.4-gki-aosp-master-db845c': 'lkft-db845c-aosp-master-5.4',
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

def find_citrigger(lkft_pname=""):
    if not lkft_pname:
        return None
    for trigger_name, lkft_pnames in citrigger_lkft.items():
        if lkft_pname in lkft_pnames.keys():
            return trigger_name
    return None


def find_cibuild(lkft_pname=""):
    if not lkft_pname:
        return None
    if lkft_pname == 'aosp-master-tracking':
        return 'lkft-aosp-master-tracking'
    for trigger_name, lkft_pnames in citrigger_lkft.items():
        if lkft_pname in lkft_pnames.keys():
            return lkft_pnames.get(lkft_pname)
    return None

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
