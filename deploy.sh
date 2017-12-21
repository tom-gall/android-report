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
pip install Django=1.11.8
pip install pyaml
pip install lava-tool
pip install django-crispy-forms

# https://docs.djangoproject.com/en/1.11/intro/tutorial01/
python -m django --version
#python manage.py startapp ${instance_report_app}
# django-admin startproject ${instance_name}
cd ${work_root} && git clone https://git.linaro.org/people/yongqin.liu/public/lcr-report.git
cd ${instance_dir} && python manage.py runserver 0.0.0.0:8000
echo "Please update the LAVA_USER_TOKEN and LAVA_USER in report/views.py"

# python manage.py createsuperuser
# By running makemigrations, you’re telling Django that you’ve made some changes to your models (in this case,
# you’ve made new ones) and that you’d like the changes to be stored as a migration.
# python manage.py makemigrations report

# The migrate command looks at the INSTALLED_APPS setting and creates any necessary database tables according to the database settings
# in your mysite/settings.py file and the database migrations shipped with the app (we’ll cover those later)
# Need to run after makemigrations so that the tables for report could be created
# python manage.py migrate

# There’s a command that will run the migrations for you and manage your database schema automatically - that’s called migrate,
# and we’ll come to it in a moment - but first, let’s see what SQL that migration would run.
# The sqlmigrate command takes migration names and returns their SQL:
# Only shows the sql script, not creation
# python manage.py sqlmigrate report 0002

