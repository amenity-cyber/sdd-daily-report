"""使用业务模型提供离线样例，不连接外部 API。"""
from datetime import date, datetime, time

from generator.formatter import CommitRecord, MemberReport, MessageRecord, TaskRecord


class MockExternalAdapter:
    def collect(self, report_date: date) -> list[MemberReport]:
        timestamp = datetime.combine(report_date, time(10, 0))
        return [MemberReport(
            name="演示成员", github_username="demo-developer",
            commits=[CommitRecord(
                author="demo-developer", message="feat: 完成日报前后端联调",
                timestamp=timestamp, repo="demo/daily-report",
                additions=42, deletions=8, files_changed=3,
            )],
            tasks=[TaskRecord(
                assignee="demo-developer", title="验证日报生成、复制与导出",
                status_from="进行中", status_to="已完成", updated_at=timestamp,
            )],
            messages=[MessageRecord(
                sender="演示成员", content="本地 Mock 联调完成，等待验收。",
                timestamp=timestamp, chat_name="演示研发群",
            )],
        )]
