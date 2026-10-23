"""Task 9 验收测试：主编排入口"""
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

import main as main_module


# ===== 验收标准 1：--check 模式能验证配置 =====

def test_check_mode():
    with patch.object(sys, "argv", ["main.py", "--check"]), \
         patch("main.load_config") as mock_load:
        mock_config = MagicMock()
        mock_config.team_name = "研发团队"
        mock_config.members = [MagicMock(name="张三")]
        mock_config.github_repos = ["repo1"]
        mock_load.return_value = mock_config

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
        assert exc_info.value.code == 0


# ===== 验收标准 2：--dry-run 模式跳过推送 =====

def test_dry_run_skips_push():
    with patch.object(sys, "argv", ["main.py", "--dry-run"]), \
         patch("main.load_config") as mock_load, \
         patch("main.collect_all") as mock_collect, \
         patch("main.generate") as mock_generate, \
         patch("main.email_notifier.send") as mock_email, \
         patch("main.lark_bot.send") as mock_lark:

        mock_config = MagicMock()
        mock_config.team_name = "研发团队"
        mock_load.return_value = mock_config

        mock_collect.return_value = {"张三": MagicMock()}
        mock_generate.return_value = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
        assert exc_info.value.code == 0

        # dry-run 不应调用推送
        mock_email.assert_not_called()
        mock_lark.assert_not_called()


# ===== 验收标准 3：单个数据源失败不影响其他 =====

def test_single_source_failure_does_not_block_others():
    with patch("main.github.collect") as mock_github, \
         patch("main.lark_task.collect") as mock_lark_task:

        mock_github.side_effect = Exception("GitHub failed")
        mock_lark_task.return_value = [MagicMock(assignee="zhangsan@company.com")]

        from main import collect_all
        from shared.config import MemberConfig
        config = MagicMock()
        config.github_repos = ["repo1"]
        config.lark_project_id = "proj1"
        config.members = [MemberConfig(name="张三", github="zhangsan")]

        from datetime import datetime
        reports = collect_all(config, datetime.now(), datetime.now())
        # GitHub 失败但其他成功，reports 应该仍有内容
        assert reports["张三"].commits is None  # GitHub 失败
        assert reports["张三"].tasks is not None  # 飞书任务成功


# ===== 验收标准 4：所有数据源失败时不生成空日报 =====

def test_all_sources_fail_raises():
    with patch("main.github.collect") as mock_github, \
         patch("main.lark_task.collect") as mock_lark_task:

        mock_github.side_effect = Exception("GitHub failed")
        mock_lark_task.side_effect = Exception("Lark task failed")

        from main import collect_all
        from shared.config import MemberConfig
        config = MagicMock()
        config.github_repos = ["repo1"]
        config.lark_project_id = "proj1"
        config.members = [MemberConfig(name="张三", github="zhangsan")]

        from shared.errors import CollectorError
        from datetime import datetime
        with pytest.raises(CollectorError):
            collect_all(config, datetime.now(), datetime.now())


# ===== 验收标准 5：--check 健康检查失败退出码 1 =====

def test_check_mode_failure():
    with patch.object(sys, "argv", ["main.py", "--check"]), \
         patch("main.load_config") as mock_load:
        mock_config = MagicMock()
        mock_config.team_name = None  # 缺必填
        mock_load.return_value = mock_config

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
        assert exc_info.value.code == 1


def test_email_only_failure_returns_nonzero_for_ci():
    config = SimpleNamespace(
        team_name="闫宣妤", notify=SimpleNamespace(email=SimpleNamespace(recipients=["test@example.com"])),
    )
    report = SimpleNamespace(date=date.today(), team_name="闫宣妤", members=[])
    with patch.object(sys, "argv", ["main.py", "--email-only"]), \
         patch("main.load_config", return_value=config), \
         patch("main.collect_all", return_value={}), \
         patch("main.generate", return_value=report), \
         patch("main.collect_activity_analytics", return_value={"today": {}, "week": []}), \
         patch("main.email_notifier.send", return_value=False), \
         patch("main.lark_bot.send") as lark_send:
        with pytest.raises(SystemExit) as exc_info:
            main_module.main()
    assert exc_info.value.code == 1
    lark_send.assert_not_called()


def test_local_git_fallback_parses_commit_and_diff_stats(monkeypatch):
    member = SimpleNamespace(name="Ada", github="ada")
    responses = [
        SimpleNamespace(returncode=0, stdout="https://github.com/example/reports.git\n"),
        SimpleNamespace(returncode=0, stdout="sha1\x1f2026-10-20T10:00:00+08:00\x1fAda\x1ffeat: report charts\n"),
        SimpleNamespace(returncode=0, stdout="12\t3\tmain.py\n-\t-\tchart.png\n"),
    ]
    monkeypatch.setattr(main_module.subprocess, "run", lambda *args, **kwargs: responses.pop(0))

    commits = main_module._local_git_commits(
        ["example/reports"], datetime(2026, 10, 20), datetime(2026, 10, 21), [member]
    )

    assert len(commits) == 1
    assert commits[0].author == "ada"
    assert commits[0].message == "feat: report charts"
    assert commits[0].additions == 12
    assert commits[0].deletions == 3
    assert commits[0].files_changed == 2


def test_activity_analytics_covers_seven_days_ending_today():
    from generator.formatter import CommitRecord, MemberReport, TaskRecord

    tz = timezone(timedelta(hours=8))
    today = datetime(2026, 10, 20, 23, 0, tzinfo=tz)
    since = today.replace(hour=0, minute=0)
    member = SimpleNamespace(name="闫宣妤", github="yanxuanyu")
    config = SimpleNamespace(
        github=SimpleNamespace(repos=["amenity-cyber/sdd-daily-report"]),
        lark=SimpleNamespace(project_id="project"),
        members=[member],
    )
    commits = [
        CommitRecord("yanxuanyu", "start week", datetime(2026, 10, 14, 10, tzinfo=tz), "repo", 1, 0, 1),
        CommitRecord("yanxuanyu", "today", datetime(2026, 10, 20, 10, tzinfo=tz), "repo", 1, 0, 1),
        CommitRecord("yanxuanyu", "future", datetime(2026, 10, 21, 10, tzinfo=tz), "repo", 1, 0, 1),
    ]
    tasks = [TaskRecord("yanxuanyu", "today task", "open", "done", datetime(2026, 10, 20, 11, tzinfo=tz))]
    report = MemberReport("闫宣妤", "yanxuanyu", commits=[commits[1]], tasks=tasks)

    with patch("main.github.collect", return_value=commits) as github_collect, \
         patch("main.lark_task.collect", return_value=tasks) as task_collect:
        analytics = main_module.collect_activity_analytics(config, {"闫宣妤": report}, since, today)

    assert github_collect.call_args.args[1] == datetime(2026, 10, 14, 0, 0, tzinfo=tz)
    assert task_collect.call_args.args[1] == datetime(2026, 10, 14, 0, 0, tzinfo=tz)
    assert [row["date"] for row in analytics["week"]] == [
        (date(2026, 10, 14) + timedelta(days=offset)).isoformat() for offset in range(7)
    ]
    assert [row["commits"] for row in analytics["week"]] == [1, 0, 0, 0, 0, 0, 1]
    assert analytics["today"] == {"commits": 1, "tasks": 1}
