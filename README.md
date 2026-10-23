# 智能日报生成器

本项目复现《SDD 实战》的智能日报生成器，保留采集、生成、推送和共享基础模块。OpenDesign 前端通过本地 HTTP API 接入现有 GitHub 提交、飞书任务采集器、日报生成器和 SQLite；日报不采集飞书群聊消息。默认读取本机 `config.yaml` 与 `.env` 使用真实数据。

## 启动本地联调

在本目录打开终端。如果已有 `.venv`，Windows PowerShell 可直接运行：

```powershell
.\.venv\Scripts\python.exe web_server.py
```

浏览器访问 http://127.0.0.1:8765 。初次启动列表为空，点击“生成新日报”得到完整正文；同一天再次生成更新当日日报。页面支持搜索、筛选、详情、复制及下载 Markdown。刷新页面或重启服务保留历史。

真实模式要求本机已有有效的 `config.yaml`、`.env` 和网络权限。启动时会显示数据模式及采集源状态；图表直接按 GitHub/飞书记录时间归入今天和近七个自然日。打开日报详情后可手动发送邮件；同一份日报成功发送后会在本地数据库记为已发送，防止重复点击。邮件仅使用配置的收件人。

外部 API 默认直连以避开系统里失效的代理设置；若网络必须经过代理，可在 `.env` 中设置 `APP_HTTP_PROXY`（例如 `http://127.0.0.1:7890`）。

新环境需 Python 3.11+。可执行 `uv sync`，或先创建虚拟环境并安装 `pyproject.toml` 列出的依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install httpx pyyaml jinja2 pytest
.\.venv\Scripts\python.exe web_server.py --port 8765 --db data/web_reports.db
```

服务仅监听本机。数据库默认位于项目 `data/web_reports.db`，已忽略版本跟踪。用 Ctrl+C 停止服务。直接双击 HTML 会显示本地服务启动引导；须从服务地址访问才能联调。

需要离线演示时加 `--mock`：

```powershell
.\.venv\Scripts\python.exe web_server.py --mock --port 8765
```

Mock 模式不连接外部服务，也拒绝真实邮件发送。原 `main.py` 命令行业务入口保留。

## 接口

- `GET /api/health`：服务状态、真实/Mock 模式和配置源状态（不返回凭据）。
- `GET /api/analytics`：今日代码提交、飞书任务分布及近七个自然日工作强度；实时采集失败时返回数据源状态。
- `GET /api/reports`：历史日报元数据列表。
- `POST /api/reports`：空请求体或 `{}`，生成并保存当日日报。
- `GET /api/reports/<id>`：完整 Markdown/HTML 正文。
- `POST /api/reports/<id>/email`：真实模式下发送邮件；Mock 模式拒绝发送；已成功发送的日报不可重复发送。

响应分别使用 `reports`、`report` 字段；错误使用 `error` 字段。页面正文按文本展示，支持复制和下载原 Markdown。

## 验证

页面统计图由实时模式下的采集器数据直接按活动时间统计，包含未生成日报的日期，因此昨天的活动不会因缺少历史日报而消失。采集源失败会显示提示，避免把失败误认成真实的零活动；Mock 模式只用于自动化验收。

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

GitHub Actions 工作流位于 `.github/workflows/ci.yml`：推送到 `main` 和向 `main` 提 PR 只运行 Python 与 Playwright CI 测试，不接触第三方凭据。每天 UTC 10:00（北京时间 18:00）在测试通过后生成并邮件发送日报；也可以在 GitHub Actions 页面从 `main` 手动运行。同一自然日的定时与手动运行共用发送标记，避免重复邮件。定时邮件任务要求在 GitHub Secrets 配置 `APP_CONFIG_YAML`（完整 YAML 内容）、`LARK_APP_ID`、`LARK_APP_SECRET`、`SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`，以及可选 `SMTP_PORT`、`SMTP_FROM`；GitHub API 使用工作流只读权限的内置 token。该工作流负责 CI 和定时邮件；网站部署需按下一节单独启用 Render CD。

### Render 网站 CD

仓库根目录的 `render.yaml` 定义了 Render Python Web 服务：绑定平台 `$PORT`、使用持久磁盘保存 SQLite、通过 `/healthz` 健康检查，并配置为 `main` 分支的 GitHub 检查通过后自动部署。生产站点要求 HTTP Basic Auth；`/healthz` 仅供平台检查，其余页面和 API 都需要登录。

首次启用需要在 Render 中创建 Blueprint 并连接本 GitHub 仓库，填入 Blueprint 提示的环境变量：`APP_CONFIG_YAML`（完整 `config.yaml` 内容）、`GITHUB_TOKEN`（只读仓库权限）、`LARK_APP_ID`、`LARK_APP_SECRET`、`SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`，以及网站登录用的 `WEB_AUTH_USER`、`WEB_AUTH_PASSWORD`。所有凭据都只填在 Render 环境变量面板，不提交到 Git。当前 Blueprint 使用 Starter Web Service 和 1 GB 持久磁盘；Render 持久磁盘要求付费实例。完成首次授权、填写密钥并创建服务后，Render 才会提供公网 HTTPS 地址；此后 `main` 上的变更在 GitHub CI 检查通过后自动部署。定时邮件仍由 GitHub Actions 管理，不由 Render Web 服务执行。

## SDD / Superpowers 过程材料

- `specs/proposal.md`、`specs/design.md`、`specs/tasks.md`：项目规范与本轮变更。
- `docs/superpowers/specs/2026-10-09-web-integration-design.md`：经用户批准的设计。
- `docs/superpowers/plans/2026-10-09-web-integration.md`：经用户批准的实施计划。
- `docs/superpowers/verification/progress.md`：测试先失败再通过的记录、执行裁定。
- `docs/superpowers/verification/2026-10-09-web-integration.md`：最终验证结果。

Superpowers 插件查询时尚未安装；本轮按照读取的官方技能文档执行需求设计、计划、TDD、调试、独立审查和完成前验证。材料不会把文档流程描述成已安装或调用插件。
