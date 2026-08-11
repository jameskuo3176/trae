from django.core.management.base import BaseCommand, CommandError

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    LegacyModuleMapping, Project, QorRecord, RunNote, ViolationPath,
)
from django_app.repositories import MongoRecordRepository, ensure_mongo_indexes, get_mongo_database


class Command(BaseCommand):
    help = 'Copy heavy project data to MongoDB; dry-run unless --execute is used'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--project-id', type=int)

    def handle(self, *args, **options):
        projects = Project.objects.all().order_by('id')
        if options['project_id']:
            projects = projects.filter(pk=options['project_id'])
            if not projects.exists():
                raise CommandError('project not found')
        execute = options['execute']
        db = get_mongo_database() if execute else None
        repository = MongoRecordRepository(db) if execute else None
        if execute:
            ensure_mongo_indexes(db)
        totals = {'qor_records': 0, 'violation_paths': 0, 'run_notes': 0}
        for project in projects:
            get_project_engine(project.id)
            alias = _get_project_db_alias(project.id)
            records = QorRecord.objects.using(alias).all().order_by('id')
            counts = {
                'qor_records': records.count(),
                'violation_paths': ViolationPath.objects.using(alias).count(),
                'run_notes': RunNote.objects.using(alias).count(),
            }
            legacy_module_ids = set(records.values_list('module_id', flat=True).distinct())
            mapped_module_ids = set(LegacyModuleMapping.objects.filter(
                project_id=project.id,
                legacy_module_id__in=legacy_module_ids,
            ).values_list('legacy_module_id', flat=True))
            missing_module_ids = sorted(legacy_module_ids - mapped_module_ids)
            for key, value in counts.items():
                totals[key] += value
            self.stdout.write(
                f'project={project.id} source={counts} '
                f'unmapped_module_ids={missing_module_ids}'
            )
            if not execute:
                continue
            if missing_module_ids:
                raise CommandError(
                    'global module mappings are required before Mongo migration; '
                    f'project={project.id} missing={missing_module_ids}'
                )
            id_map = {}
            module_map = dict(LegacyModuleMapping.objects.filter(
                project_id=project.id
            ).values_list('legacy_module_id', 'module_id'))
            for record in records.iterator():
                document = record.to_dict()
                document.update({
                    'id': str(record.id), 'legacy_id': str(record.id),
                    'project_id': project.id, 'legacy_module_id': record.module_id,
                    'module_id': module_map.get(record.module_id),
                })
                mongo_id = repository.upsert_record(document)
                id_map[record.id] = mongo_id
            for path in ViolationPath.objects.using(alias).all().iterator():
                document = path.to_dict()
                document.update({
                    'project_id': project.id,
                    'record_id': id_map.get(path.qor_record_id, str(path.qor_record_id)),
                    'legacy_id': str(path.id),
                })
                document.pop('qor_record_id', None)
                repository.upsert_violation(document)
            for note in RunNote.objects.using(alias).all().iterator():
                document = note.to_dict()
                document.update({
                    'project_id': project.id,
                    'record_id': id_map.get(note.qor_record_id, str(note.qor_record_id)),
                    'legacy_id': str(note.id),
                })
                document.pop('qor_record_id', None)
                repository.upsert_note(document)
            destination = {
                name: db[name].count_documents({'project_id': project.id})
                for name in totals
            }
            self.stdout.write(f'project={project.id} destination={destination}')
            if any(destination[name] < counts[name] for name in totals):
                raise CommandError(f'count check failed for project {project.id}')
        mode = 'EXECUTED' if execute else 'DRY-RUN'
        self.stdout.write(self.style.SUCCESS(f'{mode} source_totals={totals}'))
