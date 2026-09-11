"""Regression tests for scripts/upload_qor_client.sh.

Two failure modes are covered:

1. Non-ASCII text inside a ``python3 -c`` program. CPython decodes argv with the
   locale encoding, so under a C/POSIX locale the Chinese bytes become lone
   surrogates and the interpreter aborts before running anything with
   ``Unable to decode the command line: UnicodeEncodeError ... surrogates not
   allowed``. The static test below runs on every platform.
2. A ``.json`` input silently going to the multipart CSV endpoint, which answers
   HTTP 422 with ``skipped == total``.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'upload_qor_client.sh'
DC_REPORT_TO_JSON = Path(__file__).resolve().parents[1] / 'scripts' / 'dc_report_to_json.py'

SCRIPT_TEXT = SCRIPT.read_text(encoding='utf-8')

INLINE_PY_PROGRAM = re.compile(r"(?:python3|run_py)\s+-c\s+'([^']*)'", re.S)

DC_REPORT = """{
  "syn_owner": "bz_xixun.guo",
  "schema_version": 1,
  "generated_at": "2026-09-02T20:13:44.287746+00:00",
  "stage": "Synthesis",
  "top_module": "io_d2dw2_t",
  "run": {
    "full_dir": "/project/feint2/SYN/voyager/weekly/regr_20260902/main/io_d2dw2_t_work"
  },
  "timing": {
    "default": {
      "status": "ok",
      "source": "/project/feint2/SYN/voyager/weekly/regr_20260902/main/io_d2dw2_t_work/rpts/Synthesis/x.rpt",
      "scenarios": {
        "func_ss": {
          "path_groups": {
            "clk_a": {"WNS": -0.12, "TNS": -3.4, "NVP": 17, "Clk_Period": 1.25}
          }
        }
      }
    }
  },
  "area": {"tile": {"area": {"total": 12345.6}, "cell_count": {"total": 900}}},
  "misc": {"utilization": 70.5, "fgcg": {"total_flops": 4200}, "no_clock": {"note": "\u544a\u8b66"}}
}
"""

STUB_CURL = """#!/usr/bin/env bash
: > "$CURL_LOG"
for arg in "$@"; do
    printf '%s\\n' "$arg" >> "$CURL_LOG"
    case "$arg" in
        @*) cp "${arg#@}" "$CURL_BODY" 2>/dev/null || true ;;
    esac
done
printf '{"ok": true, "saved": 1}\\n200'
"""


def test_inline_python_programs_are_ascii_only():
    programs = INLINE_PY_PROGRAM.findall(SCRIPT_TEXT)
    assert programs, 'expected at least one inline python program to guard'
    for program in programs:
        assert program.isascii(), f'non-ASCII text in a python3 -c program: {program!r}'


def test_inline_python_goes_through_the_run_py_wrapper():
    code = [line for line in SCRIPT_TEXT.splitlines() if not line.strip().startswith('#')]
    offenders = [line.strip() for line in code if re.search(r'python3\s+-c', line)]
    assert not offenders, f'python3 -c called without the UTF-8 wrapper: {offenders}'


def test_python_invocations_are_utf8_hardened():
    assert 'PYTHONUTF8=1' in SCRIPT_TEXT
    assert 'PYTHONIOENCODING=utf-8' in SCRIPT_TEXT


# --------------------------------------------------------------------------
# End-to-end: needs a POSIX shell, so it is skipped on Windows checkouts.
# --------------------------------------------------------------------------

pytestmark_reason = 'needs bash + POSIX tooling'
run_e2e = pytest.mark.skipif(
    sys.platform.startswith('win') or shutil.which('bash') is None,
    reason=pytestmark_reason,
)


def _run_client(tmp_path, args, extra_env=None):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / 'curl'
    stub.write_text(STUB_CURL, encoding='utf-8')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env.update({
        'PATH': f'{bin_dir}{os.pathsep}{env["PATH"]}',
        'CURL_LOG': str(tmp_path / 'curl.log'),
        'CURL_BODY': str(tmp_path / 'body.json'),
        'QOR_SERVER': 'http://example.internal:5000',
        'QOR_API_KEY': 'qor_test',
        'DC_REPORT_TO_JSON': str(DC_REPORT_TO_JSON),
        # Reproduce the workstation locale that broke argv decoding.
        'LC_ALL': 'C',
        'LANG': 'C',
    })
    env.pop('QOR_UPLOAD_ENV', None)
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        ['bash', str(SCRIPT), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    log = tmp_path / 'curl.log'
    body = tmp_path / 'body.json'
    return proc, (log.read_text() if log.exists() else ''), (body.read_text() if body.exists() else '')


@run_e2e
def test_dc_report_json_routes_to_json_api_without_json_flag(tmp_path):
    report = tmp_path / 'Synthesis.qor_summary.json'
    report.write_text(DC_REPORT, encoding='utf-8')

    proc, curl_log, body = _run_client(tmp_path, ['3', 'v1.1', './Synthesis.qor_summary.json'])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'Unable to decode the command' not in proc.stdout + proc.stderr
    assert '/api/v1/qor/upload' in curl_log
    assert '/api/v1/upload?' not in curl_log
    assert '-F' not in curl_log.splitlines()
    assert '"full_dir": "/project/feint2/SYN/voyager' in body
    assert '"project_id": 3' in body


@run_e2e
def test_dc_report_run_directory_does_not_require_full_dir_option(tmp_path):
    source = json.loads(DC_REPORT)
    source['run']['directory'] = source['run'].pop('full_dir')
    report = tmp_path / 'Synthesis.qor_summary.json'
    report.write_text(json.dumps(source), encoding='utf-8')

    proc, _, body = _run_client(
        tmp_path, ['3', 'v1.1', './Synthesis.qor_summary.json']
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'pass --full-dir' not in proc.stdout + proc.stderr
    assert '"full_dir": "/project/feint2/SYN/voyager' in body


@run_e2e
def test_upload_directory_is_injected_as_canonical_full_dir(tmp_path):
    payload = tmp_path / 'run65.json'
    payload.write_text(json.dumps({
        'schema_version': '1.0',
        'upload': {
            'project_id': 1,
            'version': 'v1.1',
            'directory': '/project/feint2/SYN/voyager/weekly/regr_20260902/main/demo',
        },
        'records': [{'module_name': 'demo'}],
    }), encoding='utf-8')

    proc, _, body = _run_client(tmp_path, ['3', 'v1.1', './run65.json'])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    uploaded = json.loads(body)
    assert uploaded['upload']['full_dir'].endswith('/main/demo')
    assert 'directory' not in uploaded['upload']


@run_e2e
def test_upload_client_rejects_conflicting_path_aliases(tmp_path):
    payload = tmp_path / 'run65.json'
    payload.write_text(json.dumps({
        'schema_version': '1.0',
        'upload': {
            'project_id': 1,
            'full_dir': '/project/regr_20260908/main/demo',
            'directory': '/project/regr_20260908/main/other',
        },
        'records': [{'module_name': 'demo'}],
    }), encoding='utf-8')

    proc, curl_log, _ = _run_client(tmp_path, ['3', 'v1.1', './run65.json'])

    assert proc.returncode == 1
    assert 'conflicts with upload.directory' in proc.stderr
    assert not curl_log


@run_e2e
def test_json_flag_still_works_under_c_locale(tmp_path):
    report = tmp_path / 'Synthesis.qor_summary.json'
    report.write_text(DC_REPORT, encoding='utf-8')

    proc, curl_log, _ = _run_client(
        tmp_path, ['3', 'v1.1', './Synthesis.qor_summary.json', '--json']
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'surrogates not allowed' not in proc.stdout + proc.stderr
    assert '/api/v1/qor/upload' in curl_log


@run_e2e
def test_non_ascii_payload_survives_c_locale(tmp_path):
    payload = tmp_path / 'run65.json'
    payload.write_text(
        '{"schema_version": "1.0", "upload": {"project_id": 1},'
        ' "records": [{"module_name": "\u6a21\u5757_\u4e2d\u6587"}]}',
        encoding='utf-8',
    )

    proc, _, body = _run_client(
        tmp_path, ['3', 'v1.1', './run65.json', '--full-dir', '/scratch/runs/v1.1']
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '\u6a21\u5757_\u4e2d\u6587' in body
    assert '"full_dir": "/scratch/runs/v1.1"' in body


@run_e2e
def test_csv_still_uses_multipart(tmp_path):
    csv_file = tmp_path / 'module_alu_qor.csv'
    csv_file.write_text('module_name,wns\nmodule_alu,-0.1\n', encoding='utf-8')

    proc, curl_log, _ = _run_client(tmp_path, ['2', 'v1.0', './module_alu_qor.csv'])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '/api/v1/upload' in curl_log
    assert '/api/v1/qor/upload' not in curl_log


@run_e2e
def test_multipart_flag_forces_legacy_endpoint_with_warning(tmp_path):
    report = tmp_path / 'Synthesis.qor_summary.json'
    report.write_text(DC_REPORT, encoding='utf-8')

    proc, curl_log, _ = _run_client(
        tmp_path, ['3', 'v1.1', './Synthesis.qor_summary.json', '--multipart']
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '[WARN]' in proc.stdout
    assert '/api/v1/upload' in curl_log
    assert '/api/v1/qor/upload' not in curl_log
