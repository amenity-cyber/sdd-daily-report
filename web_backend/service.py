"""Web 业务层：Mock 采集 → 现有生成器 → SQLite。"""
from datetime import date
from threading import Lock

from generator.formatter import generate
from shared.storage import ReportStorage, StoredReport
from web_backend.mock_adapter import MockExternalAdapter


class ReportService:
    def __init__(self, storage: ReportStorage, adapter=None):
        self.storage = storage
        self.adapter = adapter if adapter is not None else MockExternalAdapter()
        self.team_name = "演示研发团队"
        self._generate_lock = Lock()

    @staticmethod
    def _serialize(report: StoredReport, detail: bool = False) -> dict:
        result = {
            "id": str(report.id),
            "name": f"{report.team_name}日报（{report.report_date.isoformat()}）",
            "status": "已完成", "owner": report.team_name,
            "createdAt": report.generated_at.isoformat(timespec="seconds"),
            "reportDate": report.report_date.isoformat(),
            "source": "Mock GitHub / 飞书",
        }
        if detail:
            result.update(markdown=report.markdown, html=report.html)
        return result

    def list_reports(self) -> list[dict]:
        return [self._serialize(report) for report in self.storage.list_reports()]

    def get_report(self, report_id: str) -> dict | None:
        for report in self.storage.list_reports():
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
