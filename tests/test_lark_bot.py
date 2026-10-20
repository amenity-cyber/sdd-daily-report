"""飞书应用机器人推送测试；所有 HTTP 交互均 mock，不会发送消息。"""
import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from generator.formatter import DailyReport, MemberReport
from notifier.lark_bot import send


def make_report():
    return DailyReport(
        date=date(2026, 9, 24),
        team_name="研发团队",
        members=[MemberReport(name="张三", github_username="zhangsan", commits=[], tasks=[], messages=[])],
        generated_at=datetime(2026, 9, 24, 18, 0, 0),
        markdown="# 日报\n\n内容",
        html="<html></html>",
    )


def test_send_signature_and_application_message():
    with patch("notifier.lark_bot._get_tenant_access_token", return_value="t-valid"), \
         patch("notifier.lark_bot.httpx.Client") as mock_client:
        response = MagicMock()
        response.json.return_value = {"code": 0}
        mock_client.return_value.__enter__.return_value.post.return_value = response

        assert send(make_report(), "oc_test_chat") is True

    _, kwargs = mock_client.return_value.__enter__.return_value.post.call_args
    payload = kwargs["json"]
    assert payload["msg_type"] == "text"
    assert payload["receive_id"] == "oc_test_chat"
    assert json.loads(payload["content"])["text"] == "# 日报\n\n内容"


def test_retry_on_failure():
    with patch("notifier.lark_bot._get_tenant_access_token", return_value="t-valid"), \
         patch("notifier.lark_bot.httpx.Client") as mock_client, \
         patch("notifier.lark_bot.time.sleep"):
        post = mock_client.return_value.__enter__.return_value.post
        post.side_effect = RuntimeError("network error")

        assert send(make_report(), "oc_test_chat") is False
        assert post.call_count == 3


def test_invalid_chat_id_is_rejected_without_http_request():
    with patch("notifier.lark_bot._get_tenant_access_token") as get_token:
        assert send(make_report(), "not-a-chat-id") is False
        get_token.assert_not_called()
