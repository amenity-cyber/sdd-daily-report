"""Web 日报服务的业务验收，不连接真实第三方平台。"""
from datetime import date, datetime
from unittest.mock import Mock

import pytest

from shared.storage import ReportStorage
from web_backend.service import ReportService


@pytest.fixture
def service(tmp_path):
    return ReportService(ReportStorage(tmp_path / "reports.db"))


def test_empty_history(service):
    assert service.list_reports() == []


def test_generate_detail_and_persist(service):
    report = service.create_report()
    assert report["status"] == "已完成"
    for heading in ("代码提交", "任务进展", "协作沟通"):
        assert heading in report["markdown"]
    assert "Mock" in report["source"]
    assert service.get_report(report["id"])["markdown"] == report["markdown"]
    assert "markdown" not in service.list_reports()[0]
    reopened = ReportService(ReportStorage(service.storage.db_path))
    assert reopened.get_report(report["id"])["markdown"] == report["markdown"]


def test_regenerate_today_keeps_id_and_single_record(service):
    first = service.create_report()
    second = service.create_report()
    assert second["id"] == first["id"]
    assert len(service.list_reports()) == 1
    assert service.get_report(second["id"])["markdown"] == second["markdown"]


def test_history_and_unknown_id(service):
    service.storage.save_report(date(2025, 1, 1), "历史团队", "# 历史日报", "<h1>历史日报</h1>", datetime(2025, 1, 1))
    service.create_report()
    assert len(service.list_reports()) == 2
    assert service.get_report("999999") is None
    assert service.get_report("not-an-id") is None


def test_adapter_failure_does_not_write_fake_report(service):
    service.adapter = Mock()
    service.adapter.collect.side_effect = RuntimeError("source unavailable")
    with pytest.raises(RuntimeError, match="source unavailable"):
        service.create_report()
    assert service.list_reports() == []
