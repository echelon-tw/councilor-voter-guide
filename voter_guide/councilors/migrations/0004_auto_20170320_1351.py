# -*- coding: utf-8 -*-
# Generated by Django 1.9.4 on 2017-03-20 13:51
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('councilors', '0003_councilors_identifiers'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='councilorsdetail',
            unique_together=set([('councilor', 'election_year')]),
        ),
    ]
