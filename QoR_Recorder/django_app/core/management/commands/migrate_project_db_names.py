import os
import re
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from django_app.core.db_routing import (
    PROJECT_DB_PREFIX,
    _get_project_db_alias,
    _project_engines,
)
from django_app.core.models import Project
from django_app.services.backup_service import perform_backup


def _safe_project_name(project):
    value = re.sub(r'[^A-Za-z0-9._-]+', '_', project.name).strip('._-')
    return value or f'project_{project.id}'


def _checkpoint(path):
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        connection.close()


class Command(BaseCommand):
    help = 'Rename qor_p_<id>.db files to <project>_syn_qor.db safely.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Create a backup and apply the rename. Default is dry-run.',
        )

    def handle(self, *args, **options):
        data_dir = os.path.abspath(str(settings.DATA_DIR))
        plan = []
        destinations = set()
        for project in Project.objects.order_by('id'):
            source = os.path.join(data_dir, f'{PROJECT_DB_PREFIX}{project.id}.db')
            destination = os.path.join(
                data_dir, f'{_safe_project_name(project)}_syn_qor.db',
            )
            if destination in destinations:
                raise CommandError(f'duplicate destination: {destination}')
            destinations.add(destination)
            if os.path.abspath(source) == os.path.abspath(destination):
                continue
            if not os.path.exists(source):
                if os.path.exists(destination):
                    plan.append((project, None, destination))
                    continue
                raise CommandError(f'project {project.name}: source database missing: {source}')
            if os.path.exists(destination):
                raise CommandError(f'project {project.name}: destination already exists: {destination}')
            plan.append((project, source, destination))

        for project, source, destination in plan:
            operation = 'metadata' if source is None else 'rename'
            self.stdout.write(
                f'{operation}: {project.name}: {source or "(already renamed)"} -> {destination}'
            )
        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'DRY-RUN: {len(plan)} project databases; use --apply to execute.'
            ))
            return

        backup = perform_backup(backup_type='pre_db_rename')
        if not backup.get('ok'):
            raise CommandError(f'pre-migration backup failed: {backup.get("error")}')
        self.stdout.write(f'backup: {backup["file_path"]}')

        renamed = []
        try:
            for project, source, destination in plan:
                alias = _get_project_db_alias(project.id)
                if alias in connections.databases:
                    connections[alias].close()
                    connections.databases.pop(alias, None)
                _project_engines.pop(project.id, None)
                if source:
                    _checkpoint(source)
                    os.replace(source, destination)
                    renamed.append((source, destination))
                project.db_path = destination
                project.save(update_fields=['db_path'])
        except Exception:
            for source, destination in reversed(renamed):
                if os.path.exists(destination) and not os.path.exists(source):
                    os.replace(destination, source)
            raise

        self.stdout.write(self.style.SUCCESS(
            f'Renamed and registered {len(plan)} project databases.'
        ))
