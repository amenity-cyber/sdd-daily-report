"""邮件推送模块：将 HTML 日报通过 SMTP 发送给指定收件人"""
import os
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from shared.logger import get_logger
from shared.errors import NotifierError

logger = get_logger(__name__)


def send(report, recipients: list[str]) -> bool:
    """
    通过 SMTP 发送 HTML 格式日报。

    Args:
        report: DailyReport 对象
        recipients: 收件人邮箱列表

    Returns:
        True 表示发送成功，False 表示失败（重试 2 次后）

    环境变量:
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    """
    if not recipients:
        logger.error("收件人列表为空")
        return False

    smtp_host = os.getenv("SMTP_HOST", "localhost")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@company.com")

    subject = f"[{report.team_name}] 日报 - {report.date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(report.html, "html", "utf-8"))

    for attempt in range(1, 4):  # 最多 3 次（首次 + 重试 2 次）
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if smtp_user and smtp_password:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, recipients, msg.as_string())
            logger.info(f"邮件发送成功: {recipients}")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败（第 {attempt} 次）: {e}")
            if attempt < 3:
                time.sleep(5)

    logger.error("邮件发送最终失败")
    return False