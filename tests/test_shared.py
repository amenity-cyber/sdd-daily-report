"""共享基础层单元测试，覆盖 Task 2 验收标准。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pytest
import yaml

from shared.config import get_config, load_config, reset_config
from shared.errors import CollectorError, ConfigError, GeneratorError, NotifierError
from shared.logger import JsonLinesFormatter, get_logger
from shared.storage import ReportStorage


def _write_config(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _valid_config() -> dict:
    return {
        "team_name": "研发团队",
        "members": [
            {"name": "张三", "github": "zhangsan", "lark": "zhangsan@company.com"},
            {"name": "李四", "github": "lisi-dev", "lark": "lisi@company.com"},
        ],
        "github": {"repos": ["org/repo-a"]},
        "lark": {
            "project_id": "proj-1",
            "chat_id": "chat-1",
            "keywords": ["进度"],
        },
        "notify": {
            "email": {"recipients": ["leader@company.com"]},
            "lark_bot": {"chat_id": "bot-chat-1"},
        },
    }


@pytest.fixture(autouse=True)
def _reset_global_config():
    reset_config()
    yield
    reset_config()


class TestConfig:
    def test_load_config_returns_object(self, tmp_path: Path):
        config_path = _write_config(tmp_path / "config.yaml", _valid_config())
        config = load_config(config_path)

        assert config.team_name == "研发团队"
        assert len(config.members) == 2
        assert config.members[0].name == "张三"
        assert config.members[0].github == "zhangsan"
        assert config.github.repos == ["org/repo-a"]
        assert config.lark.project_id == "proj-1"
        assert config.notify.email.recipients == ["leader@company.com"]
        assert get_config() is config

    def test_missing_required_field_raises_clear_error(self, tmp_path: Path):
        data = _valid_config()
        del data["team_name"]
        config_path = _write_config(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="配置缺少必填字段: team_name"):
            load_config(config_path)

    def test_missing_member_field_raises_clear_error(self, tmp_path: Path):
        data = _valid_config()
        del data["members"][0]["github"]
        config_path = _write_config(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match=r"配置缺少必填字段: members\[0\]\.github"):
            load_config(config_path)

    def test_missing_nested_field_raises_clear_error(self, tmp_path: Path):
        data = _valid_config()
        del data["notify"]["email"]["recipients"]
        config_path = _write_config(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="配置缺少必填字段: notify.email.recipients"):
            load_config(config_path)


class TestLogger:
    def test_logger_outputs_json_lines(self):
        stream = StringIO()
        logger = get_logger("test-json-logger")
        logger.handlers.clear()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonLinesFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("日报生成开始")
        logger.error("数据源不可用")

        lines = [line for line in stream.getvalue().splitlines() if line.strip()]
        assert len(lines) == 2

        info_payload = json.loads(lines[0])
        error_payload = json.loads(lines[1])
        assert info_payload["level"] == "INFO"
        assert info_payload["message"] == "日报生成开始"
        assert "timestamp" in info_payload
        assert error_payload["level"] == "ERROR"
        assert error_payload["message"] == "数据源不可用"


class TestErrors:
    def test_custom_exceptions_exist(self):
        assert issubclass(CollectorError, Exception)
        assert issubclass(GeneratorError, Exception)
        assert issubclass(NotifierError, Exception)

        with pytest.raises(CollectorError, match="采集失败"):
            raise CollectorError("采集失败")
        with pytest.raises(GeneratorError, match="生成失败"):
            raise GeneratorError("生成失败")
        with pytest.raises(NotifierError, match="推送失败"):
            raise NotifierError("推送失败")


class TestStorage:
    def test_create_write_and_query_reports(self, tmp_path: Path):
        db_path = tmp_path / "reports.db"
        storage = ReportStorage(db_path)
        assert db_path.exists()

        report_date = date(2026, 9, 24)
        generated_at = datetime(2026, 9, 24, 18, 0, 0)
        report_id = storage.save_report(
            report_date=report_date,
            team_name="研发团队",
            markdown="# 日报",
            html="<h1>日报</h1>",
            generated_at=generated_at,
        )
        assert report_id > 0

        found = storage.get_report(report_date, team_name="研发团队")
        assert found is not None
        assert found.report_date == report_date
        assert found.team_name == "研发团队"
        assert found.markdown == "# 日报"
        assert found.html == "<h1>日报</h1>"
        assert found.generated_at == generated_at

        reports = storage.list_reports()
        assert len(reports) == 1
        assert reports[0].id == found.id
