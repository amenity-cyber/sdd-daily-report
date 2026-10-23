"""Live adapter transforms real collector output into date-bucketed charts."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from generator.formatter import CommitRecord, MemberReport, TaskRecord
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
    )
    adapter = object.__new__(RealExternalAdapter)
    adapter.pipeline = SimpleNamespace(collect_all=lambda config, since, until: {"闫宣妤": member})
    adapter.config = object()

    analytics = adapter.analytics(today)

    assert len(analytics["week"]) == 7
    assert analytics["week"][-2]["date"] == yesterday.isoformat()
    assert analytics["week"][-2]["counts"] == {"commits": 2, "tasks": 1}
    assert analytics["today"]["counts"] == {"commits": 0, "tasks": 0}


def test_collect_does_not_treat_chat_messages_as_a_required_data_source():
    adapter = object.__new__(RealExternalAdapter)
    adapter.pipeline = SimpleNamespace(
        collect_all=lambda config, since, until: {
            "闫宣妤": MemberReport("闫宣妤", "yan", commits=[], tasks=[])
        },
    )
    adapter.config = SimpleNamespace()
    assert adapter.collect(date.today())[0].name == "闫宣妤"
