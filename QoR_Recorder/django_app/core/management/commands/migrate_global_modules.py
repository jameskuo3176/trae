"""Create canonical module metadata without changing project databases."""
from contextlib import nullcontext

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import Module, Project
from django_app.services.qor_import import ensure_legacy_module_bridge


class Command(BaseCommand):
    help = (
        'Map legacy project-local modules to GlobalModule / ProjectModule / '
        'LegacyModuleMapping (dry-run by default)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='persist mappings in the default relational database',
        )
        parser.add_argument('--project-id', type=int)
        parser.add_argument(
            '--legacy-module-id',
            type=int,
            action='append',
            dest='legacy_module_ids',
            help='limit to one or more project-local module IDs',
        )

    def handle(self, *args, **options):
        execute = options['execute']
        projects = Project.objects.all().order_by('id')
        if options['project_id']:
            projects = projects.filter(pk=options['project_id'])
            if not projects.exists():
                raise CommandError('project not found')

        raw_legacy_ids = options.get('legacy_module_ids') or []
        if raw_legacy_ids and not isinstance(raw_legacy_ids, (list, tuple, set)):
            raw_legacy_ids = [raw_legacy_ids]
        legacy_filter = set(raw_legacy_ids)
        report = {
            'projects': 0,
            'legacy_modules': 0,
            'ok': 0,
            'create': 0,
            'applied': 0,
            'conflicts': 0,
        }
        conflicts = []

        for project in projects:
            get_project_engine(project.id)
            alias = _get_project_db_alias(project.id)
            legacy_rows = list(
                Module.objects.using(alias)
                .filter(project_id=project.id)
                .order_by('id')
            )
            if legacy_filter:
                legacy_rows = [row for row in legacy_rows if row.id in legacy_filter]
                missing_ids = sorted(
                    legacy_filter - {row.id for row in legacy_rows}
                )
                if missing_ids:
                    raise CommandError(
                        f'project={project.id} missing local modules: {missing_ids}'
                    )
            report['projects'] += 1
            report['legacy_modules'] += len(legacy_rows)
            self.stdout.write(
                f'project={project.id} local_modules={len(legacy_rows)} '
                f'database={alias}'
            )

            scope = transaction.atomic(using='default') if execute else nullcontext()
            with scope:
                for legacy in legacy_rows:
                    result = ensure_legacy_module_bridge(
                        project,
                        legacy,
                        execute=execute,
                    )
                    status = result['status']
                    if status == 'conflict':
                        report['conflicts'] += 1
                        conflicts.append(result)
                        self.stdout.write(self.style.ERROR(
                            '  conflict '
                            f'legacy_module_id={legacy.id} '
                            f'name={legacy.name!r} '
                            f'reason={result["reason"]}'
                        ))
                        continue
                    if status == 'ok':
                        report['ok'] += 1
                        self.stdout.write(
                            f'  ok legacy_module_id={legacy.id} '
                            f'name={legacy.name!r} '
                            f'global_module_id={result["global_module_id"]}'
                        )
                        continue
                    if status == 'create':
                        report['create'] += 1
                        self.stdout.write(self.style.WARNING(
                            '  create '
                            f'legacy_module_id={legacy.id} '
                            f'name={legacy.name!r} '
                            f'actions={",".join(result["actions"])} '
                            f'global_module_id={result.get("global_module_id")}'
                        ))
                        continue
                    if status == 'applied':
                        report['applied'] += 1
                        self.stdout.write(self.style.SUCCESS(
                            '  applied '
                            f'legacy_module_id={legacy.id} '
                            f'name={legacy.name!r} '
                            f'global_module_id={result["global_module_id"]}'
                        ))

        if conflicts and execute:
            raise CommandError(
                'refusing to commit while mapping conflicts remain; '
                f'conflicts={len(conflicts)}'
            )

        mode = 'EXECUTED' if execute else 'DRY-RUN'
        self.stdout.write(self.style.SUCCESS(f'{mode} {report}'))
        if conflicts:
            self.stdout.write(self.style.ERROR(
                f'unresolved_conflicts={len(conflicts)} (no changes committed)'
            ))
