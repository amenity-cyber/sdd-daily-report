"""Task 9 验收测试：主编排入口"""
import sys
from datetime import date
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
         patch("main.lark_task.collect") as mock_lark_task, \
         patch("main.lark_msg.collect") as mock_lark_msg:

        mock_github.side_effect = Exception("GitHub failed")
        mock_lark_task.return_value = [MagicMock(assignee="zhangsan@company.com")]
        mock_lark_msg.return_value = [MagicMock(sender="zhangsan@company.com")]

        from main import collect_all
        from shared.config import MemberConfig
        config = MagicMock()
        config.github_repos = ["repo1"]
        config.lark_project_id = "proj1"
        config.lark_chat_id = "chat1"
        config.lark_keywords = ["项目"]
        config.members = [MemberConfig(name="张三", github="zhangsan", lark="zhangsan@company.com")]

        from datetime import datetime
        reports = collect_all(config, datetime.now(), datetime.now())
        # GitHub 失败但其他成功，reports 应该仍有内容
        assert reports["张三"].commits is None  # GitHub 失败
        assert reports["张三"].tasks is not None  # 飞书任务成功


# ===== 验收标准 4：所有数据源失败时不生成空日报 =====

def test_all_sources_fail_raises():
    with patch("main.github.collect") as mock_github, \
         patch("main.lark_task.collect") as mock_lark_task, \
         patch("main.lark_msg.collect") as mock_lark_msg:

        mock_github.side_effect = Exception("GitHub failed")
        mock_lark_task.side_effect = Exception("Lark task failed")
        mock_lark_msg.side_effect = Exception("Lark msg failed")

        from main import collect_all
        from shared.config import MemberConfig
        config = MagicMock()
        config.github_repos = ["repo1"]
        config.lark_project_id = "proj1"
        config.lark_chat_id = "chat1"
        config.lark_keywords = ["项目"]
        config.members = [MemberConfig(name="张三", github="zhangsan", lark="zhangsan@company.com")]

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