"""WSGI entry point for Passenger (cPanel / Spaceship shared hosting).

Passenger imports this file directly. It neither reads the Dockerfile nor uses
gunicorn - `gunicorn` in requirements.txt exists for the container runtime and is
unused here. Do not add a `run` callable: that is Passenger's WSGI/worker
protocol, and Django's application object is what it wants.

The two lines that matter are the path insert and the settings module. Passenger
starts the process with an unpredictable working directory, so relying on the
current directory to find `hrcloudpay/` fails in a way that looks like a missing
package rather than a path problem.

Deploy as: one Passenger (WSGI) application, Application root = the directory
holding this file and `manage.py`.
"""
import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hrcloudpay.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()