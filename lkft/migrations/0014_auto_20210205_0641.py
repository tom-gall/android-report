# -*- coding: utf-8 -*-
# Generated by Django 1.11.17 on 2021-02-05 06:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lkft', '0013_auto_20210202_0712'),
    ]

    operations = [
        migrations.CreateModel(
            name='TestCase',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
                ('result', models.CharField(max_length=16)),
                ('measurement', models.DecimalField(decimal_places=2, max_digits=20, null=True)),
                ('unit', models.CharField(max_length=128, null=True)),
                ('suite', models.CharField(max_length=64)),
                ('job_id', models.CharField(max_length=16)),
                ('lava_nick', models.CharField(max_length=64)),
            ],
        ),
        migrations.AddField(
            model_name='reportjob',
            name='results_cached',
            field=models.BooleanField(default=False),
        ),
    ]