#!/bin/bash -ex

dir_parent=$(cd $(dirname $0); pwd)

${dir_parent}/../workspace-python3/bin/python ${dir_parent}/../lcr-report/manage.py lkftreport
