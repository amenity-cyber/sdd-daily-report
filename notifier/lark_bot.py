"""飞书推送模块：通过应用机器人 API 发送 Markdown 日报"""
import os
import time

import httpx

from shared.logger import get_logger

logger = get_logger(__name__)

LARK_API_BASE = "https://open.feishu.cn/open-apis"


def _get_tenant_access_token() -> str | None:
    app_id = os.getenv("LARK_APP_ID")
    app_secret = os.getenv("LARK_APP_SECRET")
    if not app_id or not app_secret:
        logger.error("缺少环境变量 LARK_APP_ID 或 LARK_APP_SECRET")
        return None
    try:
        client_options = {"timeout": 10, "trust_env": False}
        if os.environ.get("APP_HTTP_PROXY"):
            client_options["proxy"] = os.environ["APP_HTTP_PROXY"]
        with httpx.Client(**client_options) as client:
            resp = client.post(
                f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token")
            logger.error(f"获取 tenant_access_token 失败: {data}")
            return None
    except Exception as e:
        logger.error(f"获取 tenant_access_token 异常: {e}")
        return None


def send(report, chat_id: str) -> bool:
    """通过飞书应用机器人 API 发送 Markdown 日报"""
    if not chat_id or not chat_id.startswith("oc_"):
        logger.error(f"chat_id 格式不正确，应为 oc_xxxxx: {chat_id}")
        return False

    token = _get_tenant_access_token()
    if not token:
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    content_text = report.markdown.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": '{"text": "' + content_text + '"}',
    }

    for attempt in range(1, 4):
        try:
            client_options = {"timeout": 30, "trust_env": False}
            if os.environ.get("APP_HTTP_PROXY"):
                client_options["proxy"] = os.environ["APP_HTTP_PROXY"]
            with httpx.Client(**client_options) as client:
                resp = client.post(
                    f"{LARK_API_BASE}/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers=headers,
                    json=payload,
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(f"飞书推送成功: {chat_id}")
                    return True
                logger.error(f"飞书推送失败（第 {attempt} 次）: code={data.get('code')}, msg={data.get('msg')}")
        except Exception as e:
            logger.error(f"飞书推送异常（第 {attempt} 次）: {e}")

        if attempt < 3:
            time.sleep(5)

    logger.error("飞书推送最终失败")
    return False
