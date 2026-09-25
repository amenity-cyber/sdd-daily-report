"""日报生成模块：将采集数据整理为 DailyReport，输出 Markdown 和 HTML"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from shared.logger import get_logger
from shared.errors import GeneratorError
from generator.template import render_markdown, render_html

logger = get_logger(__name__)


# ===== 数据模型（design.md §3.2） =====

@dataclass
class CommitRecord:
    author: str
    message: str
    timestamp: datetime
    repo: str
    additions: int
    deletions: int
    files_changed: int


@dataclass
class TaskRecord:
    assignee: str
    title: str
    status_from: str
    status_to: str
    updated_at: datetime


@dataclass
class MessageRecord:
    sender: str
    content: str
    timestamp: datetime
    chat_name: str


@dataclass
class MemberReport:
    name: str
    github_username: str
    # None 表示该数据源采集失败；[] 表示无记录
    commits: Optional[list[CommitRecord]] = None
    tasks: Optional[list[TaskRecord]] = None
    messages: Optional[list[MessageRecord]] = None


@dataclass
class DailyReport:
    date: date
    team_name: str
    members: list[MemberReport]
    generated_at: datetime
    markdown: str = ""
    html: str = ""


# ===== 主逻辑（design.md §4.2） =====

def generate(members: list[MemberReport], date: date, team_name: str) -> DailyReport:
    """
    生成日报。

    Args:
        members: 各成员的采集数据（commits/tasks/messages 为 None 表示该源失败）
        date: 日报日期
        team_name: 团队名称

    Returns:
        DailyReport，含 markdown 和 html 两种格式

    Raises:
        GeneratorError: 生成失败时抛出
    """
    if members is None:
        raise GeneratorError("members 不能为 None")

    try:
        report = DailyReport(
            date=date,
            team_name=team_name,
            members=members,
            generated_at=datetime.now(),
        )
        report.markdown = render_markdown(report)
        report.html = render_html(report)
        return report
    except Exception as e:
        logger.error(f"日报生成失败: {e}")
        raise GeneratorError(f"日报生成失败: {e}") from e