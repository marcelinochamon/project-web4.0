# Generated by Django 4.0.3 on 2022-05-01 22:01

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('waitlist', '0009_config'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='config',
            name='number_of_servers',
        ),
    ]