"""Tests for the one-file Python workstation upload client."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "upload_qor_client.py"
SPEC = importlib.util.spec_from_file_location("upload_qor_client", SCRIPT)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


def test_dc_area_maps_non_combinational_to_sequential_not_combinational():
    data = {
        "area": {
            "tile": {
                "area": {
                    "total": 411493,
                    "combinational": 99556,
                    "non_combinational": 209993,
                    "memory": 101788,
                    "macro": 0,
                },
                "cell_count": {"total": 10, "combinational": 4, "sequential": 6},
            }
        },
        "misc": {"fgcg": {"total_flops": 963050}},
        "top_module": "core",
        "run": {"full_dir": "/project/regr/main/core"},
        "timing": {"default": {"status": "empty", "scenarios": {}}},
        "schema_version": 1,
    }
    area = client._dc_area(data)
    assert area["combinational"] == 99556
    assert area["sequential"] == 209993
    payload = client.convert_dc_to_qor_record(data, project_id=1, version="v1")
    record = payload["records"][0]
    assert record["area"]["sequential"] == 209993
    assert record["cells"]["register_count"] == 963050
    # vt_ratio preserved when present
    data["misc"]["vt_ratio"] = {"LVT06": "99.99%", "SVT06": "0.00%"}
    payload2 = client.convert_dc_to_qor_record(data, project_id=1, version="v1")
    assert payload2["records"][0]["extra"]["misc_vt_ratio"]["LVT06"] == "99.99%"
    assert payload2["_raw_dc_report"]["misc"]["vt_ratio"]["LVT06"] == "99.99%"


class RecordingHandler(BaseHTTPRequestHandler):
    status = 200
    response = b'{"ok":true}'
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        self.__class__.requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        self.send_response(self.__class__.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.__class__.response)

    def log_message(self, _format, *_args):
        pass


@contextmanager
def server(status=200, response=b'{"ok":true}'):
    RecordingHandler.status = status
    RecordingHandler.response = response
    RecordingHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{}".format(httpd.server_port), RecordingHandler.requests
    finally:
        httpd.shutdown()
        thread.join()


def run_client(tmp_path, server_url, *args, key="qor_secret"):
    env = {"QOR_SERVER": server_url, "QOR_API_KEY": key}
    parsed = client.build_parser().parse_args([*args])
    return client.run(parsed, env)


def test_multipart_csv_uses_web_and_legacy_file_fields(tmp_path):
    csv_path = tmp_path / "module_alu_qor.csv"
    csv_path.write_text("module_name,wns_setup\nmodule_alu,-0.1\n", encoding="utf-8")
    with server() as (url, requests):
        result = run_client(
            tmp_path, url, "2", "v1.0", str(csv_path),
            "--module-id", "9", "--release", "--release-dir", "/released",
            "--directory", "/run",
        )

    assert result == 0
    request = requests[0]
    assert request["path"] == "/api/v1/upload"
    assert request["headers"]["X-API-Key"] == "qor_secret"
    content = request["body"].decode("utf-8")
    assert 'name="files"; filename="module_alu_qor.csv"' in content
    assert 'name="file"; filename="module_alu_qor.csv"' in content
    assert 'name="project_id"\r\n\r\n2' in content
    assert 'name="module_id"\r\n\r\n9' in content
    assert 'name="mark_released"\r\n\r\n1' in content
    assert 'name="full_dir"\r\n\r\n/run' in content


def test_section_65_json_injects_cli_fields_and_routes(tmp_path):
    source = tmp_path / "payload"
    source.write_text(json.dumps({
        "schema_version": "1.0",
        "upload": {"directory": "/native/run"},
        "records": [{"module_name": "alu"}],
    }), encoding="utf-8")
    with server() as (url, requests):
        result = run_client(
            tmp_path, url, "3", "版本 1", str(source),
            "--module-id", "8", "--release",
        )

    assert result == 0
    request = requests[0]
    assert request["path"] == "/api/v1/qor/upload?project_id=3&version=%E7%89%88%E6%9C%AC%201"
    payload = json.loads(request["body"])
    assert payload["upload"] == {
        "full_dir": "/native/run",
        "project_id": 3,
        "version": "版本 1",
        "module_id": 8,
        "mark_released": True,
    }


def native_report(full_dir="/project/run"):
    return {
        "schema_version": 1,
        "top_module": "模块_a",
        "run": {"directory": full_dir},
        "timing": {
            "default": {
                "status": "ok",
                "scenarios": {
                    "slow": {
                        "path_groups": {
                            "CLK": {
                                "WNS": 16858,
                                "TNS": -12,
                                "NVP": 2,
                                "Clk_Period": 36364,
                                "LOL": 21,
                            },
                        },
                    },
                },
            },
        },
        "area": {
            "warnings": ["fallback"],
            "tile": {"area": {"total": 123.5}},
        },
    }


def test_native_dc_conversion_preserves_ps_values_lol_and_raw_metadata(tmp_path):
    source = tmp_path / "Synthesis.qor_summary.json"
    source.write_text(json.dumps(native_report(), ensure_ascii=False), encoding="utf-8")
    with server() as (url, requests):
        result = run_client(tmp_path, url, "4", "v1.1", str(source))

    assert result == 0
    payload = json.loads(requests[0]["body"])
    record = payload["records"][0]
    assert record["timing"]["setup"]["wns"] == 16858
    assert record["clocks"]["CLK"]["period"] == 36364
    assert record["extra"]["scenarios"]["slow"]["CLK"]["lol"] == 21
    assert payload["_raw_dc_report"]["area"]["warnings"] == ["fallback"]
    assert payload["upload"]["full_dir"] == "/project/run"


def test_empty_native_timing_and_area_warnings_are_supported(tmp_path):
    report = native_report()
    report["timing"]["default"] = {
        "status": "empty",
        "scenarios": "default",
        "warnings": ["No timing paths"],
    }
    report["area"] = {"status": "empty", "warnings": ["No area values"]}
    source = tmp_path / "empty.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    with server() as (url, requests):
        assert run_client(tmp_path, url, "4", "v1.1", str(source)) == 0
    record = json.loads(requests[0]["body"])["records"][0]
    assert "timing" not in record
    assert "area" not in record
    assert record["extra"]["timing_group_count"] == 0


def test_conflicting_directory_aliases_stop_before_http(tmp_path):
    source = tmp_path / "conflict.json"
    source.write_text(json.dumps({
        "schema_version": "1.0",
        "upload": {"full_dir": "/a", "directory": "/b"},
        "records": [],
    }), encoding="utf-8")
    with server() as (url, requests):
        args = client.build_parser().parse_args(["1", "v1", str(source)])
        with pytest.raises(client.ClientError, match="conflicts"):
            client.run(args, {"QOR_SERVER": url, "QOR_API_KEY": "secret"})
    assert not requests


def test_conflicting_cli_directory_aliases_stop_before_http(tmp_path):
    source = tmp_path / "module_qor.csv"
    source.write_text("module_name\nmodule\n", encoding="utf-8")
    with server() as (url, requests):
        args = client.build_parser().parse_args([
            "1", "v1", str(source),
            "--full-dir", "/a", "--directory", "/b",
        ])
        with pytest.raises(client.ClientError, match="同时提供但值不同"):
            client.run(args, {"QOR_SERVER": url, "QOR_API_KEY": "secret"})
    assert not requests


def test_csv_json_mode_is_standalone_and_aggregates_path_groups(tmp_path):
    source = tmp_path / "module_cpu_qor.csv"
    source.write_text(
        "total_area,macro_area,CLK_wns,CLK_tns,CLK_path\n"
        "100,20,-3,-9,4\n",
        encoding="utf-8",
    )
    with server() as (url, requests):
        result = run_client(
            tmp_path, url, "2", "v2", str(source),
            "--json", "--full-dir", "/scratch/运行",
        )
    assert result == 0
    payload = json.loads(requests[0]["body"])
    record = payload["records"][0]
    assert record["area"]["total"] == 100
    assert record["timing"]["setup"] == {"wns": -3, "tns": -9, "nvp": 4}
    assert record["clocks"]["CLK"]["nvp"] == 4
    assert payload["upload"]["full_dir"] == "/scratch/运行"


def test_config_precedence_cli_then_environment_then_file(tmp_path):
    env_file = tmp_path / "qor_upload.env"
    env_file.write_text(
        "export QOR_SERVER='http://from-file'\r\n"
        "QOR_API_KEY=file-key # comment\r\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        env_file=str(env_file), server="http://from-cli"
    )
    server_value, key, _ = client.resolve_settings(
        args,
        {"QOR_SERVER": "http://from-env", "QOR_API_KEY": "env-key"},
        tmp_path,
    )
    assert server_value == "http://from-cli"
    assert key == "env-key"


def test_http_error_includes_response_body_and_never_prints_key(tmp_path, capsys):
    source = tmp_path / "module_qor.csv"
    source.write_text("module_name\nmodule\n", encoding="utf-8")
    secret = "qor_must_not_leak"
    with server(422, "无法保存：字段错误".encode("utf-8")) as (url, _requests):
        result = run_client(tmp_path, url, "2", "v1", str(source), key=secret)
    captured = capsys.readouterr()
    assert result == client.EXIT_HTTP
    assert "无法保存：字段错误" in captured.out
    assert secret not in captured.out + captured.err


def test_json_can_be_forced_to_multipart(tmp_path):
    source = tmp_path / "payload.json"
    source.write_text('{"records":[]}', encoding="utf-8")
    with server() as (url, requests):
        result = run_client(
            tmp_path, url, "2", "v1", str(source), "--multipart"
        )
    assert result == 0
    assert requests[0]["path"] == "/api/v1/upload"


class HostStrictHandler(BaseHTTPRequestHandler):
    """Mimic gunicorn/Django rejecting duplicate Host (HTTP 400 HTML)."""

    requests = []

    def do_POST(self):
        hosts = self.headers.get_all("Host") or []
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        record = {
            "path": self.path,
            "hosts": list(hosts),
            "headers": {key: self.headers.get_all(key) for key in self.headers.keys()},
            "body": body,
        }
        self.__class__.requests.append(record)
        if len(hosts) != 1:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Bad Request</title></head>"
                b"<body><h1><p>Bad Request</p></h1>"
                b"Invalid HTTP Header: &#x27;HOST&#x27;</body></html>"
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, _format, *_args):
        pass


@contextmanager
def host_strict_server():
    HostStrictHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HostStrictHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_port
        yield (
            "http://127.0.0.1:{}".format(port),
            port,
            HostStrictHandler.requests,
        )
    finally:
        httpd.shutdown()
        thread.join()


def test_post_headers_single_host_from_url_not_environ(monkeypatch):
    """Regression: duplicate Host / env HOST must not yield Invalid HTTP Header."""
    monkeypatch.setenv("HOST", "evil.workstation.local")
    monkeypatch.setenv("PORT", "9999")
    with host_strict_server() as (url, port, requests):
        status, body = client.post(
            url,
            "/api/v1/qor/upload?project_id=4&version=syn_regr_0817",
            "qor_test_key",
            timeout=5.0,
            json_body=b'{"schema_version":"1.0","upload":{},"records":[]}',
        )

    assert status == 200
    assert body == b'{"ok":true}'
    assert len(requests) == 1
    request = requests[0]
    # Exactly one Host, from URL netloc — not environ HOST/PORT.
    assert request["hosts"] == ["127.0.0.1:{}".format(port)]
    assert request["headers"]["X-API-Key"] == ["qor_test_key"]
    assert request["headers"]["Content-Type"] == [
        "application/json; charset=utf-8"
    ]
    header_names_lower = {name.lower() for name in request["headers"]}
    assert "port" not in header_names_lower
    assert all(
        value != ["evil.workstation.local"] and value != ["9999"]
        for value in request["headers"].values()
    )
