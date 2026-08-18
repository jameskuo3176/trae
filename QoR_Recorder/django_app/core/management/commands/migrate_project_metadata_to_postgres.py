"""Copy project relational/review state out of legacy project SQLite files."""
from __future__ import annotations

import json

from django.core.management import BaseCommand, CommandError
from django.db import connections, transaction

from django_app.core.db_routing import (
    _get_legacy_project_db_alias, get_legacy_project_engine,
)
from django_app.core.models import (
    AlertEvent, AlertRule, DashboardGroup, DataSnapshot, GroupReview, Module,
    Project, QorRecord, RecordAnnotation, RecordAnnotationImage, ReviewFile,
    ReviewSnapshot, SubsystemReview, TileReview,
)


MODELS = (
    Module, QorRecord, RecordAnnotation, RecordAnnotationImage, DashboardGroup,
    AlertRule, AlertEvent, DataSnapshot, TileReview, GroupReview,
    SubsystemReview, ReviewSnapshot, ReviewFile,
)
HEAVY_RECORD_FIELDS = {
    'area_total', 'area_combinational', 'area_sequential', 'area_black_box',
    'area_macro', 'wns_setup', 'tns_setup', 'nvp_setup', 'wns_hold',
    'tns_hold', 'nvp_hold', 'power_internal', 'power_switching',
    'power_leakage', 'power_total', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count', 'ram_cell_count', 'macro_cell_count',
    'target_frequency', 'achieved_frequency', 'mbb_ratio',
    'clock_gating_ratio', 'utilization', 'congestion', 'congestion_h',
    'congestion_v', 'congestion_b', 'register_count', 'raw_dc_report',
}


def _clone(row, overrides=None):
    values = {}
    for field in row._meta.concrete_fields:
        if field.primary_key:
            continue
        values[field.attname] = getattr(row, field.attname)
    values.update(overrides or {})
    copy = type(row)(**values)
    copy.save(using='default', force_insert=True)
    return copy


def _remap_json_ids(value, mapping):
    if not value:
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(parsed, list):
        return value
    return json.dumps([mapping.get(int(item), item) for item in parsed])


class Command(BaseCommand):
    help = (
        'Copy project modules/reviews/annotations from legacy SQLite into '
        'PostgreSQL; dry-run unless --execute. Destination must be empty.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        if connections['default'].vendor != 'postgresql':
            raise CommandError('The default database must be PostgreSQL.')
        conflicts = {
            model._meta.label_lower: model._base_manager.using('default').count()
            for model in MODELS
            if model._base_manager.using('default').exists()
        }
        if conflicts:
            raise CommandError(
                'Destination project tables must be empty; this command does '
                f'not merge or duplicate rows: {conflicts}'
            )

        projects = list(Project.objects.using('default').order_by('id'))
        source_counts = {}
        sources = []
        for project in projects:
            get_legacy_project_engine(project.id)
            alias = _get_legacy_project_db_alias(project.id)
            counts = {
                model._meta.label_lower: model._base_manager.using(alias).count()
                for model in MODELS
            }
            source_counts[project.id] = counts
            sources.append((project, alias))
            self.stdout.write(f'project={project.id} source={counts}')
        if not options['execute']:
            self.stdout.write(self.style.SUCCESS(
                f'DRY-RUN projects={len(projects)} rows='
                f'{sum(sum(item.values()) for item in source_counts.values())}'
            ))
            return

        copied = {model._meta.label_lower: 0 for model in MODELS}
        with transaction.atomic(using='default'):
            for project, alias in sources:
                module_map = {}
                record_map = {}
                annotation_map = {}
                rule_map = {}
                tile_map = {}
                group_map = {}
                subsystem_map = {}
                snapshot_map = {}

                for row in Module.objects.using(alias).order_by('id'):
                    new = _clone(row)
                    module_map[row.id] = new.id
                    copied[Module._meta.label_lower] += 1
                for row in QorRecord.objects.using(alias).order_by('id'):
                    overrides = {'module_id': module_map[row.module_id]}
                    overrides.update({name: None for name in HEAVY_RECORD_FIELDS})
                    new = _clone(row, overrides)
                    record_map[row.id] = new.id
                    copied[QorRecord._meta.label_lower] += 1
                for row in RecordAnnotation.objects.using(alias).order_by('id'):
                    new = _clone(row, {'qor_record_id': record_map[row.qor_record_id]})
                    annotation_map[row.id] = new.id
                    copied[RecordAnnotation._meta.label_lower] += 1
                for row in RecordAnnotationImage.objects.using(alias).order_by('id'):
                    _clone(row, {'annotation_id': annotation_map[row.annotation_id]})
                    copied[RecordAnnotationImage._meta.label_lower] += 1
                for model in (DashboardGroup, DataSnapshot):
                    for row in model.objects.using(alias).order_by('id'):
                        _clone(row)
                        copied[model._meta.label_lower] += 1
                for row in AlertRule.objects.using(alias).order_by('id'):
                    module_id = module_map.get(row.module_id, row.module_id)
                    new = _clone(row, {'module_id': module_id})
                    rule_map[row.id] = new.id
                    copied[AlertRule._meta.label_lower] += 1
                for row in AlertEvent.objects.using(alias).order_by('id'):
                    _clone(row, {
                        'rule_id': rule_map[row.rule_id],
                        'qor_record_id': record_map.get(
                            row.qor_record_id, row.qor_record_id
                        ),
                        'module_id': module_map.get(row.module_id, row.module_id),
                    })
                    copied[AlertEvent._meta.label_lower] += 1
                for row in TileReview.objects.using(alias).order_by('id'):
                    new = _clone(row, {
                        'record_id': record_map.get(row.record_id),
                        'module_id': module_map.get(row.module_id, row.module_id),
                    })
                    tile_map[row.id] = new.id
                    copied[TileReview._meta.label_lower] += 1
                for row in GroupReview.objects.using(alias).order_by('id'):
                    new = _clone(row, {
                        'tile_review_ids': _remap_json_ids(
                            row.tile_review_ids, tile_map
                        ),
                    })
                    group_map[row.id] = new.id
                    copied[GroupReview._meta.label_lower] += 1
                for row in SubsystemReview.objects.using(alias).order_by('id'):
                    new = _clone(row, {
                        'group_review_ids': _remap_json_ids(
                            row.group_review_ids, group_map
                        ),
                    })
                    subsystem_map[row.id] = new.id
                    copied[SubsystemReview._meta.label_lower] += 1
                for row in ReviewSnapshot.objects.using(alias).order_by('id'):
                    new = _clone(row, {
                        'subsystem_review_id': subsystem_map.get(
                            row.subsystem_review_id
                        ),
                    })
                    snapshot_map[row.id] = new.id
                    copied[ReviewSnapshot._meta.label_lower] += 1
                for row in ReviewFile.objects.using(alias).order_by('id'):
                    _clone(row, {'snapshot_id': snapshot_map[row.snapshot_id]})
                    copied[ReviewFile._meta.label_lower] += 1

            mismatches = {
                label: {'source': expected, 'target': copied[label]}
                for label, expected in {
                    label: sum(counts[label] for counts in source_counts.values())
                    for label in copied
                }.items()
                if copied[label] != expected
            }
            if mismatches:
                raise CommandError(f'Copy count mismatch: {mismatches}')

        for _, alias in sources:
            connections[alias].close()
        self.stdout.write(self.style.SUCCESS(f'EXECUTED copied={copied}'))
