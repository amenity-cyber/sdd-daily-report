"""从飞书开放平台采集指定项目中的任务状态变更。"""

from __future__ import annotations

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
TASKS_PATH = "/open-apis/task/v2/tasks"
REQUEST_TIMEOUT_SECONDS = 30.0
TOKEN_EXPIRED_CODES = {99991661, 99991663, 99991664}

logger = get_logger("collector.lark_task")


@dataclass(frozen=True)
class TaskRecord:
    assignee: str
    title: str
    status_from: str
    status_to: str
    updated_at: datetime


def collect(project_id: str, since: datetime, until: datetime) -> list[TaskRecord]:
    """获取项目在 [since, until] 内发生状态变更的任务。失败时返回空列表并记录错误日志。"""
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
            payload = _request_json(
                client,
                "GET",
                TASKS_PATH,
                app_id=app_id,
                app_secret=app_secret,
                token=token,
                params={
                    "project_id": project_id,
                    "updated_min": _to_iso(since),
                    "updated_max": _to_iso(until),
                },
            )
    except httpx.TimeoutException:
        logger.error("飞书任务 API 超时，已重试 %s 次仍失败", API_TIMEOUT_RETRIES)
        return []
    except Exception as exc:
        logger.error("飞书任务采集失败: %s", exc)
        return []

    if payload is None:
        return []

    items = _extract_items(payload)
    return [_to_task_record(item) for item in items]


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
    token: str,
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
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException:
            if attempt < API_TIMEOUT_RETRIES:
                time.sleep(API_TIMEOUT_INTERVAL_SECONDS)
                continue
            logger.error("飞书任务 API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
            return None

        data = _safe_json(response)
        if _is_token_expired(response, data) and token_refreshed < LARK_TOKEN_REFRESH_RETRIES:
            logger.info("飞书 token 过期，自动刷新后重试 1 次")
            new_token = _fetch_tenant_token(client, app_id, app_secret)
            if not new_token:
                return None
            return _request_json(
                client,
                method,
                path,
                app_id=app_id,
                app_secret=app_secret,
                token=new_token,
                params=params,
                json=json,
                token_refreshed=token_refreshed + 1,
            )

        if data is None or data.get("code", 0) != 0:
            logger.error("飞书任务 API 请求失败: %s", path)
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
            logger.error("飞书任务 API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
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


def _to_task_record(item: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        assignee=str(item.get("assignee") or ""),
        title=str(item.get("title") or ""),
        status_from=str(item.get("status_from") or ""),
        status_to=str(item.get("status_to") or ""),
        updated_at=_parse_timestamp(str(item.get("updated_at") or "")),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat()


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
