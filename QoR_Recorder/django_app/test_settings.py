"""Isolated SQLite settings used only by the test runner."""
import os

os.environ.setdefault('DB_TYPE', 'sqlite')
os.environ.setdefault('PERSISTENCE_MODE', 'orm')

from django_app.settings import *  # noqa: F403,E402
