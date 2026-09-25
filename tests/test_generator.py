"""Task 6 验收测试：日报生成模块"""
from datetime import date, datetime

import pytest

from generator.formatter import (
    CommitRecord,
    TaskRecord,
    MessageRecord,
    MemberReport,
    DailyReport,
    generate,
)


# ===== 测试数据 =====

def make_commit():
    return CommitRecord(
        author="zhangsan",
        message="feat: add login",
        timestamp=datetime(2026, 9, 24, 10, 0, 0),
        repo="mythy",
        additions=50,
        deletions=10,
        files_changed=3,
    )


def make_task():
    return TaskRecord(
        assignee="zhangsan@company.com",
        title="实现登录功能",
        status_from="进行中",
        status_to="已完成",
        updated_at=datetime(2026, 9, 24, 17, 0, 0),
    )


def make_message():
    return MessageRecord(
        sender="zhangsan@company.com",
        content="登录接口已经联调通过",
        timestamp=datetime(2026, 9, 24, 15, 0, 0),
        chat_name="研发群",
    )


# ===== 验收标准 1：函数签名符合 §4.2 =====

def test_generate_signature():
    """generate() 参数和返回类型符合 design.md §4.2"""
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=[], tasks=[], messages=[])]
    report = generate(members=members, date=date(2026, 9, 24), team_name="研发团队")
    assert isinstance(report, DailyReport)
    assert report.team_name == "研发团队"
    assert report.date == date(2026, 9, 24)


# ===== 验收标准 2：markdown 含三个部分标题 =====

def test_markdown_contains_three_sections():
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=[make_commit()], tasks=[make_task()], messages=[make_message()])]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "代码提交" in report.markdown
    assert "任务进展" in report.markdown
    assert "协作沟通" in report.markdown
    assert "feat: add login" in report.markdown
    assert "实现登录功能" in report.markdown


# ===== 验收标准 3：html 可渲染 =====

def test_html_renderable():
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=[make_commit()], tasks=[], messages=[])]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "<html" in report.html
    assert "</html>" in report.html
    assert "代码提交" in report.html


# ===== 验收标准 4：无记录显示"今日无记录" =====

def test_empty_member_shows_no_record():
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=[], tasks=[], messages=[])]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "今日无记录" in report.markdown
    assert "今日无记录" in report.html


# ===== 验收标准 5：数据源失败显示"数据获取失败" =====

def test_failed_source_shows_error_label():
    # commits=None 表示 GitHub 采集失败
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=None, tasks=[], messages=[])]
    report = generate(members, date(2026, 9, 24), "研发团队")

    assert "数据获取失败" in report.markdown
    assert "数据获取失败" in report.html


# ===== 验收标准 6：Markdown → HTML 转换格式正确 =====

def test_markdown_to_html_conversion():
    members = [MemberReport(name="张三", github_username="zhangsan",
                            commits=[make_commit()], tasks=[make_task()], messages=[make_message()])]
    report = generate(members, date(2026, 9, 24), "研发团队")

    # markdown 是文本，html 是结构化标签
    assert isinstance(report.markdown, str)
    assert isinstance(report.html, str)
    assert report.markdown != report.html
    assert "<h2>" in report.html or "<h3>" in report.html


# ===== 异常场景：members 为 None =====

def test_generate_raises_on_none_members():
    from shared.errors import GeneratorError
    with pytest.raises(GeneratorError):
        generate(None, date(2026, 9, 24), "研发团队")