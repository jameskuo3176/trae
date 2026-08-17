import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from django_app.core.db_routing import (
    PROJECT_MODEL_NAMES,
    _get_project_db_alias,
    get_project_engine,
    project_db_path,
)
from django_app.core.models import Project


CORE_INITIAL = ('core', '0001_initial')
CORE_ANNOTATIONS = ('core', '0005_record_annotations')
ANNOTATION_TABLES = {'record_annotations', 'record_annotation_images'}
LEGACY_NULL_COLUMNS = ('source_file', 'release_dir', 'version_description')


def _sqlite_affinity(declared_type):
    value = (declared_type or '').upper()
    if 'INT' in value:
        return 'INTEGER'
    if any(token in value for token in ('CHAR', 'CLOB', 'TEXT')):
        return 'TEXT'
    if 'BLOB' in value or not value:
        return 'BLOB'
    if any(token in value for token in ('REAL', 'FLOA', 'DOUB')):
        return 'REAL'
    return 'NUMERIC'


def _migration_models(connection, migration_name, included_names):
    executor = MigrationExecutor(connection)
    target = ('core', migration_name)
    state = executor.loader.project_state([target])
    migration = executor.loader.get_migration(*target)
    models = []
    for operation in migration.operations:
        name = getattr(operation, 'name', None)
        if name and name in included_names:
            models.append(state.apps.get_model('core', name))
    return models


def _unique_column_sets(cursor, table):
    unique_sets = set()
    indexes = list(cursor.execute(f'PRAGMA index_list("{table}")'))
    for index in indexes:
        if not index[2]:
            continue
        columns = tuple(
            row[2]
            for row in cursor.execute(f'PRAGMA index_info("{index[1]}")')
        )
        unique_sets.add(columns)
    return unique_sets


def _indexed_columns(cursor, table):
    indexed = set()
    indexes = list(cursor.execute(f'PRAGMA index_list("{table}")'))
    for index in indexes:
        columns = tuple(
            row[2]
            for row in cursor.execute(f'PRAGMA index_info("{index[1]}")')
        )
        indexed.update(columns)
    return indexed


def _validate_model_table(connection, model, allowed_null_columns=frozenset()):
    table = model._meta.db_table
    errors = []
    with connection.cursor() as cursor:
        columns = {
            row[1]: {
                'type': row[2],
                'notnull': bool(row[3]),
                'pk': bool(row[5]),
            }
            for row in cursor.execute(f'PRAGMA table_info("{table}")')
        }
        foreign_keys = {
            (row[3], row[2], row[4])
            for row in cursor.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        unique_sets = _unique_column_sets(cursor, table)
        indexed_columns = _indexed_columns(cursor, table)

        for field in model._meta.local_fields:
            column = field.column
            actual = columns.get(column)
            if actual is None:
                errors.append(f'{table}: missing column {column}')
                continue
            expected_type = field.db_type(connection)
            if _sqlite_affinity(actual['type']) != _sqlite_affinity(expected_type):
                errors.append(
                    f'{table}.{column}: type {actual["type"]!r} is not '
                    f'compatible with {expected_type!r}'
                )
            if field.primary_key and not actual['pk']:
                errors.append(f'{table}.{column}: expected primary key')
            if not field.null and not field.primary_key and not actual['notnull']:
                cursor.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL'
                )
                if cursor.fetchone()[0] and (table, column) not in allowed_null_columns:
                    errors.append(
                        f'{table}.{column}: contains NULL values but the '
                        'migration field is non-nullable'
                    )
            if field.is_relation and field.many_to_one:
                remote = field.remote_field.model._meta
                expected_fk = (
                    column,
                    remote.db_table,
                    field.target_field.column,
                )
                if expected_fk not in foreign_keys:
                    errors.append(
                        f'{table}.{column}: missing foreign key to '
                        f'{remote.db_table}.{field.target_field.column}'
                    )
            if field.unique and not field.primary_key:
                if (column,) not in unique_sets:
                    errors.append(f'{table}.{column}: missing unique constraint')
            elif field.db_index and column not in indexed_columns:
                errors.append(f'{table}.{column}: missing index')

        for field_names in model._meta.unique_together:
            expected = tuple(model._meta.get_field(name).column for name in field_names)
            if expected not in unique_sets:
                errors.append(
                    f'{table}: missing unique constraint on {expected}'
                )
    return errors


def _inspect_schema(connection, models, allowed_null_columns=frozenset()):
    tables = set(connection.introspection.table_names())
    present = [model for model in models if model._meta.db_table in tables]
    missing = [model for model in models if model._meta.db_table not in tables]
    errors = []
    for model in present:
        errors.extend(
            _validate_model_table(connection, model, allowed_null_columns)
        )
    return present, missing, errors


def _table_counts(connection):
    counts = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names():
            if table == 'django_migrations':
                continue
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cursor.fetchone()[0]
    return counts


def _legacy_null_counts(connection):
    with connection.cursor() as cursor:
        return {
            column: cursor.execute(
                f'SELECT COUNT(*) FROM qor_records WHERE "{column}" IS NULL'
            ).fetchone()[0]
            for column in LEGACY_NULL_COLUMNS
        }


def _non_target_digest(connection):
    with connection.cursor() as cursor:
        columns = [
            row[1]
            for row in cursor.execute('PRAGMA table_info("qor_records")')
            if row[1] not in LEGACY_NULL_COLUMNS
        ]
        select_columns = ', '.join(f'"{column}"' for column in columns)
        rows = cursor.execute(
            f'SELECT {select_columns} FROM qor_records ORDER BY id'
        )
        digest = hashlib.sha256()
        for row in rows:
            digest.update(repr(tuple(row)).encode('utf-8'))
            digest.update(b'\n')
        return digest.hexdigest()


def _nonnull_target_values(connection):
    with connection.cursor() as cursor:
        return {
            column: dict(
                cursor.execute(
                    f'SELECT id, "{column}" FROM qor_records '
                    f'WHERE "{column}" IS NOT NULL ORDER BY id'
                )
            )
            for column in LEGACY_NULL_COLUMNS
        }


def _normalize_legacy_nulls(connection, expected_counts):
    updated = {}
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            current = _legacy_null_counts(connection)
            if current != expected_counts:
                raise CommandError(
                    f'{connection.alias}: legacy NULL counts changed after audit; '
                    f'expected {expected_counts}, found {current}'
                )
            for column in LEGACY_NULL_COLUMNS:
                cursor.execute(
                    f'UPDATE qor_records SET "{column}" = %s '
                    f'WHERE "{column}" IS NULL',
                    [''],
                )
                updated[column] = cursor.rowcount
            if updated != expected_counts:
                raise CommandError(
                    f'{connection.alias}: normalized counts {updated} do not '
                    f'match audited counts {expected_counts}'
                )
    return updated


def _database_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_database(path, backup_dir):
    destination = backup_dir / path.name
    source = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    backup = sqlite3.connect(destination)
    try:
        source.backup(backup)
        backup.commit()
        source_check = source.execute('PRAGMA quick_check').fetchone()[0]
        backup_check = backup.execute('PRAGMA integrity_check').fetchone()[0]
        source_tables = {
            row[0]: source.execute(
                f'SELECT COUNT(*) FROM "{row[0]}"'
            ).fetchone()[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        backup_tables = {
            row[0]: backup.execute(
                f'SELECT COUNT(*) FROM "{row[0]}"'
            ).fetchone()[0]
            for row in backup.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        source.close()
        backup.close()
    if source_check != 'ok' or backup_check != 'ok' or source_tables != backup_tables:
        destination.unlink(missing_ok=True)
        raise CommandError(f'Backup verification failed for {path}')
    return destination, _database_digest(destination), destination.stat().st_size


class Command(BaseCommand):
    help = (
        'Safely reconcile legacy project SQLite schemas, back them up, and '
        'apply project migrations.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int, action='append', dest='project_ids')
        parser.add_argument(
            '--check',
            action='store_true',
            help='Inspect compatibility and pending migrations without writing.',
        )
        parser.add_argument(
            '--backup-root',
            help='Backup parent directory (default: DATA_DIR/migration-backups).',
        )
        parser.add_argument(
            '--normalize-legacy-nulls',
            action='store_true',
            help=(
                'After verified backups, convert NULL source_file, release_dir, '
                'and version_description values to empty strings.'
            ),
        )

    def handle(self, *args, **options):
        projects = Project.objects.using('default').order_by('id')
        if options['project_ids']:
            projects = projects.filter(id__in=options['project_ids'])
        inspections = []
        incompatibilities = []
        for project in projects:
            path = Path(project_db_path(project.id))
            if not path.is_file():
                raise CommandError(
                    f'Project {project.id} database does not exist: {path}'
                )
            connection = get_project_engine(project.id)
            alias = _get_project_db_alias(project.id)
            initial_models = _migration_models(
                connection,
                CORE_INITIAL[1],
                PROJECT_MODEL_NAMES - {'RecordAnnotation', 'RecordAnnotationImage'},
            )
            annotation_models = _migration_models(
                connection,
                CORE_ANNOTATIONS[1],
                {'RecordAnnotation', 'RecordAnnotationImage'},
            )
            null_counts = _legacy_null_counts(connection)
            allowed_null_columns = (
                {('qor_records', column) for column in LEGACY_NULL_COLUMNS}
                if options['normalize_legacy_nulls']
                else frozenset()
            )
            initial_present, initial_missing, initial_errors = _inspect_schema(
                connection, initial_models, allowed_null_columns,
            )
            annotation_present, annotation_missing, annotation_errors = _inspect_schema(
                connection, annotation_models,
            )
            errors = initial_errors + annotation_errors
            if errors:
                incompatibilities.append((project, errors))
            applied = MigrationRecorder(connection).applied_migrations()
            baseline = _table_counts(connection)
            executor = MigrationExecutor(connection)
            pending = bool(
                executor.migration_plan(executor.loader.graph.leaf_nodes())
            )
            inspections.append({
                'project': project,
                'alias': alias,
                'path': path,
                'connection': connection,
                'initial_models': initial_models,
                'initial_present': initial_present,
                'initial_missing': initial_missing,
                'annotation_models': annotation_models,
                'annotation_present': annotation_present,
                'annotation_missing': annotation_missing,
                'applied': applied,
                'baseline': baseline,
                'null_counts': null_counts,
                'non_target_digest': _non_target_digest(connection),
                'nonnull_target_values': _nonnull_target_values(connection),
                'pending': pending,
            })
            self.stdout.write(
                f'Project {project.id} ({project.name}): '
                f'core history through '
                f'{max((name for app, name in applied if app == "core"), default="none")}; '
                f'historical tables {len(initial_present)}/{len(initial_models)}; '
                f'annotation tables {len(annotation_present)}/{len(annotation_models)}; '
                f'legacy NULLs {null_counts}.'
            )

        if incompatibilities:
            details = '\n'.join(
                f'Project {project.id} ({project.name}):\n  '
                + '\n  '.join(errors)
                for project, errors in incompatibilities
            )
            raise CommandError(
                'Incompatible project schemas found; no project database was '
                f'changed:\n{details}'
            )

        if options['check']:
            pending_projects = [
                item['project'] for item in inspections if item['pending']
            ]
            if pending_projects:
                self.stdout.write(self.style.WARNING(
                    'Pending project migrations: '
                    + ', '.join(
                        f'{project.id} ({project.name})'
                        for project in pending_projects
                    )
                    + '. Run migrate_project_databases without --check to apply.'
                ))
            self.stdout.write(self.style.SUCCESS(
                f'Compatible project schemas: {len(inspections)}; '
                f'pending migrations: {len(pending_projects)}; no changes made.'
            ))
            return

        needs_mutation = any(
            item['pending']
            or item['initial_missing']
            or item['annotation_missing'] and item['annotation_present']
            or (
                options['normalize_legacy_nulls']
                and any(item['null_counts'].values())
            )
            for item in inspections
        )
        backup_dir = None
        if needs_mutation:
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            backup_root = Path(
                options['backup_root']
                or Path(settings.DATA_DIR) / 'migration-backups'
            )
            backup_dir = backup_root / f'project-migration-{timestamp}'
            backup_dir.mkdir(parents=True, exist_ok=False)
            connections.close_all()
            self.stdout.write(f'Creating verified backups in {backup_dir}...')
            for item in inspections:
                backup_path, digest, size = _backup_database(
                    item['path'], backup_dir,
                )
                self.stdout.write(
                    f'  project {item["project"].id}: {backup_path.name}; '
                    f'{size} bytes; sha256 {digest}'
                )
        else:
            self.stdout.write('No database changes are pending; backup not required.')

        for item in inspections:
            project = item['project']
            alias = item['alias']
            connection = item['connection']
            self.stdout.write(f'Migrating project {project.id} ({project.name})...')

            if options['normalize_legacy_nulls']:
                normalized = _normalize_legacy_nulls(
                    connection, item['null_counts'],
                )
                self.stdout.write(
                    f'  project {project.id}: normalized legacy NULLs {normalized}.'
                )

            if CORE_INITIAL not in item['applied']:
                # Satisfy the initial migration's auth dependency without
                # creating global/auth tables in the project database.
                call_command(
                    'migrate',
                    'auth',
                    '0012_alter_user_first_name_max_length',
                    database=alias,
                    interactive=False,
                    verbosity=0,
                )

            if item['initial_missing']:
                with connection.schema_editor() as schema_editor:
                    for model in item['initial_missing']:
                        schema_editor.create_model(model)
            _, missing, errors = _inspect_schema(
                connection, item['initial_models'],
            )
            if missing or errors:
                raise CommandError(
                    f'Historical schema reconciliation failed for project '
                    f'{project.id}: missing={[m._meta.db_table for m in missing]}, '
                    f'errors={errors}'
                )
            if CORE_INITIAL not in MigrationRecorder(connection).applied_migrations():
                MigrationRecorder(connection).record_applied(*CORE_INITIAL)

            # These migrations contain only global models/operations for a
            # project DB. Django records them while the router skips the SQL.
            call_command(
                'migrate',
                'core',
                '0004_repair_backup_user_column',
                database=alias,
                interactive=False,
                verbosity=0,
            )

            applied = MigrationRecorder(connection).applied_migrations()
            annotation_present, annotation_missing, annotation_errors = _inspect_schema(
                connection, item['annotation_models'],
            )
            if annotation_errors:
                raise CommandError(
                    f'Annotation schema became incompatible for project '
                    f'{project.id}: {annotation_errors}'
                )
            if annotation_present or CORE_ANNOTATIONS in applied:
                if annotation_missing:
                    with connection.schema_editor() as schema_editor:
                        for model in annotation_missing:
                            schema_editor.create_model(model)
                _, missing, errors = _inspect_schema(
                    connection, item['annotation_models'],
                )
                if missing or errors:
                    raise CommandError(
                        f'Annotation reconciliation failed for project '
                        f'{project.id}: missing={[m._meta.db_table for m in missing]}, '
                        f'errors={errors}'
                    )
                if CORE_ANNOTATIONS not in applied:
                    MigrationRecorder(connection).record_applied(*CORE_ANNOTATIONS)

            call_command(
                'migrate',
                database=alias,
                interactive=False,
                verbosity=max(0, options['verbosity'] - 1),
            )
            tables = set(connection.introspection.table_names())
            if not ANNOTATION_TABLES.issubset(tables):
                raise CommandError(
                    f'Project {project.id} is missing annotation tables after migration'
                )
            final_counts = _table_counts(connection)
            changed_counts = {
                table: (count, final_counts.get(table))
                for table, count in item['baseline'].items()
                if final_counts.get(table) != count
            }
            if changed_counts:
                raise CommandError(
                    f'Pre-existing row counts changed for project {project.id}: '
                    f'{changed_counts}'
                )
            final_null_counts = _legacy_null_counts(connection)
            if any(final_null_counts.values()):
                raise CommandError(
                    f'Project {project.id} still has legacy NULLs: '
                    f'{final_null_counts}'
                )
            if _non_target_digest(connection) != item['non_target_digest']:
                raise CommandError(
                    f'Non-target qor_records data changed for project {project.id}'
                )
            with connection.cursor() as cursor:
                for column, values in item['nonnull_target_values'].items():
                    for record_id, expected in values.items():
                        cursor.execute(
                            f'SELECT "{column}" FROM qor_records WHERE id = %s',
                            [record_id],
                        )
                        row = cursor.fetchone()
                        if row is None or row[0] != expected:
                            raise CommandError(
                                f'Non-NULL value changed for project {project.id}: '
                                f'qor_records[{record_id}].{column}'
                            )
            final_applied = MigrationRecorder(connection).applied_migrations()
            if CORE_ANNOTATIONS not in final_applied:
                raise CommandError(
                    f'Project {project.id} did not record core 0005'
                )
            final_executor = MigrationExecutor(connection)
            pending = final_executor.migration_plan(
                final_executor.loader.graph.leaf_nodes()
            )
            if pending:
                raise CommandError(
                    f'Project {project.id} still has pending migrations: {pending}'
                )
            self.stdout.write(self.style.SUCCESS(
                f'  project {project.id}: core 0005 applied; row counts preserved.'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'Migrated {len(inspections)} project database(s). '
            f'Backups: {backup_dir or "not required"}'
        ))
