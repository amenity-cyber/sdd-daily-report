"""Markdown / HTML 模板管理（jinja2）"""
from jinja2 import Template

MARKDOWN_TEMPLATE = """# {{ team_name }} 日报（{{ date }}）

生成时间：{{ generated_at }}

{% for m in members %}
## {{ m.name }}

### 代码提交
{% if m.commits and m.commits|length > 0 %}
{% for c in m.commits %}
- [{{ c.repo }}] {{ c.message }} (+{{ c.additions }}/-{{ c.deletions }}, {{ c.files_changed }} files)
{% endfor %}
{% elif m.commits is none %}
- 数据获取失败
{% else %}
- 今日无记录
{% endif %}

### 任务进展
{% if m.tasks and m.tasks|length > 0 %}
{% for t in m.tasks %}
- {{ t.title }}：{{ t.status_from }} → {{ t.status_to }}
{% endfor %}
{% elif m.tasks is none %}
- 数据获取失败
{% else %}
- 今日无记录
{% endif %}

### 协作沟通
{% if m.messages and m.messages|length > 0 %}
{% for msg in m.messages %}
- [{{ msg.chat_name }}] {{ msg.sender }}：{{ msg.content }}
{% endfor %}
{% elif m.messages is none %}
- 数据获取失败
{% else %}
- 今日无记录
{% endif %}

{% endfor %}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{{ team_name }} 日报（{{ date }}）</title>
<style>
body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; max-width: 800px; margin: 20px auto; color: #333; }
h1 { border-bottom: 2px solid #0366d6; padding-bottom: 8px; }
h2 { color: #0366d6; margin-top: 24px; }
h3 { color: #555; margin-bottom: 6px; }
ul { margin-top: 4px; }
.meta { color: #888; font-size: 13px; }
</style>
</head>
<body>
<h1>{{ team_name }} 日报</h1>
<p class="meta">日期：{{ date }} ｜ 生成时间：{{ generated_at }}</p>

{% for m in members %}
<h2>{{ m.name }}</h2>

<h3>代码提交</h3>
{% if m.commits and m.commits|length > 0 %}
<ul>
{% for c in m.commits %}
<li>[{{ c.repo }}] {{ c.message }} (+{{ c.additions }}/-{{ c.deletions }}, {{ c.files_changed }} files)</li>
{% endfor %}
</ul>
{% elif m.commits is none %}
<p>数据获取失败</p>
{% else %}
<p>今日无记录</p>
{% endif %}

<h3>任务进展</h3>
{% if m.tasks and m.tasks|length > 0 %}
<ul>
{% for t in m.tasks %}
<li>{{ t.title }}：{{ t.status_from }} → {{ t.status_to }}</li>
{% endfor %}
</ul>
{% elif m.tasks is none %}
<p>数据获取失败</p>
{% else %}
<p>今日无记录</p>
{% endif %}

<h3>协作沟通</h3>
{% if m.messages and m.messages|length > 0 %}
<ul>
{% for msg in m.messages %}
<li>[{{ msg.chat_name }}] {{ msg.sender }}：{{ msg.content }}</li>
{% endfor %}
</ul>
{% elif m.messages is none %}
<p>数据获取失败</p>
{% else %}
<p>今日无记录</p>
{% endif %}

{% endfor %}
</body>
</html>
"""


def render_markdown(report) -> str:
    """将 DailyReport 渲染为 Markdown 字符串"""
    tmpl = Template(MARKDOWN_TEMPLATE)
    return tmpl.render(
        team_name=report.team_name,
        date=report.date,
        generated_at=report.generated_at,
        members=report.members,
    )


def render_html(report) -> str:
    """将 DailyReport 渲染为 HTML 字符串"""
    tmpl = Template(HTML_TEMPLATE)
    return tmpl.render(
        team_name=report.team_name,
        date=report.date,
        generated_at=report.generated_at,
        members=report.members,
    )