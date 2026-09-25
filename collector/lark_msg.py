"""从飞书群采集消息，按关键词过滤并剔除敏感内容。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from shared.errors import (
    API_TIMEOUT_INTERVAL_SECONDS,
    API_TIMEOUT_RETRIES,
    LARK_TOKEN_REFRESH_RETRIES,
)
from shared.logger import get_logger

LARK_API_BASE = "https://open.feishu.cn"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
MESSAGES_PATH = "/open-apis/im/v1/messages"
REQUEST_TIMEOUT_SECONDS = 30.0
TOKEN_EXPIRED_CODES = {99991661, 99991663, 99991664}
SENSITIVE_KEYWORDS = ("薪资", "绩效", "裁员")

logger = get_logger("collector.lark_msg")


@dataclass(frozen=True)
class MessageRecord:
    sender: str
    content: str
    timestamp: datetime
    chat_name: str


def collect(
    chat_id: str,
    keywords: list[str],
    since: datetime,
    until: datetime,
) -> list[MessageRecord]:
    """获取群内时间窗口中的消息，仅保留命中关键词且不含敏感词的记录。"""
    app_id = os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("LARK_APP_SECRET")
    if not app_id or not app_secret:
        logger.error("缺少环境变量 LARK_APP_ID 或 LARK_APP_SECRET")
        return []

    try:
        with httpx.Client(base_url=LARK_API_BASE, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            token = _fetch_tenant_token(client, app_id, app_secret)
            if token is None:
                return []
            token_state = {"value": token}
            chat_name = _fetch_chat_name(client, app_id, app_secret, token_state, chat_id) or chat_id
            payload = _request_json(
                client,
                "GET",
                MESSAGES_PATH,
                app_id=app_id,
                app_secret=app_secret,
                token_state=token_state,
                params={
                    "container_id_type": "chat",
                    "container_id": chat_id,
                    "start_time": _to_unix(since),
                    "end_time": _to_unix(until),
                },
            )
    except httpx.TimeoutException:
        logger.error("飞书消息 API 超时，已重试 %s 次仍失败", API_TIMEOUT_RETRIES)
        return []
    except Exception as exc:
        logger.error("飞书消息采集失败: %s", exc)
        return []

    if payload is None:
        return []

    records: list[MessageRecord] = []
    for item in _extract_items(payload):
        record = _to_message_record(item, chat_name)
        if _should_keep(record.content, keywords):
            records.append(record)
    return records


def _should_keep(content: str, keywords: list[str]) -> bool:
    if any(word in content for word in SENSITIVE_KEYWORDS):
        return False
    return any(keyword in content for keyword in keywords)


def _fetch_chat_name(
    client: httpx.Client,
    app_id: str,
    app_secret: str,
    token_state: dict[str, str],
    chat_id: str,
) -> str | None:
    payload = _request_json(
        client,
        "GET",
        f"/open-apis/im/v1/chats/{chat_id}",
        app_id=app_id,
        app_secret=app_secret,
        token_state=token_state,
    )
    if not payload:
        return None
    data = payload.get("data") or {}
    name = data.get("name") or data.get("chat_name")
    return str(name) if name else None


def _fetch_tenant_token(client: httpx.Client, app_id: str, app_secret: str) -> str | None:
    payload = _post_json(
        client,
        TOKEN_PATH,
        json={"app_id": app_id, "app_secret": app_secret},
    )
    if payload is None:
        return None
    token = payload.get("tenant_access_token")
    if not token:
        logger.error("飞书 token 响应缺少 tenant_access_token")
        return None
    return str(token)


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    app_id: str,
    app_secret: str,
    token_state: dict[str, str],
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    token_refreshed: int = 0,
) -> Any | None:
    for attempt in range(1, API_TIMEOUT_RETRIES + 1):
        try:
            response = client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token_state['value']}"},
            )
        except httpx.TimeoutException:
            if attempt < API_TIMEOUT_RETRIES:
                time.sleep(API_TIMEOUT_INTERVAL_SECONDS)
                continue
            logger.error("飞书消息 API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
            return None

        data = _safe_json(response)
        if _is_token_expired(response, data) and token_refreshed < LARK_TOKEN_REFRESH_RETRIES:
            logger.info("飞书 token 过期，自动刷新后重试 1 次")
            new_token = _fetch_tenant_token(client, app_id, app_secret)
            if not new_token:
                return None
            token_state["value"] = new_token
            return _request_json(
                client,
                method,
                path,
                app_id=app_id,
                app_secret=app_secret,
                token_state=token_state,
                params=params,
                json=json,
                token_refreshed=token_refreshed + 1,
            )

        if data is None or data.get("code", 0) != 0:
            logger.error("飞书消息 API 请求失败: %s", path)
            return None
        return data
    return None


def _post_json(client: httpx.Client, path: str, json: dict[str, Any]) -> Any | None:
    for attempt in range(1, API_TIMEOUT_RETRIES + 1):
        try:
            response = client.post(path, json=json)
        except httpx.TimeoutException:
            if attempt < API_TIMEOUT_RETRIES:
                time.sleep(API_TIMEOUT_INTERVAL_SECONDS)
                continue
            logger.error("飞书消息 API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
            return None
        data = _safe_json(response)
        if data is None or data.get("code", 0) != 0:
            logger.error("飞书 token 获取失败: %s", path)
            return None
        return data
    return None


def _is_token_expired(response: httpx.Response, data: dict[str, Any] | None) -> bool:
    if response.status_code == 401:
        return True
    if not data:
        return False
    return int(data.get("code") or 0) in TOKEN_EXPIRED_CODES


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    items = data.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _to_message_record(item: dict[str, Any], chat_name: str) -> MessageRecord:
    sender = item.get("sender")
    if isinstance(sender, dict):
        sender_text = str(sender.get("id") or sender.get("name") or "")
    else:
        sender_text = str(sender or "")

    content = item.get("content")
    if not content:
        body = item.get("body") or {}
        content = body.get("content") or ""
    content_text = _normalize_content(str(content or ""))

    timestamp_raw = str(item.get("timestamp") or item.get("create_time") or "")
    name = str(item.get("chat_name") or chat_name)
    return MessageRecord(
        sender=sender_text,
        content=content_text,
        timestamp=_parse_timestamp(timestamp_raw),
        chat_name=name,
    )


def _normalize_content(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict) and parsed.get("text"):
            return str(parsed["text"])
    return content


def _to_unix(value: datetime) -> str:
    return str(int(value.timestamp()))


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min
    if value.isdigit():
        raw = int(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
