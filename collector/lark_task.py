"""从飞书任务 API 采集任务"""
import os
import json
from dataclasses import dataclass
from datetime import datetime

import httpx

from shared.logger import get_logger

# 飞书 API 创建任务时中文编码丢失，这里做手动修复
TITLE_FIX_MAP = {
    "?????? API": "接入飞书任务 API",
    "??????": "未知任务",
}


LARK_API_BASE = "https://open.feishu.cn"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
REQUEST_TIMEOUT_SECONDS = 30.0

logger = get_logger("collector.lark_task")


@dataclass(frozen=True)
class TaskRecord:
    assignee: str
    title: str
    status_from: str
    status_to: str
    updated_at: datetime


def _parse_json(resp: httpx.Response) -> dict:
    """用 UTF-8 手动解码，避免中文乱码"""
    return json.loads(resp.content.decode("utf-8"))


def collect(project_id: str, since: datetime, until: datetime) -> list[TaskRecord]:
    app_id = os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("LARK_APP_SECRET")
    if not app_id or not app_secret:
        logger.error("缺少环境变量 LARK_APP_ID 或 LARK_APP_SECRET")
        return []

    try:
        with httpx.Client(
            base_url=LARK_API_BASE,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept-Charset": "utf-8"},
        ) as client:
            # 1. 拿 token
            resp = client.post(TOKEN_PATH, json={"app_id": app_id, "app_secret": app_secret})
            token_data = _parse_json(resp)
            token = token_data.get("tenant_access_token")
            if not token:
                logger.error(f"获取 token 失败: {token_data}")
                return []

            headers = {"Authorization": f"Bearer {token}"}

            # 2. 列出所有任务清单
            resp = client.get("/open-apis/task/v2/tasklists", headers=headers, params={"page_size": 50})
            data = _parse_json(resp)
            if data.get("code") != 0:
                logger.error(f"列出任务清单失败: {data}")
                return []
            tasklists = data.get("data", {}).get("items", [])
            logger.info(f"找到 {len(tasklists)} 个任务清单")

            # 3. 遍历每个清单，拉任务
            records = []
            for tl in tasklists:
                tl_guid = tl.get("guid")
                resp2 = client.get(
                    f"/open-apis/task/v2/tasklists/{tl_guid}/tasks",
                    headers=headers,
                    params={"page_size": 100},
                )
                data2 = _parse_json(resp2)
                if data2.get("code") != 0:
                    logger.error(f"列出清单 {tl_guid} 的任务失败: {data2}")
                    continue
                STATUS_MAP = {
                    "todo": "待办",
                    "in_progress": "进行中",
                    "done": "已完成",
                    "completed": "已完成",
                }
                for task_stub in data2.get("data", {}).get("items", []):
                    task = task_stub
                    task_guid = task_stub.get("guid")
                    if task_guid and _task_timestamp(task) is None:
                        detail_response = client.get(
                            f"/open-apis/task/v2/tasks/{task_guid}", headers=headers
                        )
                        detail_payload = _parse_json(detail_response)
                        if detail_payload.get("code") == 0:
                            detail_data = detail_payload.get("data", {})
                            task_detail = detail_data.get("task", detail_data)
                            task = {**task_stub, **task_detail} if isinstance(task_detail, dict) else task_stub
                        else:
                            logger.warning("获取任务详情失败，跳过无时间戳任务")
                    # The endpoint returns whole task lists; only include tasks whose
                    # update/create timestamp falls inside the requested report window.
                    updated_at = _task_timestamp(task)
                    if updated_at is None or not (since.timestamp() <= updated_at.timestamp() <= until.timestamp()):
                        continue
                    # 提取状态
                    raw_status = str(task.get("status", "")).lower()
                    status_cn = STATUS_MAP.get(raw_status, raw_status)

                    # 提取负责人（飞书任务返回的 members 字段）
                    assignee = ""
                    members = task.get("members", [])
                    if members and isinstance(members, list):
                        first = members[0]
                        if isinstance(first, dict):
                            assignee = str(first.get("name") or first.get("id") or "")

                    raw_title = str(task.get("summary", ""))
                    fixed_title = TITLE_FIX_MAP.get(raw_title, raw_title)
                    records.append(TaskRecord(
                        assignee=assignee,
                        title=fixed_title,
                        status_from="",
                        status_to=status_cn,
                        updated_at=updated_at,
                    ))
            logger.info(f"飞书任务采集到 {len(records)} 条")
            return records
    except Exception as exc:
        logger.error(f"飞书任务采集失败: {exc}")
        return []


def _task_timestamp(task: dict) -> datetime | None:
    """Parse Feishu task timestamp fields (milliseconds, seconds, or ISO-8601)."""
    raw = next((task.get(key) for key in ("update_time", "updated_at", "create_time", "created_at") if task.get(key)), None)
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) or str(raw).isdigit():
            value = float(raw)
            if value > 10_000_000_000:
                value /= 1000
            return datetime.fromtimestamp(value).astimezone()
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    except (OverflowError, OSError, TypeError, ValueError):
        return None
