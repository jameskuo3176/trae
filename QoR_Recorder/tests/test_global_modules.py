import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError
from django.db import connections
from io import StringIO

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    GlobalModule,
    LegacyModuleMapping,
    Module,
    Project,
    ProjectModule,
    User,
)
from django_app.services.qor_import import (
    ensure_legacy_module_bridge,
    plan_legacy_module_bridge,
)
from django_app.services.review_hierarchy import validate_hierarchy


@pytest.fixture
def module_api_env(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user(
            'module-create-admin',
            password='x',
            role='admin',
        )
        project = Project.objects.create(name='new-project')
        alias = _get_project_db_alias(project.id)
        if alias in connections.databases:
            connections[alias].close()
            connections.databases.pop(alias, None)
        get_project_engine(project.id)
        call_command('migrate', database=alias, verbosity=0, interactive=False)
    yield {'admin': admin, 'project': project, 'alias': alias}
    if alias in connections.databases:
        connections[alias].close()
        connections.databases.pop(alias, None)


@pytest.mark.django_db
def test_module_normalization_and_project_association():
    project_a = Project.objects.create(name='A')
    project_b = Project.objects.create(name='B')
    module = GlobalModule.objects.create(name='  CPU_TOP  ', normalized_name='ignored')
    assert module.normalized_name == 'cpu_top'
    ProjectModule.objects.create(project=project_a, module=module)
    ProjectModule.objects.create(project=project_b, module=module)
    assert module.project_links.count() == 2


@pytest.mark.django_db
def test_normalized_name_is_globally_unique():
    GlobalModule.objects.create(name='CPU_TOP', normalized_name='ignored')
    with pytest.raises(IntegrityError):
        GlobalModule.objects.create(name='cpu_top', normalized_name='ignored')


@pytest.mark.django_db
def test_module_name_must_not_be_blank():
    with pytest.raises(ValueError, match='must not be empty'):
        GlobalModule.objects.create(name=' \t ', normalized_name='ignored')


@pytest.mark.django_db
def test_admin_create_module_builds_all_canonical_mappings(
    client, module_api_env,
):
    env = module_api_env
    client.force_login(env['admin'])

    response = client.post(
        '/api/admin/modules',
        data={'project_id': env['project'].id, 'name': 'test1'},
        content_type='application/json',
    )

    assert response.status_code == 200
    assert response.json()['created'] is True
    legacy = Module.objects.using(env['alias']).get(name='test1')
    canonical = GlobalModule.objects.get(normalized_name='test1')
    project_module = ProjectModule.objects.get(
        project=env['project'],
        module=canonical,
    )
    mapping = LegacyModuleMapping.objects.get(
        project=env['project'],
        legacy_module_id=legacy.id,
    )
    assert mapping.module_id == canonical.id
    assert response.json()['global_module_id'] == canonical.id
    assert response.json()['project_module_id'] == project_module.id

    errors, _resolved = validate_hierarchy({
        'version': 'test',
        'projects': {
            env['project'].name: {
                'owner': env['admin'].username,
                'groups': {
                    'default': {
                        'owner': env['admin'].username,
                        'modules': {
                            'test1': {'release_owner': env['admin'].username},
                        },
                    },
                },
            },
        },
    })
    assert errors == []

    duplicate = client.post(
        '/api/admin/modules',
        data={'project_id': env['project'].id, 'name': 'test1'},
        content_type='application/json',
    )
    assert duplicate.status_code == 200
    assert duplicate.json()['created'] is False
    assert Module.objects.using(env['alias']).filter(name='test1').count() == 1
    assert ProjectModule.objects.filter(project=env['project']).count() == 1
    assert LegacyModuleMapping.objects.filter(project=env['project']).count() == 1


@pytest.mark.django_db
def test_admin_batch_create_modules_bridges_new_and_existing_modules(
    client, module_api_env,
):
    env = module_api_env
    existing = Module.objects.using(env['alias']).create(
        project_id=env['project'].id,
        name='existing-unmapped',
    )
    client.force_login(env['admin'])

    response = client.post(
        '/api/admin/modules/batch',
        data={
            'project_id': env['project'].id,
            'module_names': ['existing-unmapped', 'batch-new-one', 'batch-new-two'],
        },
        content_type='application/json',
    )

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['created'] == ['batch-new-one', 'batch-new-two']
    assert response.json()['skipped'] == ['existing-unmapped']
    assert response.json()['bridged_count'] == 3
    assert GlobalModule.objects.filter(
        normalized_name__in=('existing-unmapped', 'batch-new-one', 'batch-new-two'),
    ).count() == 3
    assert ProjectModule.objects.filter(project=env['project']).count() == 3
    assert LegacyModuleMapping.objects.filter(project=env['project']).count() == 3
    assert LegacyModuleMapping.objects.get(
        project=env['project'],
        legacy_module_id=existing.id,
    ).legacy_name == 'existing-unmapped'


@pytest.mark.django_db
def test_plan_legacy_module_bridge_reports_create_for_unmapped_module(module_api_env):
    env = module_api_env
    legacy = Module.objects.using(env['alias']).create(
        project_id=env['project'].id,
        name='module_rf',
    )
    plan = plan_legacy_module_bridge(env['project'], legacy)
    assert plan['status'] == 'create'
    assert plan['legacy_module_id'] == legacy.id
    assert 'create_legacy_mapping' in plan['actions']


@pytest.mark.django_db
def test_migrate_global_modules_bridges_unmapped_local_modules(module_api_env):
    env = module_api_env
    legacy = Module.objects.using(env['alias']).create(
        project_id=env['project'].id,
        name='module_misc',
    )
    dry_run = StringIO()
    call_command(
        'migrate_global_modules',
        project_id=env['project'].id,
        legacy_module_id=legacy.id,
        stdout=dry_run,
    )
    assert 'create' in dry_run.getvalue()
    assert LegacyModuleMapping.objects.filter(
        project=env['project'],
        legacy_module_id=legacy.id,
    ).count() == 0

    apply_out = StringIO()
    call_command(
        'migrate_global_modules',
        project_id=env['project'].id,
        legacy_module_id=legacy.id,
        execute=True,
        stdout=apply_out,
    )
    mapping = LegacyModuleMapping.objects.get(
        project=env['project'],
        legacy_module_id=legacy.id,
    )
    assert mapping.legacy_name == 'module_misc'
    assert ProjectModule.objects.filter(
        project=env['project'],
        module_id=mapping.module_id,
    ).exists()


@pytest.mark.django_db
def test_migrate_global_modules_refuses_conflicting_mapping(module_api_env):
    env = module_api_env
    legacy = Module.objects.using(env['alias']).create(
        project_id=env['project'].id,
        name='conflict-module',
    )
    other = GlobalModule.objects.create(name='other', normalized_name='other')
    LegacyModuleMapping.objects.create(
        project=env['project'],
        legacy_module_id=legacy.id,
        module=other,
        legacy_name='stale-name',
    )
    plan = ensure_legacy_module_bridge(env['project'], legacy, execute=False)
    assert plan['status'] == 'conflict'
    assert plan['reason'] == 'legacy_name_mismatch'


@pytest.mark.django_db
def test_block_qor_upload_bridges_modules(client, module_api_env):
    env = module_api_env
    client.force_login(env['admin'])
    csv_body = (
        'module_name,version,full_dir,area_total\n'
        'module_rf,v1,/proj/run1,100\n'
    )
    response = client.post(
        '/api/admin/upload_block_qor',
        data={
            'project_id': env['project'].id,
            'files': SimpleUploadedFile(
                'block_qor.csv',
                csv_body.encode('utf-8'),
                content_type='text/csv',
            ),
        },
    )
    assert response.status_code == 200
    legacy = Module.objects.using(env['alias']).get(name='module_rf')
    mapping = LegacyModuleMapping.objects.get(
        project=env['project'],
        legacy_module_id=legacy.id,
    )
    assert mapping.legacy_name == 'module_rf'
    assert ProjectModule.objects.filter(
        project=env['project'],
        module_id=mapping.module_id,
    ).exists()
