# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys
import logging
import requests

logger = logging.getLogger(__name__)

def download_urllib(url, path):
    check_dict = {'file_not_exist': False}
    import urllib
    def Schedule(a,b,c):
        '''
        a: the number downloaded of blocks
        b: the size of the block
        c: the size of the file
        '''
        if c == -1:
            #global file_not_exist
            check_dict['file_not_exist'] = True
            return

        per = 100.0 * a * b / c
        if per > 100 :
            per = 100
            sys.stdout.write("\r %.2f%%" % per)
            sys.stdout.flush()
            sys.stdout.write('\n')
        else:
            sys.stdout.write("\r %.2f%%" % per)
            sys.stdout.flush()
    try:
        urllib.urlretrieve(url, path, Schedule)
    except AttributeError:
        urllib.request.urlretrieve(url, path, Schedule)

    if not check_dict['file_not_exist']:
        logger.info("File is saved to %s" % path)
    return check_dict['file_not_exist']
