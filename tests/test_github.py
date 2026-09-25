"""GitHub 采集模块单元测试（全部使用 mock 数据）。"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any, get_type_hints
from unittest.mock import MagicMock

import httpx
import pytest

from collector.github import PER_PAGE, CommitRecord, collect


SINCE = datetime(2026, 9, 24, 0, 0, 0)
UNTIL = datetime(2026, 9, 24, 18, 0, 0)
REPO = "org/repo-a"


def _commit_summary(index: int) -> dict[str, Any]:
    return {
        "sha": f"sha-{index:03d}",
        "commit": {
            "author": {
                "name": "Zhang San",
                "date": "2026-09-24T10:00:00Z",
            },
            "message": f"commit message {index}",
        },
        "author": {"login": "zhangsan"},
    }


def _commit_detail(index: int) -> dict[str, Any]:
    return {
        "sha": f"sha-{index:03d}",
        "stats": {"additions": 10, "deletions": 2, "total": 12},
        "files": [{"filename": "a.py"}, {"filename": "b.py"}],
    }


def _json_response(payload: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.github.com"),
    )


class MockClient:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self.calls.append((path, params))
        return self._handler(path, params)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: MockClient) -> MockClient:
    monkeypatch.setattr("collector.github.httpx.Client", lambda **kwargs: client)
    return client


class TestCollectSignature:
    def test_signature_matches_contract(self):
        signature = inspect.signature(collect)
        params = list(signature.parameters)
        assert params == ["repos", "since", "until"]
        hints = get_type_hints(collect)
        assert hints["repos"] == list[str]
        assert hints["since"] is datetime
        assert hints["until"] is datetime
        assert hints["return"] == list[CommitRecord]


class TestCommitRecord:
    def test_returns_seven_typed_fields(self, monkeypatch: pytest.MonkeyPatch):
        def handler(path: str, params: dict[str, Any] | None):
            if path.endswith("/commits") and not path.rstrip("/").endswith("sha-001"):
                return _json_response([_commit_summary(1)])
            return _json_response(_commit_detail(1))

        _patch_client(monkeypatch, MockClient(handler))
        records = collect([REPO], SINCE, UNTIL)

        assert len(records) == 1
        record = records[0]
        assert isinstance(record, CommitRecord)
        assert record.author == "zhangsan"
        assert isinstance(record.author, str)
        assert record.message == "commit message 1"
        assert isinstance(record.message, str)
        assert record.timestamp == datetime.fromisoformat("2026-09-24T10:00:00+00:00")
        assert isinstance(record.timestamp, datetime)
        assert record.repo == REPO
        assert isinstance(record.repo, str)
        assert record.additions == 10
        assert isinstance(record.additions, int)
        assert record.deletions == 2
        assert isinstance(record.deletions, int)
        assert record.files_changed == 2
        assert isinstance(record.files_changed, int)


class TestPagination:
    def test_fetches_pages_of_thirty(self, monkeypatch: pytest.MonkeyPatch):
        def handler(path: str, params: dict[str, Any] | None):
            if path == f"/repos/{REPO}/commits":
                page = int((params or {}).get("page", 1))
                per_page = int((params or {}).get("per_page", PER_PAGE))
                assert per_page == 30
                if page == 1:
                    return _json_response([_commit_summary(i) for i in range(1, 31)])
                if page == 2:
                    return _json_response([_commit_summary(i) for i in range(31, 36)])
                return _json_response([])
            sha = path.rsplit("/", 1)[-1]
            index = int(sha.split("-")[1])
            return _json_response(_commit_detail(index))

        client = _patch_client(monkeypatch, MockClient(handler))
        records = collect([REPO], SINCE, UNTIL)

        assert len(records) == 35
        list_calls = [params for path, params in client.calls if path == f"/repos/{REPO}/commits"]
        assert [item["page"] for item in list_calls] == [1, 2]
        assert all(item["per_page"] == 30 for item in list_calls)


class TestTimeoutRetry:
    def test_retries_three_times_then_returns_empty_and_logs_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        sleep = MagicMock()
        monkeypatch.setattr("collector.github.time.sleep", sleep)

        attempts = {"count": 0}

        def handler(path: str, params: dict[str, Any] | None):
            attempts["count"] += 1
            raise httpx.TimeoutException("request timed out")

        _patch_client(monkeypatch, MockClient(handler))
        logger = logging.getLogger("collector.github")
        logger.propagate = True

        with caplog.at_level(logging.ERROR, logger="collector.github"):
            records = collect([REPO], SINCE, UNTIL)

        assert records == []
        assert attempts["count"] == 3
        assert sleep.call_count == 2
        assert all(call.args[0] == 5 for call in sleep.call_args_list)
        assert any("超时" in message for message in caplog.messages)


class TestRateLimit:
    def test_waits_for_reset_header_then_retries(self, monkeypatch: pytest.MonkeyPatch):
        reset_at = 1_800_000_000
        monkeypatch.setattr("collector.github.time.time", lambda: reset_at - 12)
        sleep = MagicMock()
        monkeypatch.setattr("collector.github.time.sleep", sleep)

        state = {"list_calls": 0}

        def handler(path: str, params: dict[str, Any] | None):
            if path == f"/repos/{REPO}/commits":
                state["list_calls"] += 1
                if state["list_calls"] == 1:
                    return _json_response(
                        {"message": "API rate limit exceeded"},
                        status_code=403,
                        headers={"X-RateLimit-Reset": str(reset_at)},
                    )
                return _json_response([_commit_summary(1)])
            return _json_response(_commit_detail(1))

        _patch_client(monkeypatch, MockClient(handler))
        records = collect([REPO], SINCE, UNTIL)

        assert len(records) == 1
        assert records[0].author == "zhangsan"
        sleep.assert_called()
        assert sleep.call_args.args[0] == 12
        assert state["list_calls"] == 2
