"""Live adapter transforms real collector output into date-bucketed charts."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from generator.formatter import CommitRecord, MemberReport, MessageRecord, TaskRecord
from web_backend.real_adapter import RealExternalAdapter


def test_analytics_includes_yesterday_and_today_in_seven_day_window():
    today = date.today()
    yesterday = today - timedelta(days=1)
    tz = datetime.now().astimezone().tzinfo
    member = MemberReport(
        name="闫宣妤", github_username="yan",
        commits=[CommitRecord("yan", "one", datetime.combine(yesterday, datetime.min.time(), tzinfo=tz), "repo", 1, 0, 1),
                 CommitRecord("yan", "two", datetime.combine(yesterday, datetime.min.time(), tzinfo=tz), "repo", 1, 0, 1)],
        tasks=[TaskRecord("yan", "task", "进行中", "已完成", datetime.combine(yesterday, datetime.min.time(), tzinfo=tz))],
        messages=[MessageRecord("闫宣妤", "discussion", datetime.combine(today, datetime.min.time(), tzinfo=tz), "chat")],
    )
    adapter = object.__new__(RealExternalAdapter)
    adapter.pipeline = SimpleNamespace(collect_all=lambda config, since, until: {"闫宣妤": member})
    adapter.config = object()

    analytics = adapter.analytics(today)

    assert len(analytics["week"]) == 7
    assert analytics["week"][-2]["date"] == yesterday.isoformat()
    assert analytics["week"][-2]["counts"] == {"commits": 2, "tasks": 1, "discussions": 0}
    assert analytics["today"]["counts"] == {"commits": 0, "tasks": 0, "discussions": 1}
