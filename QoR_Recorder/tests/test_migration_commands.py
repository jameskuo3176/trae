from io import StringIO

import pytest
from django.core.management import call_command

from django_app.core.models import GlobalModule


@pytest.mark.django_db
def test_global_module_migration_is_dry_run_by_default():
    output = StringIO()
    call_command('migrate_global_modules', stdout=output)
    assert 'DRY-RUN' in output.getvalue()
    assert GlobalModule.objects.count() == 0


@pytest.mark.django_db
def test_sqlite_to_mongo_dry_run_does_not_connect():
    output = StringIO()
    call_command('migrate_sqlite_to_mongo', stdout=output)
    assert 'DRY-RUN' in output.getvalue()
