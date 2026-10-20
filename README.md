# 智能日报生成器

本项目复现《SDD 实战》的智能日报生成器，保留采集、生成、推送和共享基础模块。本轮将 OpenDesign 前端接入本地 HTTP 服务，使用模拟工作记录调用原有生成器，并保存到 SQLite。

## 启动本地联调

在本目录打开终端。如果已有 `.venv`，Windows PowerShell 可直接运行：

```powershell
.\.venv\Scripts\python.exe web_server.py
```

浏览器访问 http://127.0.0.1:8765 。初次启动列表为空，点击“生成新日报”得到完整正文；同一天再次生成更新当日日报。页面支持搜索、筛选、详情、复制及下载 Markdown。刷新页面或重启服务保留历史。

新环境需 Python 3.11+。可执行 `uv sync`，或先创建虚拟环境并安装 `pyproject.toml` 列出的依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install httpx pyyaml jinja2 pytest
.\.venv\Scripts\python.exe web_server.py --port 8765 --db data/web_reports.db
```

服务仅监听本机。数据库默认位于项目 `data/web_reports.db`，已忽略版本跟踪。用 Ctrl+C 停止服务。直接双击 HTML 会显示本地服务启动引导；须从服务地址访问才能联调。

本轮使用 Mock GitHub/飞书数据，不需要凭据，不发送真实邮件或飞书通知。原 `main.py` 命令行业务入口保留。

## 接口

- `GET /api/health`：服务运行状态、Mock 模式。
- `GET /api/analytics`：今日提交、任务、讨论分布及近七个自然日工作强度。
- `GET /api/reports`：历史日报元数据列表。
- `POST /api/reports`：空请求体或 `{}`，生成并保存当日日报。
- `GET /api/reports/<id>`：完整 Markdown/HTML 正文。

响应分别使用 `reports`、`report` 字段；错误使用 `error` 字段。页面正文按文本展示，支持复制和下载原 Markdown。

## 验证

页面统计图从已保存日报的代码提交、任务进展和协作沟通章节汇总，不伪造额外数据。无日报日期显示为 0。

Python 回归与接口测试：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q
```

浏览器测试使用 Node.js 和 Playwright，默认读取本项目 `.venv` 的 Python。首次可安装测试依赖（不属于产品运行依赖）：

```powershell
npm install --no-save --package-lock=false playwright
$env:WEB_TEST_BROWSER='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
node tests/web_e2e.cjs
```

如果没有 Edge，可运行 `npx playwright install chromium` 并不设置 `WEB_TEST_BROWSER`。若 Edge 安装位置不同，请修改该变量。`WEB_TEST_PYTHON` 可指定其他 Python；`PLAYWRIGHT_MODULE` 可指定已安装 Playwright 的绝对目录。Linux/macOS 使用对应 Python 和浏览器路径即可。

脚本创建独立临时数据库、随机端口和无窗口浏览器，检查生成、持久化、复制、下载、错误恢复、筛选、正文安全展示、桌面/窄屏布局、服务重启和直接文件打开。结束后关闭测试服务与浏览器。结果、截图和导出文件位于 `test-results/web-*`，不会修改演示数据库。

GitHub Actions 工作流位于 `.github/workflows/ci.yml`：推送到 `main`、向 `main` 提交 PR 或手动触发时，会在 Python 3.11/3.12 运行测试，并在 Python 3.11 环境运行 Playwright 浏览器验收；浏览器测试证据会作为 Actions artifact 保存。CI 使用模拟数据，不读取本地 `config.yaml`，不连接飞书，也不发送邮件。当前工作流负责持续集成和验收，实际部署需先确定托管平台。

## SDD / Superpowers 过程材料

- `specs/proposal.md`、`specs/design.md`、`specs/tasks.md`：项目规范与本轮变更。
- `docs/superpowers/specs/2026-10-09-web-integration-design.md`：经用户批准的设计。
- `docs/superpowers/plans/2026-10-09-web-integration.md`：经用户批准的实施计划。
- `docs/superpowers/verification/progress.md`：测试先失败再通过的记录、执行裁定。
- `docs/superpowers/verification/2026-10-09-web-integration.md`：最终验证结果。

Superpowers 插件查询时尚未安装；本轮按照读取的官方技能文档执行需求设计、计划、TDD、调试、独立审查和完成前验证。材料不会把文档流程描述成已安装或调用插件。
