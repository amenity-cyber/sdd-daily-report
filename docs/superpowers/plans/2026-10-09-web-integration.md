# 智能日报生成器前后端联调 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让 OpenDesign 前端通过本地 API 生成、保存、查看、复制并导出日报。
**Architecture:** Python 标准库 HTTP 服务同源提供前端与 API。MockExternalAdapter 返回现有业务模型，ReportService 复用现有生成器和 SQLite 存储；页面读取 API，不再内嵌样例数组。
**Tech Stack:** Python 3.11+、sqlite3、http.server、现有 Jinja2、原生 HTML/CSS/JS、pytest、Playwright（仅验证）。
**Spec:** docs/superpowers/specs/2026-10-09-web-integration-design.md（用户已批准）。

## Global Constraints

- 不增加产品依赖；保留已有 48 个测试不变。
- 保留 web_ui/ 入口和 OpenDesign 页面布局；统一已有规范中的目录约定。
- Mock 数据不调用外部平台，不读取凭据；不伪造真实推送或性能数字。
- 复用现有 SQLite 按日期和团队唯一的规则；重复生成更新当日记录。
- 默认数据库 data/web_reports.db，默认仅监听 127.0.0.1。
- 先观察新增测试失败，再实现并运行通过；不自动发布或向老师发送消息。

## Review Focus

1. 同日重复生成和重启：记录 ID、日期及正文一致，列表不产生伪造历史。
2. 生成失败、详情失败、服务离线：不能提示成功，已有列表保持可用，按钮恢复可重试。
3. 陈旧筛选值、中文正文、含 HTML 字符的正文：筛选可恢复，正文完整，不执行脚本。
4. 文件直接打开和窄屏：有明确服务启动引导；页面无整体横向溢出。
5. 静态路径穿越、非法 JSON 与 HTTP 方法：清晰的 4xx 错误，不返回配置或内部堆栈。

## Task 1: Mock 生成服务与历史持久化

**Files:** Create web_backend/__init__.py、web_backend/mock_adapter.py、web_backend/service.py、tests/test_web_service.py；Modify .gitignore。
**Interfaces:** 消费 generate(members, date, team_name) 和 ReportStorage；输出 MockExternalAdapter.collect(report_date: date) -> list[MemberReport]；ReportService(storage, adapter=None)，list_reports() -> list[dict]，create_report() -> dict，get_report(report_id: str) -> dict | None。

- [x] 写服务测试：空库返回 []；生成正文含“代码提交”“任务进展”“协作沟通”；详情匹配；重新创建服务保留内容；重复生成同日只保留一条且 ID 不变；未知 ID 返回 None；适配器异常不新增记录。
- [x] 运行 `python -m pytest tests/test_web_service.py -q`，确认新模块缺失导致失败（RED）。
- [x] 实现 Mock 数据及服务，列表只返回展示元数据，详情和生成返回完整正文；忽略 data/。
- [x] 运行同一测试命令，全部通过（GREEN）；检查与设计一致。
- [x] 留存任务结果和 Git 提交（如 Git 写入需要授权，先完成可审阅文件与验证）。

## Task 2: 本地 HTTP 接口与静态入口

**Files:** Create web_server.py、tests/test_web_http.py。
**Interfaces:** 消费 Task 1 的 ReportService；输出 create_server(host: str, port: int, service: ReportService) -> ThreadingHTTPServer 和 CLI `python web_server.py --port 8765 --db data/web_reports.db`。

- [x] 写 HTTP 测试，启动临时端口与临时数据库：GET /、/api/health、/api/reports；POST /api/reports→GET 列表→GET /api/reports/<id>；未知 ID；非法 JSON；不支持的方法；静态路径越界；生成异常返回不泄露堆栈的 JSON 500。
- [x] 运行 `python -m pytest tests/test_web_http.py -q`，确认 web_server 缺失导致失败（RED）。
- [x] 实现白名单静态服务与 JSON 路由、请求大小限制、错误处理和 CLI。允许无请求体或空 JSON 对象的生成请求；默认只监听本机。
- [x] 运行 HTTP 与服务测试，全部通过（GREEN）。
- [x] 留存任务结果和 Git 提交。

## Task 3: 前端联调、复制、导出及浏览器验证

**Files:** Modify web_ui/index.html；Create web_ui/style.css、web_ui/app.js、tests/web_e2e.cjs。
**Interfaces:** 消费 /api/reports、/api/reports/<id>；保留 DOM ID createBtn、taskBody、searchInput、modalBody、modalCopy、modalExport；移除静态 TASKS 数组。

- [x] 编写 Playwright 脚本：空库开始；点击生成后出现完整正文；列表刷新保留；复制后读取剪贴板；下载与 API 正文一致；模拟 500 后无假记录且按钮恢复；详情失败明确提示；离线列表错误；非法筛选恢复；HTML 正文按文本显示；390px 和 1366px 无页面溢出；页面无未捕获异常。
- [x] 用已安装 Edge、隔离的临时测试数据库运行脚本，观察旧前端对应交互失败（RED）。测试通过环境变量使用 Playwright 库路径和浏览器路径，README 给出可复用运行命令。
- [x] 拆分样式/脚本；实现同源 fetch、真实生成/详情、错误状态、实际复制与 Blob 下载、焦点恢复与异步详情防覆盖、file:// 引导、窄屏修正。
- [x] 运行同一浏览器脚本，全部通过（GREEN）。
- [x] 留存任务结果和 Git 提交。

## Task 4: 全量验证与交付记录

**Files:** Modify specs/proposal.md、specs/design.md、specs/tasks.md；Create README.md、docs/superpowers/verification/2026-10-09-web-integration.md。
**Interfaces:** 消费前三个任务的实现与测试证据，输出可复现启动说明和验收记录。

- [x] 同步规范里的 web/ 为 web_ui/、HTTP 契约、Mock 范围、已实际验证的前端任务；原项目未验证的外部 API 验收不标成已通过。
- [x] 运行 `python -m pytest -q`，原 48 个及新增测试全部通过；运行浏览器验证与服务重启验证。
- [x] 用新的独立 reviewer 审查本轮完整变更、设计与计划，重点检查 Review Focus；重要问题先写复现失败测试，再修复并跑全量验证。
- [x] 写验证记录：命令、环境、RED/GREEN、结果、插件实际状态、人工设计/计划审批、已知限制。附本地启动和第三轮提交所需文件。
- [x] 留存最终 Git 提交或明确尚未提交的状态；不发布、不推送、不联系老师。

## 执行交接

用户已批准本计划并选择当前 main 原地 Native 执行，实施及验证已完成：
- 推荐 Native：当前会话逐项实现，完成后独立 reviewer 检查全量变更。任务接口连续，直接执行更易保持一致。
- Subagent-driven：每个任务由独立实现者和审查者完成，过程审查更密集。

如用户明确选择“当前项目 main 原地执行”，视为对现有分支执行的授权；否则按 Superpowers 的 worktree 流程隔离实现。Git 提交遇到文件权限限制时使用实际授权流程，不修改系统配置绕过权限。

## 计划自审

设计中的持久化、API、UI 错误恢复、复制/导出、路径限制、响应式和原测试回归均有对应任务。跨任务接口名称一致；Task 1 为 Task 2 提供服务；Task 2 为 Task 3 提供同源接口；Task 4 验证全部交付。没有需要用户补充的业务参数。
