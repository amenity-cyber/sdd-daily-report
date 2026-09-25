"""读取并校验 config.yaml，提供全局配置访问。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared.errors import ConfigError

_REQUIRED_TOP_LEVEL = ("team_name", "members", "github", "lark", "notify")
_REQUIRED_MEMBER_FIELDS = ("name", "github", "lark")


@dataclass(frozen=True)
class MemberConfig:
    name: str
    github: str
    lark: str


@dataclass(frozen=True)
class GitHubConfig:
    repos: list[str]


@dataclass(frozen=True)
class LarkConfig:
    project_id: str
    chat_id: str
    keywords: list[str]


@dataclass(frozen=True)
class EmailNotifyConfig:
    recipients: list[str]


@dataclass(frozen=True)
class LarkBotNotifyConfig:
    chat_id: str


@dataclass(frozen=True)
class NotifyConfig:
    email: EmailNotifyConfig
    lark_bot: LarkBotNotifyConfig


@dataclass(frozen=True)
class AppConfig:
    team_name: str
    members: list[MemberConfig]
    github: GitHubConfig
    lark: LarkConfig
    notify: NotifyConfig
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


_config: AppConfig | None = None


def _require(data: Any, key: str, path: str) -> Any:
    if not isinstance(data, dict) or key not in data or data[key] in (None, "", []):
        raise ConfigError(f"配置缺少必填字段: {path}")
    return data[key]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件解析失败: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件格式不正确，应为 YAML 映射: {path}")
    return data


def _parse_members(raw_members: Any) -> list[MemberConfig]:
    if not isinstance(raw_members, list) or not raw_members:
        raise ConfigError("配置缺少必填字段: members")
    members: list[MemberConfig] = []
    for index, item in enumerate(raw_members):
        if not isinstance(item, dict):
            raise ConfigError(f"配置字段 members[{index}] 格式不正确")
        fields: dict[str, str] = {}
        for field_name in _REQUIRED_MEMBER_FIELDS:
            value = item.get(field_name)
            if not value:
                raise ConfigError(f"配置缺少必填字段: members[{index}].{field_name}")
            fields[field_name] = str(value)
        members.append(MemberConfig(**fields))
    return members


def _parse_github(raw: Any) -> GitHubConfig:
    repos = _require(raw, "repos", "github.repos")
    if not isinstance(repos, list) or not repos:
        raise ConfigError("配置缺少必填字段: github.repos")
    return GitHubConfig(repos=[str(repo) for repo in repos])


def _parse_lark(raw: Any) -> LarkConfig:
    project_id = str(_require(raw, "project_id", "lark.project_id"))
    chat_id = str(_require(raw, "chat_id", "lark.chat_id"))
    keywords = _require(raw, "keywords", "lark.keywords")
    if not isinstance(keywords, list) or not keywords:
        raise ConfigError("配置缺少必填字段: lark.keywords")
    return LarkConfig(
        project_id=project_id,
        chat_id=chat_id,
        keywords=[str(item) for item in keywords],
    )


def _parse_notify(raw: Any) -> NotifyConfig:
    email_raw = _require(raw, "email", "notify.email")
    recipients = _require(email_raw, "recipients", "notify.email.recipients")
    if not isinstance(recipients, list) or not recipients:
        raise ConfigError("配置缺少必填字段: notify.email.recipients")
    lark_bot_raw = _require(raw, "lark_bot", "notify.lark_bot")
    bot_chat_id = str(_require(lark_bot_raw, "chat_id", "notify.lark_bot.chat_id"))
    return NotifyConfig(
        email=EmailNotifyConfig(recipients=[str(item) for item in recipients]),
        lark_bot=LarkBotNotifyConfig(chat_id=bot_chat_id),
    )


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """读取 YAML 配置，校验必填字段，并缓存为全局配置。"""
    global _config
    config_path = Path(path)
    data = _load_yaml(config_path)

    for key in _REQUIRED_TOP_LEVEL:
        _require(data, key, key)

    config = AppConfig(
        team_name=str(data["team_name"]),
        members=_parse_members(data["members"]),
        github=_parse_github(data["github"]),
        lark=_parse_lark(data["lark"]),
        notify=_parse_notify(data["notify"]),
        raw=data,
    )
    _config = config
    return config


def get_config() -> AppConfig:
    """返回已加载的全局配置；尚未加载时尝试读取默认 config.yaml。"""
    if _config is None:
        return load_config()
    return _config


def reset_config() -> None:
    """清除全局配置缓存（主要用于测试）。"""
    global _config
    _config = None
