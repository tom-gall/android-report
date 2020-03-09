# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys
import logging
import requests

try:
    from urllib import urlretrieve
    from urllib2 import HTTPError
except ImportError:
    from urllib.request import urlretrieve
    from urllib.error import HTTPError

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
        urlretrieve(url, path, Schedule)
        if not check_dict['file_not_exist']:
            logger.info("File is found: %s" % url)
    except HTTPError as error:
        if error.code == 404:
            logger.info("File is found: %s" % url)
        else:
            raise error

    if not check_dict['file_not_exist']:
        logger.info("File is saved to %s" % path)
    return check_dict['file_not_exist']
