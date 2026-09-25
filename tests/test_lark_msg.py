"""飞书消息采集模块单元测试（全部使用 mock 数据）。"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any, get_type_hints
from unittest.mock import MagicMock

import httpx
import pytest

from collector.lark_msg import MESSAGES_PATH, SENSITIVE_KEYWORDS, TOKEN_PATH, MessageRecord, collect


SINCE = datetime(2026, 9, 24, 0, 0, 0)
UNTIL = datetime(2026, 9, 24, 18, 0, 0)
CHAT_ID = "oc_chat_1"
KEYWORDS = ["进度", "阻塞", "完成"]
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


def _message(
    content: str,
    sender: str = "zhangsan@company.com",
    timestamp: str = "2026-09-24T10:00:00Z",
) -> dict[str, Any]:
    return {
        "sender": sender,
        "content": content,
        "timestamp": timestamp,
        "chat_name": "研发群",
    }


class MockClient:
    def __init__(self, handler) -> None:
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return self._handler(method.upper(), path, kwargs)

    def post(self, path: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response:
        return self.request("POST", path, json=json, **kwargs)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: MockClient) -> MockClient:
    monkeypatch.setattr("collector.lark_msg.httpx.Client", lambda **kwargs: client)
    return client


def _default_handler(items: list[dict[str, Any]]):
    def handler(method: str, path: str, kwargs: dict[str, Any]):
        if path == TOKEN_PATH:
            return _json_response(_token_ok())
        if path.startswith("/open-apis/im/v1/chats/"):
            return _json_response({"code": 0, "data": {"name": "研发群"}})
        if path == MESSAGES_PATH:
            return _json_response({"code": 0, "data": {"items": items}})
        raise AssertionError(path)

    return handler


@pytest.fixture
def lark_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LARK_APP_ID", APP_ID)
    monkeypatch.setenv("LARK_APP_SECRET", APP_SECRET)


class TestCollectSignature:
    def test_signature_matches_contract(self):
        signature = inspect.signature(collect)
        assert list(signature.parameters) == ["chat_id", "keywords", "since", "until"]
        hints = get_type_hints(collect)
        assert hints["chat_id"] is str
        assert hints["keywords"] == list[str]
        assert hints["since"] is datetime
        assert hints["until"] is datetime
        assert hints["return"] == list[MessageRecord]


class TestMessageRecord:
    def test_returns_four_typed_fields(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        _patch_client(monkeypatch, MockClient(_default_handler([_message("今日进度正常")])))
        records = collect(CHAT_ID, KEYWORDS, SINCE, UNTIL)

        assert len(records) == 1
        record = records[0]
        assert isinstance(record, MessageRecord)
        assert record.sender == "zhangsan@company.com"
        assert isinstance(record.sender, str)
        assert record.content == "今日进度正常"
        assert isinstance(record.content, str)
        assert record.timestamp == datetime.fromisoformat("2026-09-24T10:00:00+00:00")
        assert isinstance(record.timestamp, datetime)
        assert record.chat_name == "研发群"
        assert isinstance(record.chat_name, str)


class TestKeywordFilter:
    def test_keeps_only_messages_containing_keywords(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        items = [
            _message("今日进度正常"),
            _message("午饭吃什么"),
            _message("登录功能已完成"),
            _message("被阻塞在测试环境"),
        ]
        _patch_client(monkeypatch, MockClient(_default_handler(items)))
        records = collect(CHAT_ID, KEYWORDS, SINCE, UNTIL)
        contents = [item.content for item in records]
        assert contents == ["今日进度正常", "登录功能已完成", "被阻塞在测试环境"]


class TestSensitiveFilter:
    def test_filters_salary_performance_and_layoff(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        items = [
            _message("进度：接口联调完成"),
            _message("进度同步：薪资结构调整"),
            _message("完成绩效自评"),
            _message("阻塞：裁员相关流程"),
            _message("有阻塞，需要帮忙"),
        ]
        _patch_client(monkeypatch, MockClient(_default_handler(items)))
        records = collect(CHAT_ID, KEYWORDS, SINCE, UNTIL)
        contents = [item.content for item in records]

        assert "进度：接口联调完成" in contents
        assert "有阻塞，需要帮忙" in contents
        for sensitive in SENSITIVE_KEYWORDS:
            assert all(sensitive not in text for text in contents)
        assert len(records) == 2


class TestTokenRefresh:
    def test_expired_token_refreshes_once_and_retries(self, monkeypatch: pytest.MonkeyPatch, lark_env):
        token_calls = {"count": 0}
        chat_calls = {"count": 0}

        def handler(method: str, path: str, kwargs: dict[str, Any]):
            if path == TOKEN_PATH:
                token_calls["count"] += 1
                token = "t-first" if token_calls["count"] == 1 else "t-refreshed"
                return _json_response({"code": 0, "tenant_access_token": token})
            auth = (kwargs.get("headers") or {}).get("Authorization")
            if auth == "Bearer t-first":
                return _json_response({"code": 99991663, "msg": "token invalid"})
            if path.startswith("/open-apis/im/v1/chats/"):
                chat_calls["count"] += 1
                return _json_response({"code": 0, "data": {"name": "研发群"}})
            if path == MESSAGES_PATH:
                return _json_response({"code": 0, "data": {"items": [_message("今日进度正常")]}})
            raise AssertionError(path)

        _patch_client(monkeypatch, MockClient(handler))
        records = collect(CHAT_ID, KEYWORDS, SINCE, UNTIL)

        assert len(records) == 1
        assert token_calls["count"] >= 2
        assert chat_calls["count"] == 1


class TestTimeoutRetry:
    def test_retries_three_times_then_returns_empty_and_logs_error(
        self, monkeypatch: pytest.MonkeyPatch, lark_env, caplog: pytest.LogCaptureFixture
    ):
        sleep = MagicMock()
        monkeypatch.setattr("collector.lark_msg.time.sleep", sleep)
        attempts = {"count": 0}

        def handler(method: str, path: str, kwargs: dict[str, Any]):
            if path == TOKEN_PATH:
                return _json_response(_token_ok())
            if path.startswith("/open-apis/im/v1/chats/"):
                return _json_response({"code": 0, "data": {"name": "研发群"}})
            attempts["count"] += 1
            raise httpx.TimeoutException("request timed out")

        _patch_client(monkeypatch, MockClient(handler))
        logging.getLogger("collector.lark_msg").propagate = True

        with caplog.at_level(logging.ERROR, logger="collector.lark_msg"):
            records = collect(CHAT_ID, KEYWORDS, SINCE, UNTIL)

        assert records == []
        assert attempts["count"] == 3
        assert sleep.call_count == 2
        assert all(call.args[0] == 5 for call in sleep.call_args_list)
        assert any("超时" in message for message in caplog.messages)
