import pytest

from django_app.services.path_derivation import (
    PathDerivationError, derive_path_metadata, derive_version, normalize_full_dir,
)


def test_windows_and_linux_paths_have_same_version():
    assert derive_version(r'D:\runs\regr_old\foo\regr_20260810\main\cpu') == 'regr_20260810'
    assert derive_version('/runs/regr_old/foo/regr_20260810/main/cpu') == 'regr_20260810'


def test_last_regr_is_used_without_direct_main_predecessor():
    assert derive_version('/runs/regr_a/foo/regr_b/cpu') == 'regr_b'


def test_quarter_week_release_train_is_path_derived():
    assert derive_version('/workspace/2026Q3_w3/main/cpu') == '2026Q3_w3'
    assert derive_version('2026Q3_w3/variant_c/cpu_cfg1') == '2026Q3_w3'


def test_no_v1_fallback_and_structured_error():
    with pytest.raises(PathDerivationError) as raised:
        derive_version('/runs/main/cpu')
    assert raised.value.as_dict()['code'] == 'version_not_in_path'


def test_normalization_rejects_parent_traversal():
    with pytest.raises(PathDerivationError):
        normalize_full_dir('/runs/../secret')
