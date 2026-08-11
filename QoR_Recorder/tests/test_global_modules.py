import pytest
from django.db import IntegrityError

from django_app.core.models import GlobalModule, Project, ProjectModule


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
