"""Copy Django metadata from the legacy main SQLite database to PostgreSQL."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connections, transaction


SOURCE_ALIAS = 'legacy_metadata'
EXCLUDED_MODELS = {
    'contenttypes.contenttype',
    'auth.permission',
    'sessions.session',
}


def _source_config(path):
    return {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(path),
        'OPTIONS': {'timeout': 30},
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'TIME_ZONE': settings.TIME_ZONE,
        'TEST': {
            'CHARSET': None, 'COLLATION': None, 'MIGRATE': False,
            'MIRROR': None, 'NAME': None,
        },
    }


class Command(BaseCommand):
    help = (
        'Copy legacy Django metadata from SQLite into an empty migrated '
        'PostgreSQL database; dry-run unless --execute is supplied.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            default=str(Path(settings.DATA_DIR) / 'qor_recorder.db'),
            help='Legacy main SQLite database path.',
        )
        parser.add_argument('--execute', action='store_true')
        parser.add_argument(
            '--fixture-out',
            help='Keep the generated JSON fixture at this path for audit.',
        )

    def handle(self, *args, **options):
        target = connections['default']
        if target.vendor != 'postgresql':
            raise CommandError(
                'The default database must be PostgreSQL. Set DATABASE_URL or '
                'POSTGRES_* before running this command.'
            )
        source_path = Path(options['source']).expanduser().resolve()
        if not source_path.is_file():
            raise CommandError(f'Source SQLite database does not exist: {source_path}')

        connections.databases[SOURCE_ALIAS] = _source_config(source_path)
        source = connections[SOURCE_ALIAS]
        with source.cursor() as cursor:
            cursor.execute('PRAGMA integrity_check')
            integrity = cursor.fetchone()[0]
        if integrity != 'ok':
            raise CommandError(f'Source SQLite integrity_check failed: {integrity}')

        source_tables = set(source.introspection.table_names())
        labels = []
        counts = {}
        target_conflicts = {}
        for model in apps.get_models():
            label = model._meta.label_lower
            if label in EXCLUDED_MODELS or model._meta.proxy:
                continue
            if model._meta.db_table not in source_tables:
                continue
            count = model._base_manager.using(SOURCE_ALIAS).count()
            if not count:
                continue
            labels.append(label)
            counts[label] = count
            target_count = model._base_manager.using('default').count()
            if target_count:
                target_conflicts[label] = target_count

        self.stdout.write(
            f'source={source_path} integrity=ok models={len(labels)} '
            f'rows={sum(counts.values())}'
        )
        self.stdout.write(json.dumps(counts, ensure_ascii=False, sort_keys=True))
        if not options['execute']:
            self.stdout.write(self.style.SUCCESS('DRY-RUN: PostgreSQL was not changed.'))
            return
        if target_conflicts:
            raise CommandError(
                'Target PostgreSQL contains business data; refusing to merge. '
                f'Use a fresh migrated database. Conflicts: {target_conflicts}'
            )

        fixture_out = options['fixture_out']
        temporary = None
        if fixture_out:
            fixture_path = Path(fixture_out).expanduser().resolve()
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.NamedTemporaryFile(
                prefix='qor-metadata-', suffix='.json', delete=False,
            )
            temporary.close()
            fixture_path = Path(temporary.name)

        try:
            with fixture_path.open('w', encoding='utf-8') as stream:
                call_command(
                    'dumpdata',
                    *labels,
                    database=SOURCE_ALIAS,
                    format='json',
                    use_natural_foreign_keys=True,
                    use_natural_primary_keys=True,
                    indent=2,
                    stdout=stream,
                )
            with transaction.atomic(using='default'):
                call_command(
                    'loaddata', str(fixture_path), database='default',
                    verbosity=max(0, options['verbosity'] - 1),
                )
                mismatches = {}
                for label, expected in counts.items():
                    model = apps.get_model(label)
                    actual = model._base_manager.using('default').count()
                    if actual != expected:
                        mismatches[label] = {'source': expected, 'target': actual}
                if mismatches:
                    raise CommandError(f'Post-load count mismatch: {mismatches}')
        finally:
            connections[SOURCE_ALIAS].close()
            if temporary:
                fixture_path.unlink(missing_ok=True)

        self.stdout.write(self.style.SUCCESS(
            f'EXECUTED: copied {sum(counts.values())} rows across '
            f'{len(counts)} models; count verification passed.'
        ))
