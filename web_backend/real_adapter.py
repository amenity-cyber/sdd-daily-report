"""Adapter that connects the web application to the configured live sources."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from shared.config import load_config
from shared.env import load_local_env


class RealExternalAdapter:
    mode = "real"
    source_label = "GitHub API / 飞书 API"

    def __init__(self, config_path: str | Path, env_path: str | Path):
        load_local_env(env_path)
        self.config = load_config(config_path)
        self.team_name = self.config.team_name
        # Import after loading the project .env so the CLI and web server share
        # the same collectors and local Git fallback.
        import main as daily_pipeline

        self.pipeline = daily_pipeline

    @property
    def sources(self) -> dict[str, bool]:
        return {
            "github": bool(self.config.github.repos),
            "feishu": bool(os.environ.get("LARK_APP_ID") and os.environ.get("LARK_APP_SECRET")),
            "email": bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD")),
        }

    @staticmethod
    def _window(report_date: date, now: datetime) -> tuple[datetime, datetime]:
        start = datetime.combine(report_date, time.min, tzinfo=now.tzinfo)
        if report_date == now.date():
            return start, now
        return start, start + timedelta(days=1) - timedelta(microseconds=1)

    def collect(self, report_date: date):
        now = datetime.now().astimezone()
        since, until = self._window(report_date, now)
        reports = self.pipeline.collect_all(self.config, since, until)
        if not any(
            getattr(member, field, None) is not None
            for member in reports.values()
            for field in ("commits", "tasks", "messages")
        ):
            raise RuntimeError("GitHub 和飞书数据源均未返回可用结果，请检查配置、网络和服务权限")
        return list(reports.values())

    def _collection_status(self, reports: dict) -> dict[str, bool]:
        status = getattr(self.pipeline, "last_collection_status", None)
        if status:
            return status.copy()
        members = list(reports.values())
        return {
            "github": bool(members) and all(member.commits is not None for member in members),
            "local_git": False,
            "feishu_tasks": bool(members) and members[0].tasks is not None,
            "feishu_discussions": bool(members) and all(member.messages is not None for member in members),
        }

    def analytics(self, today: date | None = None) -> dict:
        now = datetime.now().astimezone()
        today = today or now.date()
        until = now if today == now.date() else self._window(today, now)[1]
        first_day = today - timedelta(days=6)
        week_start, _ = self._window(first_day, now)
        reports = self.pipeline.collect_all(self.config, week_start, until)
        source_status = self._collection_status(reports)
        rows = {
            (first_day + timedelta(days=offset)).isoformat(): {
                "date": (first_day + timedelta(days=offset)).isoformat(),
                "label": (first_day + timedelta(days=offset)).strftime("%m/%d"),
                "counts": {"commits": 0, "tasks": 0, "discussions": 0},
                "total": 0,
            }
            for offset in range(7)
        }
        for member in reports.values():
            for attribute, category in (("commits", "commits"), ("tasks", "tasks"), ("messages", "discussions")):
                for activity in getattr(member, attribute) or []:
                    timestamp = activity.timestamp if attribute != "tasks" else activity.updated_at
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=now.tzinfo)
                    day = timestamp.astimezone(now.tzinfo).date().isoformat()
                    if day in rows:
                        rows[day]["counts"][category] += 1
        week = list(rows.values())
        for row in week:
            row["total"] = sum(row["counts"].values())
        today_row = next((row for row in week if row["date"] == today.isoformat()), None)
        return {"sources": source_status, "today": today_row or {
            "date": today.isoformat(), "label": today.strftime("%m/%d"),
            "counts": {"commits": 0, "tasks": 0, "discussions": 0}, "total": 0,
        }, "week": week}
