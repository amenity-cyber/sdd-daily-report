"""主编排入口：按顺序编排 采集 → 聚合 → 生成 → 推送"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

from shared.config import load_config, ConfigError
from shared.logger import get_logger
from shared.errors import CollectorError, GeneratorError, NotifierError
from shared.env import load_local_env

from collector import github, lark_task, lark_msg
from generator.formatter import CommitRecord, MemberReport, generate
from notifier import email as email_notifier
from notifier import lark_bot
from dataclasses import replace
def _load_local_env(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries without requiring a third-party dotenv package."""
    load_local_env(path)


_load_local_env()

logger = get_logger(__name__)
last_collection_status = {}


def _local_git_commits(repos: list[str], since: datetime, until: datetime, members) -> list[CommitRecord] | None:
    """Use the matching local checkout as a transparent fallback when GitHub is unreachable."""
    root = Path.cwd()
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root,
        capture_output=True, text=True, check=False,
    )
    if remote.returncode != 0:
        return None
    remote_name = remote.stdout.strip().removesuffix(".git").rstrip("/").split("://")[-1]
    repo_name = remote_name.removeprefix("github.com/").lower()
    configured = {repo.strip().removesuffix(".git").lower() for repo in repos}
    if repo_name not in configured:
        return None

    history = subprocess.run(
        ["git", "log", f"--since={since.isoformat()}", f"--until={until.isoformat()}",
         "--format=%H%x1f%aI%x1f%an%x1f%s"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if history.returncode != 0:
        return None
    members_by_name = {member.name.casefold(): member for member in members}
    members_by_login = {member.github.casefold(): member for member in members}
    commits = []
    for row in history.stdout.splitlines():
        fields = row.split("\x1f", 3)
        if len(fields) != 4:
            continue
        sha, timestamp_text, author_name, message = fields
        member = members_by_name.get(author_name.casefold()) or members_by_login.get(author_name.casefold())
        if member is None and len(members) == 1:
            member = members[0]
        if member is None:
            continue
        stats = subprocess.run(
            ["git", "show", "--format=", "--numstat", sha],
            cwd=root, capture_output=True, text=True, check=False,
        )
        additions = deletions = files_changed = 0
        for line in stats.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            try:
                additions += int(parts[0])
                deletions += int(parts[1])
            except ValueError:  # binary files use '-' for line counts
                pass
            files_changed += 1
        commits.append(CommitRecord(
            author=member.github, message=message,
            timestamp=datetime.fromisoformat(timestamp_text),
            repo=repo_name, additions=additions, deletions=deletions,
            files_changed=files_changed,
        ))
    return commits


def parse_args():
    parser = argparse.ArgumentParser(description="智能日报生成器")
    parser.add_argument("--check", action="store_true", help="健康检查：验证 API 连接和配置")
    parser.add_argument("--dry-run", action="store_true", help="执行采集和生成但不推送")
    parser.add_argument("--email-only", action="store_true", help="只发送邮件，不重复推送到飞书")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    return parser.parse_args()


def run_check(config) -> bool:
    """健康检查：验证配置完整性，不调用外部 API"""
    logger.info("开始健康检查...")
    try:
        assert config.team_name, "team_name 未配置"
        assert config.members, "members 未配置"
        assert config.github.repos, "github.repos 未配置"
        logger.info(f"配置检查通过：团队={config.team_name}, 成员数={len(config.members)}")
        logger.info("健康检查完成")
        return True
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return False


def collect_all(config, since: datetime, until: datetime) -> dict:
    """
    并行（本实现为串行 + 异常隔离）采集所有数据源。
    单个数据源失败不影响其他数据源。
    返回: {member_name: MemberReport}
    """
    global last_collection_status
    status = {"github": False, "local_git": False, "feishu_tasks": False, "feishu_discussions": False}
    # 初始化每个成员的空报告
    reports = {}
    for m in config.members:
        reports[m.name] = MemberReport(
            name=m.name,
            github_username=m.github,
            commits=None,   # None = 失败
            tasks=None,
            messages=None,
        )

    # 1. GitHub 采集
    try:
        commits = github.collect(config.github.repos, since, until)
        if getattr(github, "last_collection_failed", False):
            fallback = _local_git_commits(config.github.repos, since, until, config.members)
            if fallback is not None:
                logger.warning("GitHub API 不可用，使用匹配仓库的本地 Git 历史补充提交数据")
                commits = fallback
                status["local_git"] = True
        else:
            status["github"] = True
        logger.info(f"GitHub 采集到 {len(commits)} 条 commit")
        for m in config.members:
            reports[m.name].commits = [c for c in commits if c.author == m.github]
    except Exception as e:
        logger.error(f"GitHub 采集失败: {e}")

    # 2. 飞书任务采集
    try:
        tasks = lark_task.collect(config.lark.project_id, since, until)
        status["feishu_tasks"] = not getattr(lark_task, "last_collection_failed", False)
        logger.info(f"飞书任务采集到 {len(tasks)} 条")
        if config.members:
            reports[config.members[0].name].tasks = tasks
    except Exception as e:
        status["feishu_tasks"] = False
        logger.error(f"飞书任务采集失败: {e}")

    # 3. 飞书消息采集
    try:
        messages = lark_msg.collect(config.lark.chat_id, config.lark.keywords, since, until)
        status["feishu_discussions"] = not getattr(lark_msg, "last_collection_failed", False)
        logger.info(f"飞书消息采集到 {len(messages)} 条")
        for m in config.members:
            seen_contents = set()
            filtered = []
            for msg in messages:
                if msg.sender != m.lark:
                    continue
                key = msg.content[:20]
                if key in seen_contents:
                    continue
                seen_contents.add(key)

                # 提取关键词前缀（用 config.lark.keywords 里配的词）
                prefix = ""
                for kw in config.lark.keywords:
                    if kw in msg.content:
                        prefix = f"[{kw}] "
                        break

                # 用新内容替换（带前缀）
                from dataclasses import replace
                msg = replace(msg, content=prefix + msg.content)
                filtered.append(msg)
            reports[m.name].messages = filtered
    except Exception as e:
        status["feishu_discussions"] = False
        logger.error(f"飞书消息采集失败: {e}")

    last_collection_status = status
    # 检查是否所有数据源都失败
    all_failed = all(
        r.commits is None and r.tasks is None and r.messages is None
        for r in reports.values()
    )
    if all_failed:
        raise CollectorError("所有数据源采集失败，不生成空日报")

    return reports


def collect_activity_analytics(config, reports: dict, since: datetime, until: datetime) -> dict:
    """Collect seven-day activity for charts; daily figures reuse the report data."""
    daily = {
        "commits": sum(len(member.commits or []) for member in reports.values()),
        "tasks": sum(len(member.tasks or []) for member in reports.values()),
        "messages": sum(len(member.messages or []) for member in reports.values()),
    }
    # 最近七个自然日，包含今天；since 是今天 00:00，因此向前回退六天。
    week_start = since - timedelta(days=6)
    first_day = since.date() - timedelta(days=6)
    rows = {
        (first_day + timedelta(days=offset)).isoformat(): {
            "date": (first_day + timedelta(days=offset)).isoformat(),
            "commits": 0,
            "tasks": 0,
            "messages": 0,
        }
        for offset in range(7)
    }
    try:
        commits = github.collect(config.github.repos, week_start, until)
        if getattr(github, "last_collection_failed", False):
            fallback = _local_git_commits(config.github.repos, week_start, until, config.members)
            if fallback is not None:
                commits = fallback
        for item in commits:
            day = item.timestamp.astimezone(until.tzinfo).date().isoformat()
            if day in rows and any(item.author == member.github for member in config.members):
                rows[day]["commits"] += 1
    except Exception as exc:
        logger.error(f"周趋势 GitHub 采集失败: {exc}")
    try:
        tasks = lark_task.collect(config.lark.project_id, week_start, until)
        for item in tasks:
            day = item.updated_at.astimezone(until.tzinfo).date().isoformat()
            if day in rows:
                rows[day]["tasks"] += 1
    except Exception as exc:
        logger.error(f"周趋势飞书任务采集失败: {exc}")
    try:
        messages = lark_msg.collect(config.lark.chat_id, config.lark.keywords, week_start, until)
        for item in messages:
            day = item.timestamp.astimezone(until.tzinfo).date().isoformat()
            if day in rows:
                rows[day]["messages"] += 1
    except Exception as exc:
        logger.error(f"周趋势飞书消息采集失败: {exc}")
    return {"today": daily, "week": list(rows.values())}


def main():
    args = parse_args()
    start_time = datetime.now()
    logger.info(f"=== 日报生成开始：{start_time} ===")

    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error(f"配置加载失败: {e}")
        sys.exit(1)

    # --check 模式
    if args.check:
        ok = run_check(config)
        sys.exit(0 if ok else 1)

    # 确定采集时间窗口（Asia/Shanghai 本地当天 00:00 至现在）
    until = datetime.now().astimezone()
    today = until.date()
    since = until.replace(hour=0, minute=0, second=0, microsecond=0)


    # 采集
    try:
        reports = collect_all(config, since, until)
    except CollectorError as e:
        logger.error(f"采集阶段失败: {e}")
        sys.exit(1)

    # 生成
    try:
        report = generate(list(reports.values()), today, config.team_name)
        logger.info(f"日报生成成功，共 {len(report.members)} 位成员")
    except GeneratorError as e:
        logger.error(f"日报生成失败: {e}")
        sys.exit(1)

    # --dry-run 模式
    if args.dry_run:
        logger.info("--dry-run 模式：跳过推送")
        logger.info(f"=== 日报生成结束：{datetime.now()} ===")
        sys.exit(0)

    # 推送
    analytics = collect_activity_analytics(config, reports, since, until)
    email_ok = email_notifier.send(report, config.notify.email.recipients, analytics=analytics)
    lark_ok = False if args.email_only else lark_bot.send(report, config.notify.lark_bot.chat_id)
    logger.info(f"推送结果：邮件={email_ok}, 飞书={lark_ok}")
    if args.email_only and not email_ok:
        logger.error("--email-only 模式下邮件发送失败")
        sys.exit(1)

    end_time = datetime.now()
    logger.info(f"=== 日报生成结束：{end_time}，耗时 {end_time - start_time} ===")


if __name__ == "__main__":
    main()
