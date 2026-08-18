"""Create canonical module metadata without changing project databases."""
from contextlib import nullcontext

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from django_app.core.db_routing import (
    _get_legacy_project_db_alias, get_legacy_project_engine,
)
from django_app.core.models import (
    GlobalModule, LegacyModuleMapping, Module, Project, ProjectModule,
    normalize_module_name,
)


class Command(BaseCommand):
    help = 'Map legacy project-local modules to global modules (dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='persist mappings')
        parser.add_argument('--project-id', type=int)

    def handle(self, *args, **options):
        execute = options['execute']
        projects = Project.objects.all().order_by('id')
        if options['project_id']:
            projects = projects.filter(pk=options['project_id'])
            if not projects.exists():
                raise CommandError('project not found')
        report = {'projects': 0, 'legacy_modules': 0, 'global_modules': 0, 'mappings': 0}
        for project in projects:
            get_legacy_project_engine(project.id)
            alias = _get_legacy_project_db_alias(project.id)
            legacy_rows = list(Module.objects.using(alias).all().order_by('id'))
            report['projects'] += 1
            report['legacy_modules'] += len(legacy_rows)
            self.stdout.write(f'project={project.id} modules={len(legacy_rows)}')
            seen = set()
            # Every project's mappings are one relational transaction. Legacy
            # project databases are read-only, so rollback is single-database.
            scope = transaction.atomic(using='default') if execute else nullcontext()
            with scope:
                for legacy in legacy_rows:
                    key = normalize_module_name(legacy.name)
                    seen.add(key)
                    if execute:
                        canonical, _ = GlobalModule.objects.get_or_create(
                            normalized_name=key,
                            defaults={'name': legacy.name, 'description': legacy.description},
                        )
                        ProjectModule.objects.get_or_create(
                            project=project, module=canonical,
                            defaults={
                                'owner_id': legacy.owner_id,
                                'collaborators': legacy.collaborators,
                            },
                        )
                        _, created = LegacyModuleMapping.objects.get_or_create(
                            project=project,
                            legacy_module_id=legacy.id,
                            defaults={'module': canonical, 'legacy_name': legacy.name},
                        )
                        report['mappings'] += int(created)
            report['global_modules'] += len(seen)
        mode = 'EXECUTED' if execute else 'DRY-RUN'
        self.stdout.write(self.style.SUCCESS(f'{mode} {report}'))
