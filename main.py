"""主编排入口：按顺序编排 采集 → 聚合 → 生成 → 推送"""
import argparse
import sys
from datetime import datetime, timedelta, date

from shared.config import load_config, ConfigError
from shared.logger import get_logger
from shared.errors import CollectorError, GeneratorError, NotifierError

from collector import github, lark_task, lark_msg
from generator.formatter import MemberReport, generate
from notifier import email as email_notifier
from notifier import lark_bot

logger = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="智能日报生成器")
    parser.add_argument("--check", action="store_true", help="健康检查：验证 API 连接和配置")
    parser.add_argument("--dry-run", action="store_true", help="执行采集和生成但不推送")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    return parser.parse_args()


def run_check(config) -> bool:
    """健康检查：验证配置完整性，不调用外部 API"""
    logger.info("开始健康检查...")
    try:
        assert config.team_name, "team_name 未配置"
        assert config.members, "members 未配置"
        assert config.github_repos, "github.repos 未配置"
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
        commits = github.collect(config.github_repos, since, until)
        logger.info(f"GitHub 采集到 {len(commits)} 条 commit")
        for m in config.members:
            reports[m.name].commits = [c for c in commits if c.author == m.github]
    except Exception as e:
        logger.error(f"GitHub 采集失败: {e}")

    # 2. 飞书任务采集
    try:
        tasks = lark_task.collect(config.lark_project_id, since, until)
        logger.info(f"飞书任务采集到 {len(tasks)} 条")
        for m in config.members:
            reports[m.name].tasks = [t for t in tasks if t.assignee == m.lark]
    except Exception as e:
        logger.error(f"飞书任务采集失败: {e}")

    # 3. 飞书消息采集
    try:
        messages = lark_msg.collect(config.lark_chat_id, config.lark_keywords, since, until)
        logger.info(f"飞书消息采集到 {len(messages)} 条")
        for m in config.members:
            reports[m.name].messages = [msg for msg in messages if msg.sender == m.lark]
    except Exception as e:
        logger.error(f"飞书消息采集失败: {e}")

    # 检查是否所有数据源都失败
    all_failed = all(
        r.commits is None and r.tasks is None and r.messages is None
        for r in reports.values()
    )
    if all_failed:
        raise CollectorError("所有数据源采集失败，不生成空日报")

    return reports


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

    # 确定采集时间窗口（当天 00:00 至现在）
    today = date.today()
    since = datetime.combine(today, datetime.min.time())
    until = datetime.now()

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
    email_ok = email_notifier.send(report, config.recipients)
    lark_ok = lark_bot.send(report, config.lark_chat_id)
    logger.info(f"推送结果：邮件={email_ok}, 飞书={lark_ok}")

    end_time = datetime.now()
    logger.info(f"=== 日报生成结束：{end_time}，耗时 {end_time - start_time} ===")


if __name__ == "__main__":
    main()