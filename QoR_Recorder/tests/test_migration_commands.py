from io import StringIO
import importlib
import sqlite3
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import connection

from django_app.core.management.commands.migrate_project_databases import (
    _backup_database,
    _legacy_null_counts,
    _normalize_legacy_nulls,
)
from django_app.core.models import GlobalModule
from django_app.core.db_routing import _get_project_db_alias, get_project_engine


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


def test_postgresql_url_settings_are_parsed_without_sqlite_fallback(monkeypatch):
    from django_app import settings as app_settings

    monkeypatch.setattr(app_settings, 'DB_TYPE', app_settings.DB_TYPE_SQL)
    monkeypatch.setenv(
        'DATABASE_URL',
        'postgresql://qor:p%40ss@db.internal:55432/qor_meta?sslmode=require',
    )
    config = app_settings._build_database_config()['default']
    assert config['ENGINE'] == 'django.db.backends.postgresql'
    assert config['NAME'] == 'qor_meta'
    assert config['PASSWORD'] == 'p@ss'
    assert config['HOST'] == 'db.internal'
    assert config['PORT'] == '55432'
    assert config['OPTIONS'] == {'sslmode': 'require'}


@pytest.mark.django_db
def test_mongo_runtime_routes_project_models_to_relational_default(settings):
    settings.PERSISTENCE_MODE = 'mongo'
    assert _get_project_db_alias(123) == 'default'
    assert get_project_engine(123).alias == 'default'


@pytest.mark.django_db(transaction=True)
def test_legacy_null_normalization_changes_only_null_values():
    with connection.cursor() as cursor:
        cursor.execute(
            'CREATE TABLE qor_records ('
            'id INTEGER PRIMARY KEY, source_file TEXT, release_dir TEXT, '
            'version_description TEXT, preserved TEXT)'
        )
        cursor.execute(
            'INSERT INTO qor_records VALUES '
            "(1, NULL, NULL, NULL, 'keep-1'), "
            "(2, 'source', 'release', 'description', 'keep-2')"
        )
    expected = {
        'source_file': 1,
        'release_dir': 1,
        'version_description': 1,
    }
    assert _legacy_null_counts(connection) == expected
    assert _normalize_legacy_nulls(connection, expected) == expected
    with connection.cursor() as cursor:
        rows = list(cursor.execute(
            'SELECT source_file, release_dir, version_description, preserved '
            'FROM qor_records ORDER BY id'
        ))
    assert rows == [
        ('', '', '', 'keep-1'),
        ('source', 'release', 'description', 'keep-2'),
    ]


def test_project_migration_backup_is_verified(tmp_path):
    source = tmp_path / 'project.db'
    backup_dir = tmp_path / 'migration-backup'
    backup_dir.mkdir()
    database = sqlite3.connect(source)
    database.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)')
    database.execute("INSERT INTO records (value) VALUES ('preserved')")
    database.commit()
    database.close()

    destination, digest, size = _backup_database(source, backup_dir)

    assert destination.is_file()
    assert len(digest) == 64
    assert size == destination.stat().st_size
    copied = sqlite3.connect(destination)
    try:
        assert copied.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert copied.execute('SELECT value FROM records').fetchone() == ('preserved',)
    finally:
        copied.close()


def test_weekly_selection_source_repair_is_idempotent():
    migration = importlib.import_module(
        'django_app.core.migrations.0009_repair_weekly_selection_source'
    )
    field = SimpleNamespace(column='source')
    model = SimpleNamespace(_meta=SimpleNamespace(
        db_table='weekly_run_selections',
        get_field=lambda name: field,
    ))
    apps = SimpleNamespace(get_model=lambda app, name: model)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Introspection:
        def __init__(self, columns):
            self.columns = columns

        def table_names(self):
            return ['weekly_run_selections']

        def get_table_description(self, cursor, table):
            return [SimpleNamespace(name=name) for name in self.columns]

    def run(columns):
        connection = SimpleNamespace(
            alias='default',
            introspection=Introspection(columns),
            cursor=lambda: Cursor(),
        )
        added = []
        schema_editor = SimpleNamespace(
            connection=connection,
            add_field=lambda target_model, target_field: added.append(
                (target_model, target_field)
            ),
        )
        migration.repair_weekly_selection_source(apps, schema_editor)
        return added

    assert run(['id', 'record_id']) == [(model, field)]
    assert run(['id', 'record_id', 'source']) == []
