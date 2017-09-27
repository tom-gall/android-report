#!/bin/bash

if [ -d "${work_root}" ]; then
    work_root=${work_root}
elif [ -d /sata250/django_instances ]; then
    work_root="/sata250/django_instances"
elif [ -d /SATA3/django_instances ]; then
    work_root="/SATA3/django_instances"
elif [ -d /home/yongqin.liu/django_instance ]; then
    work_root="/home/yongqin.liu/django_instance"
else
    echo "Please set the path for work_root"
    exit 1
fi

instance_name="lcr-report"
instance_report_app="report"

virenv_dir="/${work_root}/workspace"
instance_dir="/${work_root}/${instance_name}"
mkdir -p ${virenv_dir} 
cd ${virenv_dir}
# https://pip.pypa.io/en/latest/installing/#installing-with-get-pip-py
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
sudo python get-pip.py

# https://virtualenv.pypa.io/en/stable/
sudo pip install virtualenv
virtualenv ${virenv_dir}
source ${virenv_dir}/bin/activate

#(ENV)$ deactivate
#$ rm -r /path/to/ENV

#https://docs.djangoproject.com/en/1.11/topics/install/#installing-official-release
pip install Django
pip install pyaml
pip install lava-tool

# https://docs.djangoproject.com/en/1.11/intro/tutorial01/
python -m django --version
#python manage.py startapp ${instance_report_app}
# django-admin startproject ${instance_name}
cd ${work_root} && git clone https://git.linaro.org/people/yongqin.liu/public/lcr-report.git
cd ${instance_dir} && python manage.py runserver 0.0.0.0:8000
echo "Please update the LAVA_USER_TOKEN and LAVA_USER in report/views.py"
