"""从 GitHub API 采集指定时间范围内的 commit 记录。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from shared.errors import API_TIMEOUT_INTERVAL_SECONDS, API_TIMEOUT_RETRIES
from shared.logger import get_logger

GITHUB_API_BASE = "https://api.github.com"
PER_PAGE = 30
REQUEST_TIMEOUT_SECONDS = 30.0
RATE_LIMIT_RETRIES = 3

logger = get_logger("collector.github")


@dataclass(frozen=True)
class CommitRecord:
    author: str
    message: str
    timestamp: datetime
    repo: str
    additions: int
    deletions: int
    files_changed: int


def collect(repos: list[str], since: datetime, until: datetime) -> list[CommitRecord]:
    """获取各仓库在 [since, until] 内的 commit，失败时返回空列表并记录错误日志。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    records: list[CommitRecord] = []
    try:
        with httpx.Client(
            base_url=GITHUB_API_BASE,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            for repo in repos:
                repo_records = _collect_repo(client, repo, since, until)
                if repo_records is None:
                    return []
                records.extend(repo_records)
    except httpx.TimeoutException:
        logger.error("GitHub API 超时，已重试 %s 次仍失败", API_TIMEOUT_RETRIES)
        return []
    except Exception as exc:
        logger.error("GitHub 采集失败: %s", exc)
        return []
    return records


def _collect_repo(
    client: httpx.Client,
    repo: str,
    since: datetime,
    until: datetime,
) -> list[CommitRecord] | None:
    if "/" not in repo:
        logger.error("仓库名称格式不正确，应为 owner/repo: %s", repo)
        return []

    commits: list[CommitRecord] = []
    page = 1
    while True:
        payload = _get_json(
            client,
            f"/repos/{repo}/commits",
            params={
                "since": _to_iso(since),
                "until": _to_iso(until),
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        if payload is None:
            return None
        if not isinstance(payload, list):
            logger.error("GitHub 提交列表响应格式不正确: %s", repo)
            return None

        for item in payload:
            sha = item.get("sha")
            if not sha:
                continue
            detail = _get_json(client, f"/repos/{repo}/commits/{sha}")
            if detail is None:
                return None
            commits.append(_to_commit_record(item, detail if isinstance(detail, dict) else {}, repo))

        if len(payload) < PER_PAGE:
            break
        page += 1
    return commits


def _get_json(
    client: httpx.Client,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any | None:
    last_timeout: httpx.TimeoutException | None = None
    rate_limit_attempts = 0

    for attempt in range(1, API_TIMEOUT_RETRIES + 1):
        try:
            response = client.get(path, params=params)
        except httpx.TimeoutException as exc:
            last_timeout = exc
            if attempt < API_TIMEOUT_RETRIES:
                time.sleep(API_TIMEOUT_INTERVAL_SECONDS)
                continue
            logger.error("GitHub API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
            return None

        if response.status_code == 403:
            reset_header = response.headers.get("X-RateLimit-Reset")
            if reset_header and rate_limit_attempts < RATE_LIMIT_RETRIES:
                rate_limit_attempts += 1
                wait_seconds = _rate_limit_wait_seconds(reset_header)
                logger.info("GitHub API 限流，等待 %s 秒后重试: %s", wait_seconds, path)
                time.sleep(wait_seconds)
                continue
            logger.error("GitHub API 返回 403: %s", path)
            return None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("GitHub API 请求失败 (%s): %s", exc.response.status_code, path)
            return None
        return response.json()

    if last_timeout is not None:
        logger.error("GitHub API 超时，已重试 %s 次仍失败: %s", API_TIMEOUT_RETRIES, path)
    return None


def _rate_limit_wait_seconds(reset_header: str) -> float:
    try:
        reset_at = int(reset_header)
    except ValueError:
        return API_TIMEOUT_INTERVAL_SECONDS
    return max(0.0, reset_at - time.time())


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat()


def _to_commit_record(summary: dict[str, Any], detail: dict[str, Any], repo: str) -> CommitRecord:
    commit = summary.get("commit") or {}
    author_login = ""
    if isinstance(summary.get("author"), dict):
        author_login = str(summary["author"].get("login") or "")
    if not author_login and isinstance(commit.get("author"), dict):
        author_login = str(commit["author"].get("name") or "")

    timestamp_raw = ""
    if isinstance(commit.get("author"), dict):
        timestamp_raw = str(commit["author"].get("date") or "")
    timestamp = _parse_timestamp(timestamp_raw)

    stats = detail.get("stats") or {}
    files = detail.get("files") or []
    return CommitRecord(
        author=author_login,
        message=str(commit.get("message") or ""),
        timestamp=timestamp,
        repo=repo,
        additions=int(stats.get("additions") or 0),
        deletions=int(stats.get("deletions") or 0),
        files_changed=len(files) if isinstance(files, list) else int(stats.get("total") or 0),
    )


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
