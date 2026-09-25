"""Task 7 验收测试：邮件推送模块"""
from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest

from generator.formatter import DailyReport, MemberReport
from notifier.email import send


def make_report():
    return DailyReport(
        date=date(2026, 9, 24),
        team_name="研发团队",
        members=[MemberReport(name="张三", github_username="zhangsan",
                              commits=[], tasks=[], messages=[])],
        generated_at=datetime(2026, 9, 24, 18, 0, 0),
        markdown="# 日报",
        html="<html><body>日报</body></html>",
    )


# ===== 验收标准 1：函数签名符合 §4.3 =====

def test_send_signature():
    """send(report, recipients) -> bool"""
    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        result = send(make_report(), ["leader@company.com"])
        assert isinstance(result, bool)
        assert result is True


# ===== 验收标准 2：邮件主题含日期和团队名 =====

def test_email_subject_contains_date_and_team():
    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        send(make_report(), ["leader@company.com"])
        args, kwargs = mock_server.sendmail.call_args
        msg_str = args[2]
        # 主题被 Base64 编码，解码后检查中文和日期
        import email
        from email.header import decode_header
        msg = email.message_from_string(msg_str)
        raw_subject = msg["Subject"]
        decoded_parts = decode_header(raw_subject)
        subject = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )
        assert "研发团队" in subject
        assert "2026-09-24" in subject


# ===== 验收标准 3：邮件正文为 HTML =====

def test_email_body_is_html():
    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        send(make_report(), ["leader@company.com"])
        args, kwargs = mock_server.sendmail.call_args
        msg_str = args[2]
        # HTML 部分被 Base64 编码，检查 Content-Type 即可
        assert "text/html" in msg_str
        # 解码 HTML 部分验证
        import email
        msg = email.message_from_string(msg_str)
        html_part = None
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html_part = part.get_payload(decode=True).decode("utf-8")
                break
        assert html_part is not None
        assert "<html>" in html_part

# ===== 验收标准 4：失败重试 2 次 =====

def test_retry_on_failure():
    with patch("smtplib.SMTP") as mock_smtp, patch("time.sleep"):
        mock_smtp.side_effect = Exception("SMTP connection failed")
        result = send(make_report(), ["leader@company.com"])
        assert result is False
        # 首次 + 重试 2 次 = 3 次调用
        assert mock_smtp.call_count == 3


# ===== 验收标准 5：收件人为空返回 False =====

def test_empty_recipients_returns_false():
    result = send(make_report(), [])
    assert result is False