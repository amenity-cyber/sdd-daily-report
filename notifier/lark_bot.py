"""飞书推送模块：通过飞书机器人 webhook 发送 Markdown 日报"""
import os
import time

import httpx

from shared.logger import get_logger

logger = get_logger(__name__)


def send(report, chat_id: str) -> bool:
    """
    通过飞书机器人 webhook 发送 Markdown 日报。

    Args:
        report: DailyReport 对象
        chat_id: 飞书群 ID 或 webhook 地址

    Returns:
        True 表示发送成功，False 表示失败（重试 2 次后）

    环境变量:
        LARK_WEBHOOK_URL (若 chat_id 不是完整 URL，则用此环境变量)
    """
    webhook_url = chat_id if chat_id.startswith("http") else os.getenv("LARK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.error("飞书 webhook URL 未配置")
        return False

    payload = {
        "msg_type": "text",
        "content": {
            "text": report.markdown,
        },
    }

    for attempt in range(1, 4):  # 首次 + 重试 2 次
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(webhook_url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"飞书推送成功: {chat_id}")
                    return True
                logger.error(f"飞书推送失败（第 {attempt} 次）: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"飞书推送异常（第 {attempt} 次）: {e}")

        if attempt < 3:
            time.sleep(5)

    logger.error("飞书推送最终失败")
    return False