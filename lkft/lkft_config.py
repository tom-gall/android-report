# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re

citrigger_lkft = {
    'trigger-lkft-aosp-mainline': [
        'mainline-9.0-hikey',
        'mainline-9.0-hikey-auto',
        'mainline-9.0-hikey960',
        'mainline-9.0-hikey960-auto',
        'mainline-9.0-x15',
        'mainline-9.0-x15-auto',
        ],

    'trigger-lkft-ti-4.19': [
        '4.19-9.0-x15',
        '4.19-9.0-x15-auto',
        '4.19-9.0-am65x',
        '4.19-9.0-am65x-auto',
        ],
    'trigger-lkft-hikey-4.19': [
        '4.19-9.0-hikey',
        '4.19-9.0-hikey-auto',
        '4.19-9.0-hikey960',
        '4.19-9.0-hikey960-auto',
        ],

    'trigger-lkft-x15-4.14': [
        '4.14-8.1-x15',
        ],
    'trigger-lkft-hikey-4.14-premerge-ci': [
        '4.14-9.0-hikey',
        '4.14-9.0-hikey960',
        ],
    'trigger-lkft-hikey-4.14': [
        '4.14-8.1-hikey',
        ],

    'trigger-lkft-hikey-4.9-premerge-ci': [
        '4.9-9.0-hikey',
        '4.9-9.0-hikey960',
        ],
    'trigger-lkft-hikey-4.9': [
        '4.9-8.1-hikey',
        ],

    'trigger-lkft-hikey-4.4-premerge-ci': [
        '4.4-lts-9.0-hikey',
        ],
    'trigger-lkft-hikey-4.4': [
        '4.4-8.1-hikey',
        '4.4-9.0-hikey',
        ],
}

def find_citrigger(lkft_pname=""):
    if not lkft_pname:
        return None
    for trigger_name, lkft_pnames in citrigger_lkft.items():
        if lkft_pname in lkft_pnames:
            return trigger_name
    return None
