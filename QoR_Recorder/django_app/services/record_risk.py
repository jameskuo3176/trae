"""Project-scoped risk assessment orchestration and user judgement storage."""
from __future__ import annotations

from django.utils import timezone

from django_app.core.models import (
    LegacyModuleMapping,
    ProjectMember,
    ProjectModule,
    QorRecord,
    RecordRiskAssessment,
)
from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.services.risk_rating import RISK_LEVELS, assess_versions, rate_version


def can_edit_risk(user, project, module_id):
    if not project.is_writable or user.is_viewer:
        return False
    if user.is_admin:
        return True
    if ProjectModule.objects.filter(
        project=project, module_id=module_id, owner_id=user.id,
    ).exists():
        return True
    return ProjectMember.objects.filter(
        project=project, user=user, role__in=('owner', 'editor'),
    ).exists()


def manual_ratings(project_id, module_id):
    return {
        row.record_id: row.manual_rating
        for row in RecordRiskAssessment.objects.filter(
            project_id=project_id, module_id=module_id,
        )
    }


def set_manual_rating(user, project, module_id, record_id, rating):
    if rating not in RISK_LEVELS:
        raise ValueError('rating must be low, medium, or high')
    if not can_edit_risk(user, project, module_id):
        raise PermissionError('risk rating edit denied')
    assessment, _ = RecordRiskAssessment.objects.update_or_create(
        project=project,
        record_id=str(record_id),
        defaults={
            'module_id': module_id,
            'manual_rating': rating,
            'rated_by': user,
            'updated_at': timezone.now(),
        },
    )
    return assessment


def clear_manual_rating(user, project, module_id, record_id):
    if not can_edit_risk(user, project, module_id):
        raise PermissionError('risk rating edit denied')
    return RecordRiskAssessment.objects.filter(
        project=project,
        module_id=module_id,
        record_id=str(record_id),
    ).delete()[0] > 0


def orm_module_history(project_id, module_id):
    legacy_ids = list(LegacyModuleMapping.objects.filter(
        project_id=project_id, module_id=module_id,
    ).values_list('legacy_module_id', flat=True))
    if not legacy_ids:
        return []
    get_project_engine(project_id)
    alias = _get_project_db_alias(project_id)
    return [
        {**row.to_dict(), 'id': str(row.id)}
        for row in QorRecord.objects.using(alias).filter(
            module_id__in=legacy_ids,
        ).order_by('recorded_at', 'id')
    ]


def assess_module_history(project_id, module_id, records=None):
    records = records if records is not None else orm_module_history(project_id, module_id)
    return assess_versions(records, manual_ratings(project_id, module_id))


def enrich_record_risks(items, user, history_loader=None):
    """Attach risk payloads while avoiding history queries without user overrides."""
    grouped = {}
    for item in items:
        try:
            key = (int(item['project_id']), int(item['module_id']))
        except (KeyError, TypeError, ValueError):
            item['risk'] = {**rate_version(item), 'can_edit': False}
            continue
        grouped.setdefault(key, []).append(item)

    project_ids = {key[0] for key in grouped}
    module_ids = {key[1] for key in grouped}
    override_keys = set(RecordRiskAssessment.objects.filter(
        project_id__in=project_ids,
        module_id__in=module_ids,
    ).values_list('project_id', 'module_id'))

    from django_app.core.models import Project
    projects = {row.id: row for row in Project.objects.filter(id__in=project_ids)}
    for (project_id, module_id), records in grouped.items():
        assessment_records = records
        if (project_id, module_id) in override_keys:
            assessment_records = (
                history_loader(project_id, module_id)
                if history_loader else orm_module_history(project_id, module_id)
            )
            known = {str(row.get('id')) for row in assessment_records}
            assessment_records = [
                *assessment_records,
                *(row for row in records if str(row.get('id')) not in known),
            ]
        risks = assess_module_history(project_id, module_id, assessment_records)
        editable = can_edit_risk(user, projects[project_id], module_id)
        for record in records:
            risk = risks.get(str(record.get('id')), rate_version(record))
            record['risk'] = {**risk, 'can_edit': editable}
    return items
