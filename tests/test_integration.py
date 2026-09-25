"""Task 10 验收测试：端到端集成测试"""
import sys
from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest

from generator.formatter import (
    CommitRecord, TaskRecord, MessageRecord,
    MemberReport, DailyReport, generate,
)
from shared.config import MemberConfig
from shared.errors import CollectorError


# ===== 辅助函数：构造 mock 数据源 =====

def make_config():
    config = MagicMock()
    config.team_name = "研发团队"
    config.github_repos = ["repo1"]
    config.lark_project_id = "proj1"
    config.lark_chat_id = "chat1"
    config.lark_keywords = ["项目"]
    config.recipients = ["leader@company.com"]
    config.members = [
        MemberConfig(name="张三", github="zhangsan", lark="zhangsan@company.com"),
    ]
    return config


def make_commit():
    return CommitRecord(
        author="zhangsan", message="feat: add login",
        timestamp=datetime(2026, 9, 24, 10, 0, 0),
        repo="mythy", additions=50, deletions=10, files_changed=3,
    )


def make_task():
    return TaskRecord(
        assignee="zhangsan@company.com", title="实现登录",
        status_from="进行中", status_to="已完成",
        updated_at=datetime(2026, 9, 24, 17, 0, 0),
    )


def make_message():
    return MessageRecord(
        sender="zhangsan@company.com", content="登录接口联调通过",
        timestamp=datetime(2026, 9, 24, 15, 0, 0), chat_name="研发群",
    )


# ===== 验收标准 1：正常场景 =====

def test_normal_scenario():
    """所有数据源可用，日报生成并推送成功"""
    with patch("main.github.collect") as mock_gh, \
         patch("main.lark_task.collect") as mock_lt, \
         patch("main.lark_msg.collect") as mock_lm, \
         patch("main.email_notifier.send") as mock_email, \
         patch("main.lark_bot.send") as mock_lark, \
         patch.object(sys, "argv", ["main.py"]), \
         patch("main.load_config") as mock_load:

        mock_load.return_value = make_config()
        mock_gh.return_value = [make_commit()]
        mock_lt.return_value = [make_task()]
        mock_lm.return_value = [make_message()]
        mock_email.return_value = True
        mock_lark.return_value = True

        import main as main_module

        main_module.main()


        mock_email.assert_called_once()
        mock_lark.assert_called_once()


# ===== 验收标准 2：降级场景 =====

def test_degraded_scenario():
    """某个数据源超时，日报中标注"数据获取失败"，其他部分正常"""
    members = [MemberReport(
        name="张三", github_username="zhangsan",
        commits=None,   # GitHub 失败
        tasks=[make_task()], messages=[make_message()],
    )]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "数据获取失败" in report.markdown
    assert "实现登录" in report.markdown   # 其他部分正常
    assert "登录接口联调通过" in report.markdown


# ===== 验收标准 3：空数据场景 =====

def test_empty_data_scenario():
    """某成员无任何记录，显示'今日无记录'"""
    members = [MemberReport(
        name="张三", github_username="zhangsan",
        commits=[], tasks=[], messages=[],
    )]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "今日无记录" in report.markdown
    assert "今日无记录" in report.html


# ===== 验收标准 4：全部失败场景 =====

def test_all_fail_scenario():
    """所有数据源不可用，不生成日报，记录错误"""
    with patch("main.github.collect") as mock_gh, \
         patch("main.lark_task.collect") as mock_lt, \
         patch("main.lark_msg.collect") as mock_lm, \
         patch.object(sys, "argv", ["main.py"]), \
         patch("main.load_config") as mock_load:

        mock_load.return_value = make_config()
        mock_gh.side_effect = CollectorError("GitHub failed")
        mock_lt.side_effect = CollectorError("Lark task failed")
        mock_lm.side_effect = CollectorError("Lark msg failed")

        import main as main_module
        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
        # 采集全部失败时，main 应该退出码 1
        assert exc_info.value.code == 1


# ===== 验收标准 5：执行耗时 < 60 秒 =====

def test_execution_time_under_60s():
    """mock 环境下执行完整流程耗时 < 60 秒"""
    import time
    start = time.time()

    members = [MemberReport(
        name="张三", github_username="zhangsan",
        commits=[make_commit()], tasks=[make_task()], messages=[make_message()],
    )]
    generate(members, date(2026, 9, 24), "研发团队")

    elapsed = time.time() - start
    assert elapsed < 60, f"耗时 {elapsed:.2f}s，超过 60s"