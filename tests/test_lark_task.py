"""飞书任务清单采集测试；所有 API 响应均由本地 mock 提供。"""
from datetime import datetime
from unittest.mock import patch

import httpx
from datetime import timezone

from collector.lark_task import TOKEN_PATH, TaskRecord, collect


PROJECT_ID = "list-1"
SINCE = datetime(2026, 9, 24)
UNTIL = datetime(2026, 9, 25)


def response(payload):
    return httpx.Response(
        status_code=200,
        json=payload,
        request=httpx.Request("GET", "https://open.feishu.cn"),
    )


class MockClient:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, path, **kwargs):
        return self.handler("POST", path, kwargs)

    def get(self, path, **kwargs):
        return self.handler("GET", path, kwargs)


def test_collects_tasks_from_tasklists(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "test-app")
    monkeypatch.setenv("LARK_APP_SECRET", "test-secret")
    calls = []

    def handler(method, path, kwargs):
        calls.append((method, path, kwargs))
        if path == TOKEN_PATH:
            return response({"code": 0, "tenant_access_token": "test-token"})
        if path == "/open-apis/task/v2/tasklists":
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"
            return response({"code": 0, "data": {"items": [{"guid": PROJECT_ID}]}})
        if path == f"/open-apis/task/v2/tasklists/{PROJECT_ID}/tasks":
            return response({"code": 0, "data": {"items": [{
                "guid": "task-1",
                "summary": "日报图表联调",
            }]}})
        if path == "/open-apis/task/v2/tasks/task-1":
            return response({"code": 0, "data": {"task": {
                "guid": "task-1",
                "summary": "日报图表联调",
                "status": "done",
                "members": [{"name": "演示成员"}],
                "updated_at": str(int(datetime(2026, 9, 24, 12, tzinfo=timezone.utc).timestamp() * 1000)),
            }}})
        raise AssertionError(path)

    monkeypatch.setattr("collector.lark_task.httpx.Client", lambda **kwargs: MockClient(handler))
    records = collect(PROJECT_ID, SINCE, UNTIL)

    assert len(records) == 1
    assert isinstance(records[0], TaskRecord)
    assert records[0].title == "日报图表联调"
    assert records[0].assignee == "演示成员"
    assert records[0].status_to == "已完成"
    assert isinstance(records[0].updated_at, datetime)
    assert len(calls) == 4


def test_collect_filters_tasks_outside_requested_window(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "test-app")
    monkeypatch.setenv("LARK_APP_SECRET", "test-secret")
    in_window = int(datetime(2026, 9, 24, 12, tzinfo=timezone.utc).timestamp() * 1000)
    old_task = int(datetime(2026, 9, 20, 12, tzinfo=timezone.utc).timestamp() * 1000)

    def handler(method, path, kwargs):
        if path == TOKEN_PATH:
            return response({"code": 0, "tenant_access_token": "test-token"})
        if path == "/open-apis/task/v2/tasklists":
            return response({"code": 0, "data": {"items": [{"guid": PROJECT_ID}]}})
        if path.endswith("/tasks"):
            return response({"code": 0, "data": {"items": [
                {"guid": "new", "summary": "本周任务", "status": "done"},
                {"guid": "old", "summary": "历史任务", "status": "done"},
                {"guid": "missing", "summary": "时间缺失任务", "status": "done"},
            ]}})
        if path.endswith("/tasks/new"):
            return response({"code": 0, "data": {"task": {"updated_at": str(in_window)}}})
        if path.endswith("/tasks/old"):
            return response({"code": 0, "data": {"task": {"updated_at": str(old_task)}}})
        if path.endswith("/tasks/missing"):
            return response({"code": 0, "data": {"task": {}}})
        raise AssertionError(path)

    monkeypatch.setattr("collector.lark_task.httpx.Client", lambda **kwargs: MockClient(handler))
    records = collect(PROJECT_ID, SINCE, UNTIL)
    assert [record.title for record in records] == ["本周任务"]


def test_missing_credentials_skips_external_request(monkeypatch):
    monkeypatch.delenv("LARK_APP_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)
    with patch("collector.lark_task.httpx.Client") as client:
        assert collect(PROJECT_ID, SINCE, UNTIL) == []
        client.assert_not_called()


def test_tasklist_api_error_returns_no_records(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "test-app")
    monkeypatch.setenv("LARK_APP_SECRET", "test-secret")

    def handler(method, path, kwargs):
        if path == TOKEN_PATH:
            return response({"code": 0, "tenant_access_token": "test-token"})
        return response({"code": 999, "msg": "mock failure"})

    monkeypatch.setattr("collector.lark_task.httpx.Client", lambda **kwargs: MockClient(handler))
    assert collect(PROJECT_ID, SINCE, UNTIL) == []
