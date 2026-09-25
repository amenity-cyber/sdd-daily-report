"""飞书任务采集模块单元测试（全部使用 mock 数据）。"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any, get_type_hints
from unittest.mock import MagicMock

import httpx
import pytest

from collector.lark_task import TOKEN_PATH, TASKS_PATH, TaskRecord, collect


SINCE = datetime(2026, 9, 24, 0, 0, 0)
UNTIL = datetime(2026, 9, 24, 18, 0, 0)
PROJECT_ID = "proj-1"
APP_ID = "cli_test"
APP_SECRET = "secret_test"


def _json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("GET", "https://open.feishu.cn"),
    )


def _token_ok() -> dict[str, Any]:
    return {"code": 0, "tenant_access_token": "t-valid", "expire": 7200}


def _task_item() -> dict[str, Any]:
    return {
        "assignee": "zhangsan@company.com",
        "title": "修复登录超时",
        "status_from": "进行中",
        "status_to": "已完成",
        "updated_at": "2026-09-24T10:00:00Z",
    }


class MockClient:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        self.calls.append((method.upper(), path, kwargs.get("headers")))
        return self._handler(method.upper(), path, kwargs)

    def post(self, path: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response:
        return self.request("POST", path, json=json, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: MockClient) -> MockClient:
    monkeypatch.setattr("collector.lark_task.httpx.Client", lambda **kwargs: client)
    return client


@pytest.fixture
def lark_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LARK_APP_ID", APP_ID)
    monkeypatch.setenv("LARK_APP_SECRET", APP_SECRET)


class TestCollectSignature:
    def test_signature_matches_contract(self):
        signature = inspect.signature(collect)
        assert list(signature.parameters) == ["project_id", "since", "until"]
        hints = get_type_hints(collect)
        assert hints["project_id"] is str
        assert hints["since"] is datetime
        assert hints["until"] is datetime
        assert hints["return"] == list[TaskRecord]


class TestTaskRecord:
    def test_returns_five_typed_fields(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        def handler(method: str, path: str, kwargs: dict[str, Any]):
            if path == TOKEN_PATH:
                return _json_response(_token_ok())
            return _json_response({"code": 0, "data": {"items": [_task_item()]}})

        _patch_client(monkeypatch, MockClient(handler))
        records = collect(PROJECT_ID, SINCE, UNTIL)

        assert len(records) == 1
        record = records[0]
        assert isinstance(record, TaskRecord)
        assert record.assignee == "zhangsan@company.com"
        assert isinstance(record.assignee, str)
        assert record.title == "修复登录超时"
        assert isinstance(record.title, str)
        assert record.status_from == "进行中"
        assert isinstance(record.status_from, str)
        assert record.status_to == "已完成"
        assert isinstance(record.status_to, str)
        assert record.updated_at == datetime.fromisoformat("2026-09-24T10:00:00+00:00")
        assert isinstance(record.updated_at, datetime)


class TestTokenRefresh:
    def test_expired_token_refreshes_once_and_retries(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        token_calls = {"count": 0}
        task_calls = {"count": 0}

        def handler(method: str, path: str, kwargs: dict[str, Any]):
            if path == TOKEN_PATH:
                token_calls["count"] += 1
                token = "t-first" if token_calls["count"] == 1 else "t-refreshed"
                return _json_response({"code": 0, "tenant_access_token": token})
            if path == TASKS_PATH:
                task_calls["count"] += 1
                auth = (kwargs.get("headers") or {}).get("Authorization")
                if auth == "Bearer t-first":
                    return _json_response({"code": 99991663, "msg": "token invalid"})
                return _json_response({"code": 0, "data": {"items": [_task_item()]}})
            raise AssertionError(path)

        _patch_client(monkeypatch, MockClient(handler))
        records = collect(PROJECT_ID, SINCE, UNTIL)

        assert len(records) == 1
        assert records[0].title == "修复登录超时"
        assert token_calls["count"] == 2
        assert task_calls["count"] == 2


class TestTimeoutRetry:
    def test_retries_three_times_then_returns_empty_and_logs_error(
        self, monkeypatch: pytest.MonkeyPatch, lark_env, caplog: pytest.LogCaptureFixture
    ):
        sleep = MagicMock()
        monkeypatch.setattr("collector.lark_task.time.sleep", sleep)
        attempts = {"count": 0}

        def handler(method: str, path: str, kwargs: dict[str, Any]):
            if path == TOKEN_PATH:
                return _json_response(_token_ok())
            attempts["count"] += 1
            raise httpx.TimeoutException("request timed out")

        _patch_client(monkeypatch, MockClient(handler))
        logging.getLogger("collector.lark_task").propagate = True

        with caplog.at_level(logging.ERROR, logger="collector.lark_task"):
            records = collect(PROJECT_ID, SINCE, UNTIL)

        assert records == []
        assert attempts["count"] == 3
        assert sleep.call_count == 2
        assert all(call.args[0] == 5 for call in sleep.call_args_list)
        assert any("超时" in message for message in caplog.messages)
