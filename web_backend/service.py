"""Web 业务层：Mock 采集 → 现有生成器 → SQLite。"""
import re
from datetime import date, timedelta
from threading import Lock

from generator.formatter import generate
from notifier.email import send as send_email
from shared.storage import ReportStorage, StoredReport
from web_backend.mock_adapter import MockExternalAdapter


class ReportService:
    def __init__(self, storage: ReportStorage, adapter=None):
        self.storage = storage
        self.adapter = adapter if adapter is not None else MockExternalAdapter()
        self.mode = getattr(self.adapter, "mode", "mock")
        self.team_name = getattr(self.adapter, "team_name", "演示研发团队")
        self.source_label = getattr(self.adapter, "source_label", "Mock GitHub / 飞书")
        self._generate_lock = Lock()
        self._email_lock = Lock()

    def _serialize(self, report: StoredReport, detail: bool = False) -> dict:
        result = {
            "id": str(report.id),
            "name": f"{report.team_name}日报（{report.report_date.isoformat()}）",
            "status": "已完成", "owner": report.team_name,
            "createdAt": report.generated_at.isoformat(timespec="seconds"),
            "reportDate": report.report_date.isoformat(),
            "source": self.source_label,
            "mode": self.mode,
            "emailSent": self.storage.email_sent(report.id),
        }
        if detail:
            result.update(markdown=report.markdown, html=report.html)
        return result

    def _visible_reports(self) -> list[StoredReport]:
        reports = self.storage.list_reports()
        if self.mode == "real":
            return [report for report in reports if report.team_name == self.team_name]
        return reports

    def list_reports(self) -> list[dict]:
        return [self._serialize(report) for report in self._visible_reports()]

    @staticmethod
    def _activity_counts(markdown: str) -> dict[str, int]:
        """Count activity bullets in the generated report's two source sections."""
        headings = {
            "### 📝 一、代码提交": "commits",
            "### ✅ 二、任务进展": "tasks",
        }
        counts = {key: 0 for key in ("commits", "tasks")}
        summary_names = {
            "代码提交": "commits",
            "任务更新": "tasks",
        }
        summary_found = set()
        active = None
        for line in markdown.splitlines():
            summary = re.match(r"\|\s*(代码提交|任务更新)\s*\|\s*(\d+)", line)
            if summary:
                key = summary_names[summary.group(1)]
                counts[key] += int(summary.group(2))
                summary_found.add(key)
            heading = next((key for text, key in headings.items() if line.strip() == text), None)
            if heading:
                active = heading
            elif line.startswith("## ") or line.startswith("---"):
                active = None
            elif active and active not in summary_found and line.startswith("- "):
                counts[active] += 1
        return counts

    def analytics(self, today: date | None = None) -> dict:
        """Summarize saved reports for today's mix and the last seven calendar days."""
        if callable(getattr(self.adapter, "analytics", None)):
            return self.adapter.analytics(today)
        today = today or date.today()
        reports_by_date: dict[date, dict[str, int]] = {}
        for report in self._visible_reports():
            daily_counts = reports_by_date.setdefault(report.report_date, {
                "commits": 0, "tasks": 0,
            })
            for category, count in self._activity_counts(report.markdown).items():
                daily_counts[category] += count
        week = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            counts = reports_by_date.get(day, {"commits": 0, "tasks": 0})
            week.append({
                "date": day.isoformat(),
                "label": day.strftime("%m/%d"),
                "counts": counts,
                "total": sum(counts.values()),
            })
        return {"today": week[-1], "week": week}

    def get_report(self, report_id: str) -> dict | None:
        for report in self._visible_reports():
            if str(report.id) == report_id:
                return self._serialize(report, detail=True)
        return None

    def create_report(self) -> dict:
        with self._generate_lock:
            today = date.today()
            report = generate(self.adapter.collect(today), today, self.team_name)
            self.storage.save_report(
                today, self.team_name, report.markdown, report.html, report.generated_at,
            )
            # 查询持久化结果，避免 SQLite UPSERT 的 lastrowid 在重复生成时歧义。
            stored = self.storage.get_report(today, self.team_name)
            return self._serialize(stored, detail=True)

    def send_email(self, report_id: str) -> bool:
        if self.mode != "real":
            raise RuntimeError("模拟模式不允许发送真实邮件")
        with self._email_lock:
            stored = next((item for item in self._visible_reports() if str(item.id) == report_id), None)
            if stored is None:
                raise LookupError("日报不存在")
            if self.storage.email_sent(stored.id):
                raise FileExistsError("这份日报已发送过邮件")
            from types import SimpleNamespace

            report = SimpleNamespace(
                date=stored.report_date,
                team_name=stored.team_name,
                members=[],
                generated_at=stored.generated_at,
                markdown=stored.markdown,
                html=stored.html,
            )
            analytics = self.adapter.analytics(stored.report_date)
            sent = send_email(report, self.adapter.config.notify.email.recipients, analytics=analytics)
            if sent:
                self.storage.mark_email_sent(stored.id)
            return sent
