"""使用真实本地 HTTP 请求验证 Web 契约。"""
import json
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from shared.storage import ReportStorage
from web_backend.service import ReportService
from web_server import create_server


@pytest.fixture
def server(tmp_path):
    service = ReportService(ReportStorage(tmp_path / "reports.db"))
    httpd = create_server("127.0.0.1", 0, service)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", service
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def request(server, path, method="GET", body=None):
    req = Request(server[0] + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        response = urlopen(req, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read().decode("utf-8")


def test_static_and_health(server):
    status, headers, body = request(server, "/")
    assert status == 200
    assert "智能日报生成器" in body
    assert headers["Content-Type"].startswith("text/html")
    assert json.loads(request(server, "/api/health")[2])["mode"] == "mock"


def test_generate_list_detail_http_chain(server):
    assert json.loads(request(server, "/api/reports")[2]) == {"reports": []}
    status, _, body = request(server, "/api/reports", "POST", b"{}")
    assert status == 200
    report = json.loads(body)["report"]
    rows = json.loads(request(server, "/api/reports")[2])["reports"]
    assert rows[0]["id"] == report["id"]
    status, _, body = request(server, "/api/reports/" + report["id"])
    assert status == 200
    assert json.loads(body)["report"]["markdown"] == report["markdown"]
    assert "代码提交" in body


@pytest.mark.parametrize("path", ["/api/reports/999999", "/api/reports/not-an-id", "/../config.yaml", "/%2e%2e/config.yaml", "/data/web_reports.db", "/missing"])
def test_unknown_paths_are_not_exposed(server, path):
    status, _, body = request(server, path)
    assert status == 404
    assert "error" in json.loads(body)


@pytest.mark.parametrize("body", [b"{bad", b"[]", b'{"unexpected":true}', b"null"])
def test_invalid_json_rejected(server, body):
    assert request(server, "/api/reports", "POST", body)[0] == 400


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_wrong_method(server, method):
    status, _, body = request(server, "/api/reports", method, b"{}")
    assert status == 405
    assert "error" in json.loads(body)


def test_post_empty_body_allowed(server):
    assert request(server, "/api/reports", "POST", b"")[0] == 200


def test_internal_error_safe_and_recoverable(server):
    with patch.object(server[1], "create_report", side_effect=RuntimeError("secret/path/token")):
        status, _, body = request(server, "/api/reports", "POST", b"{}")
    assert status == 500
    assert "secret" not in body
    assert "error" in json.loads(body)
    assert request(server, "/api/reports", "POST", b"{}")[0] == 200
