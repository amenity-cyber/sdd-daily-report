"""Task 8 验收测试：飞书推送模块"""
from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest

from generator.formatter import DailyReport, MemberReport
from notifier.lark_bot import send


def make_report():
    return DailyReport(
        date=date(2026, 9, 24),
        team_name="研发团队",
        members=[MemberReport(name="张三", github_username="zhangsan",
                              commits=[], tasks=[], messages=[])],
        generated_at=datetime(2026, 9, 24, 18, 0, 0),
        markdown="# 日报\n\n内容",
        html="<html></html>",
    )


# ===== 验收标准 1：函数签名符合 §4.3 =====

def test_send_signature():
    """send(report, chat_id) -> bool"""
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
        result = send(make_report(), "https://open.feishu.cn/webhook/xxx")
        assert isinstance(result, bool)
        assert result is True


# ===== 验收标准 2：发送的消息为 Markdown 格式 =====

def test_send_markdown_content():
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post = mock_client.return_value.__enter__.return_value.post
        mock_post.return_value = mock_resp

        send(make_report(), "https://open.feishu.cn/webhook/xxx")

        args, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        assert payload["msg_type"] == "text"
        assert "# 日报" in payload["content"]["text"]


# ===== 验收标准 3：失败重试 2 次 =====

def test_retry_on_failure():
    with patch("httpx.Client") as mock_client, patch("time.sleep"):
        mock_post = mock_client.return_value.__enter__.return_value.post
        mock_post.side_effect = Exception("Network error")

        result = send(make_report(), "https://open.feishu.cn/webhook/xxx")
        assert result is False
        assert mock_post.call_count == 3


# ===== 验收标准 4：无 webhook 配置返回 False =====

def test_missing_webhook_returns_false():
    with patch.dict("os.environ", {}, clear=True):
        result = send(make_report(), "not-a-url")
        assert result is False