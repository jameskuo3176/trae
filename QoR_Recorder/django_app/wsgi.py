"""
WSGI config for django_app project.
"""

import logging
import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')

application = get_wsgi_application()

logging.getLogger('django_app').info(
    'WSGI ready pid=%s DEBUG=%s LOG_LEVEL=%s LOG_FILE=%s',
    os.getpid(),
    getattr(settings, 'DEBUG', False),
    getattr(settings, 'LOG_LEVEL', 'INFO'),
    getattr(settings, 'LOG_FILE', ''),
)