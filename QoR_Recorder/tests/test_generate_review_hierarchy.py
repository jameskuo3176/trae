import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'generate_review_hierarchy.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('generate_review_hierarchy', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generates_projects_wrap_from_owner_prefix_syntax():
    module = _load_script()
    text = """
    OWNER_alice = cpu dsp
    OWNER_bob = mem
    """
    dumped = module.generate_review_hierarchy_yaml(text, 'blazar')
    data = yaml.safe_load(dumped)
    assert data == {
        'projects': {
            'blazar': {
                'owner': 'alice',
                'groups': {
                    'alice': {
                        'owner': 'alice',
                        'modules': {
                            'cpu': {'release_owner': 'alice'},
                            'dsp': {'release_owner': 'alice'},
                        },
                    },
                    'bob': {
                        'owner': 'bob',
                        'modules': {
                            'mem': {'release_owner': 'bob'},
                        },
                    },
                },
            }
        }
    }


def test_plain_usernames_and_bare_wrap_and_project_owner():
    module = _load_script()
    text = 'alice = cpu dsp\nbob = mem cache'
    dumped = module.generate_review_hierarchy_yaml(
        text, 'blazar', project_owner='admin', wrap='bare',
    )
    assert yaml.safe_load(dumped) == {
        'owner': 'admin',
        'groups': {
            'alice': {
                'owner': 'alice',
                'modules': {
                    'cpu': {'release_owner': 'alice'},
                    'dsp': {'release_owner': 'alice'},
                },
            },
            'bob': {
                'owner': 'bob',
                'modules': {
                    'mem': {'release_owner': 'bob'},
                    'cache': {'release_owner': 'bob'},
                },
            },
        },
    }


def test_duplicate_module_errors():
    module = _load_script()
    with pytest.raises(module.HierarchyGenerateError, match="module 'cpu'"):
        module.parse_owner_module_text('alice = cpu dsp\nbob = cpu mem')


def test_cli_writes_output_file(tmp_path, capsys):
    module = _load_script()
    owners = tmp_path / 'owners.txt'
    owners.write_text('OWNER_alice = cpu dsp\nbob = mem\n', encoding='utf-8')
    out = tmp_path / 'fragment.yaml'
    rc = module.main([
        '--project', 'blazar',
        '--input', str(owners),
        '--output', str(out),
    ])
    assert rc == 0
    assert capsys.readouterr().out == ''
    assert yaml.safe_load(out.read_text(encoding='utf-8'))['projects']['blazar']['owner'] == 'alice'
