"""Markdown / HTML 模板管理（jinja2）"""
from jinja2 import Template

MARKDOWN_TEMPLATE = """# {{ team_name }} 工作日报

> **日期**：{{ date }} 　|　 **生成时间**：{{ generated_at }}

---

{% for m in members %}
## 👤 {{ m.name }}

### 📊 今日概览

| 指标 | 数值 |
|------|------|
| 代码提交 | {% if m.commits %}{{ m.commits|length }} 次{% else %}—{% endif %} |
| 任务更新 | {% if m.tasks %}{{ m.tasks|length }} 项{% else %}—{% endif %} |
| 协作讨论 | {% if m.messages %}{{ m.messages|length }} 条{% else %}—{% endif %} |

> **📌 今日总结**：{% if m.commits and m.commits|length > 0 %}共完成 {{ m.commits|length }} 次代码提交{% else %}今日无代码提交{% endif %}，{% if m.tasks and m.tasks|length > 0 %}{{ m.tasks|length }} 项任务有更新{% else %}无任务变更{% endif %}，{% if m.messages and m.messages|length > 0 %}{{ m.messages|length }} 条协作讨论{% else %}无协作记录{% endif %}，整体进展{% if m.commits and m.commits|length > 5 %}活跃{% elif m.commits and m.commits|length > 0 %}顺利{% else %}平稳{% endif %}。

### 📝 一、代码提交

{% if m.commits and m.commits|length > 0 %}
今日在 **{{ m.commits[0].repo }}** 仓库共提交 **{{ m.commits|length }}** 次，累计 **+{{ m.commits|sum(attribute='additions') }}** / **-{{ m.commits|sum(attribute='deletions') }}** 行。

**主要变更**：
{% set message_counts = {} %}
{% for c in m.commits %}
{% if c.message not in message_counts %}
{% set _ = message_counts.update({c.message: 1}) %}
{% else %}
{% set _ = message_counts.update({c.message: message_counts[c.message] + 1}) %}
{% endif %}
{% endfor %}
{% for msg, count in message_counts.items() %}
- {{ msg }}{% if count > 1 %}（{{ count }} 次）{% endif %}
{% endfor %}
{% elif m.commits is none %}
> ⚠️ GitHub 数据获取失败
{% else %}
> 今日无代码提交记录
{% endif %}

### ✅ 二、任务进展

{% if m.tasks and m.tasks|length > 0 %}
今日共 **{{ m.tasks|length }}** 项任务有更新：

{% for t in m.tasks %}
- {{ t.title }}{% if t.status_to %}（{{ t.status_to }}）{% endif %}{% if t.assignee %} — 负责人：{{ t.assignee }}{% endif %}
{% endfor %}
{% elif m.tasks is none %}
> ⚠️ 飞书任务数据获取失败
{% else %}
> 今日无任务变更记录
{% endif %}

### 💬 三、协作沟通

{% if m.messages and m.messages|length > 0 %}
今日群内共 **{{ m.messages|length }}** 条相关讨论：

{% for msg in m.messages %}
- {{ msg.content }}
{% endfor %}
{% elif m.messages is none %}
> ⚠️ 飞书消息数据获取失败
{% else %}
> 今日无协作沟通记录
{% endif %}

---

{% endfor %}

📌 **日报说明**
本日报由 **SDD 智能日报生成器** 自动生成，数据来源：GitHub API（不可用时使用匹配仓库的本地 Git 历史）+ 飞书开放平台 API。

*—— 系统自动发送，请勿直接回复 ——*
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{{ team_name }} 工作日报（{{ date }}）</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", Arial, sans-serif; max-width: 720px; margin: 32px auto; padding: 0 24px; color: #24292f; line-height: 1.75; background: #ffffff; font-size: 15px; }
h1 { color: #0969da; border-bottom: 2px solid #0969da; padding-bottom: 14px; font-size: 26px; font-weight: 600; margin-bottom: 8px; }
h2 { color: #24292f; margin-top: 40px; padding: 10px 16px; background: linear-gradient(90deg, #f0f6ff 0%, #ffffff 100%); border-left: 4px solid #0969da; border-radius: 3px; font-size: 20px; font-weight: 600; }
h3 { color: #57606a; margin-top: 24px; font-size: 16px; font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid #d0d7de; }
.meta { color: #57606a; font-size: 13px; background: #f6f8fa; padding: 12px 16px; border-radius: 6px; border-left: 3px solid #0969da; margin-bottom: 24px; }
.stat-cards { display: flex; gap: 12px; margin: 16px 0; }
.stat-card { flex: 1; text-align: center; padding: 20px 12px; background: linear-gradient(135deg, #f0f6ff 0%, #ffffff 100%); border-radius: 8px; border: 1px solid #d0d7de; }
.stat-num { font-size: 32px; font-weight: 700; color: #0969da; line-height: 1.2; }
.stat-label { font-size: 13px; color: #57606a; margin-top: 4px; }
.summary-box { background: #ddf4ff; border-left: 4px solid #0969da; padding: 12px 16px; border-radius: 4px; margin: 16px 0; color: #24292f; font-size: 14px; }
.summary-box strong { color: #0969da; }
.summary { background: #ddf4ff; border-left: 3px solid #0969da; padding: 8px 14px; border-radius: 3px; color: #0969da; font-size: 14px; margin: 12px 0; }
ul { margin: 10px 0; padding-left: 22px; }
li { margin: 8px 0; color: #24292f; }
.empty { color: #8b949e; font-style: italic; padding: 10px 16px; background: #f6f8fa; border-left: 3px solid #d0d7de; border-radius: 3px; margin: 8px 0; }
.error { color: #cf222e; padding: 10px 16px; background: #ffebe9; border-left: 3px solid #cf222e; border-radius: 3px; margin: 8px 0; }
.footer { margin-top: 48px; padding: 20px 0; border-top: 1px solid #d0d7de; color: #57606a; font-size: 13px; line-height: 1.6; }
.footer-title { color: #24292f; font-weight: 600; margin-bottom: 6px; }
.footer small { color: #8b949e; display: block; margin-top: 12px; font-style: italic; }
</style>
</head>
<body>
<h1>{{ team_name }} 工作日报</h1>
<p class="meta"><strong>日期：</strong>{{ date }}　|　<strong>生成时间：</strong>{{ generated_at }}</p>

{% for m in members %}
<h2>👤 {{ m.name }}</h2>

<h3>📊 今日概览</h3>
<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-num">{% if m.commits %}{{ m.commits|length }}{% else %}0{% endif %}</div>
        <div class="stat-label">代码提交</div>
    </div>
    <div class="stat-card">
        <div class="stat-num">{% if m.tasks %}{{ m.tasks|length }}{% else %}0{% endif %}</div>
        <div class="stat-label">任务更新</div>
    </div>
    <div class="stat-card">
        <div class="stat-num">{% if m.messages %}{{ m.messages|length }}{% else %}0{% endif %}</div>
        <div class="stat-label">协作讨论</div>
    </div>
</div>

<div class="summary-box">
    <strong>📌 今日总结：</strong>{% if m.commits and m.commits|length > 0 %}共完成 {{ m.commits|length }} 次代码提交{% else %}今日无代码提交{% endif %}，{% if m.tasks and m.tasks|length > 0 %}{{ m.tasks|length }} 项任务有更新{% else %}无任务变更{% endif %}，{% if m.messages and m.messages|length > 0 %}{{ m.messages|length }} 条协作讨论{% else %}无协作记录{% endif %}，整体进展{% if m.commits and m.commits|length > 5 %}活跃{% elif m.commits and m.commits|length > 0 %}顺利{% else %}平稳{% endif %}。
</div>

<h3>📝 一、代码提交</h3>
{% if m.commits and m.commits|length > 0 %}
<p class="summary">今日在 {{ m.commits[0].repo }} 仓库共提交 {{ m.commits|length }} 次，累计 +{{ m.commits|sum(attribute='additions') }} / -{{ m.commits|sum(attribute='deletions') }} 行。</p>
<p><strong>主要变更：</strong></p>
<ul>
{% set message_counts = {} %}
{% for c in m.commits %}
{% if c.message not in message_counts %}
{% set _ = message_counts.update({c.message: 1}) %}
{% else %}
{% set _ = message_counts.update({c.message: message_counts[c.message] + 1}) %}
{% endif %}
{% endfor %}
{% for msg, count in message_counts.items() %}
<li>{{ msg }}{% if count > 1 %}（{{ count }} 次）{% endif %}</li>
{% endfor %}
</ul>
{% elif m.commits is none %}
<p class="error">⚠️ GitHub 数据获取失败</p>
{% else %}
<p class="empty">今日无代码提交记录</p>
{% endif %}

<h3>✅ 二、任务进展</h3>
{% if m.tasks and m.tasks|length > 0 %}
<p class="summary">今日共 {{ m.tasks|length }} 项任务有更新。</p>
<ul>
{% for t in m.tasks %}
<li>{{ t.title }}{% if t.status_to %}（{{ t.status_to }}）{% endif %}{% if t.assignee %} — 负责人：{{ t.assignee }}{% endif %}</li>
{% endfor %}
</ul>
{% elif m.tasks is none %}
<p class="error">⚠️ 飞书任务数据获取失败</p>
{% else %}
<p class="empty">今日无任务变更记录</p>
{% endif %}

<h3>💬 三、协作沟通</h3>
{% if m.messages and m.messages|length > 0 %}
<p class="summary">今日群内共 {{ m.messages|length }} 条相关讨论。</p>
<ul>
{% for msg in m.messages %}
<li>{{ msg.content }}</li>
{% endfor %}
</ul>
{% elif m.messages is none %}
<p class="error">⚠️ 飞书消息数据获取失败</p>
{% else %}
<p class="empty">今日无协作沟通记录</p>
{% endif %}

{% endfor %}

<div class="footer">
    <div class="footer-title">📌 日报说明</div>
    本日报由 <strong>SDD 智能日报生成器</strong> 自动生成，数据来源：GitHub API（不可用时使用匹配仓库的本地 Git 历史）+ 飞书开放平台 API。
    <small>—— 系统自动发送，请勿直接回复 ——</small>
</div>
</body>
</html>
"""


def render_markdown(report) -> str:
    tmpl = Template(MARKDOWN_TEMPLATE)
    return tmpl.render(
        team_name=report.team_name,
        date=report.date,
        generated_at=report.generated_at,
        members=report.members,
    )


def render_html(report) -> str:
    tmpl = Template(HTML_TEMPLATE)
    return tmpl.render(
        team_name=report.team_name,
        date=report.date,
        generated_at=report.generated_at,
        members=report.members,
    )
