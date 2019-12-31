#!/bin/bash -ex

dir_parent=$(cd $(dirname $0); pwd)

${dir_parent}/../workspace/bin/python ${dir_parent}/../lcr-report/manage.py lkftreport
