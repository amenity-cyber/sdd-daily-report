"""邮件推送模块：将 HTML 日报通过 SMTP 发送给指定收件人"""
import os
import re
import smtplib
import time
from html import escape
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from shared.logger import get_logger
from notifier.charts import render_email_charts

logger = get_logger(__name__)


def send(report, recipients: list[str], analytics: dict | None = None) -> bool:
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

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    try:
        smtp_port = int(os.getenv("SMTP_PORT") or "587")
    except ValueError:
        logger.error("SMTP_PORT 配置无效")
        return False
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM") or smtp_user
    if not smtp_host or not 1 <= smtp_port <= 65535 or not smtp_user or not smtp_password or not smtp_from:
        logger.error("邮件服务配置不完整；需要有效 SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD")
        return False

    report_name = report.team_name
    subject = f"研一+{report_name}+{report.date}+智能日报"

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)

    alternative = MIMEMultipart("alternative")
    msg.attach(alternative)
    alternative.attach(MIMEText(report.markdown or "日报详见 HTML 邮件正文。", "plain", "utf-8"))

    html = report.html
    title = f"{escape(report.team_name)} 今日日报"
    html, _ = re.subn(r"<h1\b[^>]*>.*?</h1>", f"<h1>{title}</h1>", html, count=1, flags=re.IGNORECASE | re.DOTALL)

    if analytics is not None:
        charts, html = render_email_charts(analytics, html)
        alternative.attach(MIMEText(html, "html", "utf-8"))
        for content_id, image_bytes in charts.items():
            image = MIMEImage(image_bytes, _subtype="png")
            image.add_header("Content-ID", f"<{content_id}>")
            image.add_header("Content-Disposition", "inline", filename=f"{content_id}.png")
            msg.attach(image)
    else:
        alternative.attach(MIMEText(html, "html", "utf-8"))

    for attempt in range(1, 4):  # 最多 3 次（首次 + 重试 2 次）
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_from, recipients, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
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
