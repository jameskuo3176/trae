import importlib.util
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest


HANDLER = Path(__file__).resolve().parents[1] / 'scripts' / 'gvim_protocol_handler.py'


def _load_handler():
    spec = importlib.util.spec_from_file_location('gvim_protocol_handler', HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gvim_handler_launches_with_argument_array(monkeypatch):
    module = _load_handler()
    calls = []

    monkeypatch.setattr(module.shutil, 'which', lambda name: r'C:\Vim\gvim.exe')
    monkeypatch.setattr(
        module.subprocess,
        'Popen',
        lambda args, **kwargs: calls.append((args, kwargs)) or object(),
    )

    path = r'D:\runs\top.v'
    uri = f'gvim://open?path={quote(path)}&line=17'
    module.main(uri)

    assert calls == [(
        [r'C:\Vim\gvim.exe', '+17', '--', path],
        {'shell': False, 'close_fds': True},
    )]


def test_gvim_handler_rejects_unsafe_uri(monkeypatch):
    module = _load_handler()
    monkeypatch.setattr(module.shutil, 'which', lambda name: r'C:\Vim\gvim.exe')
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('must not launch')
    ))

    with pytest.raises(SystemExit):
        module.main('http://open?path=/tmp/x')
    with pytest.raises(SystemExit):
        module.main('gvim://open?path=')
