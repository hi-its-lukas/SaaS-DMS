import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dms_project.settings')

if __name__ == '__main__':
    from django.core.management import execute_from_command_line
    execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:5000'])
