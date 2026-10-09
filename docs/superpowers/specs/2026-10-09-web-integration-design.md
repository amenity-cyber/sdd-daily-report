# 智能日报生成器：前后端联调设计

日期：2026-10-09（Asia/Shanghai）
状态：用户已批准；实现、回归验证及独立审查修复已完成。

## 目标与依据

用户要求补齐现有前端缺口，并使用 Superpowers 完成前后端联调和功能验证。
已有 specs/proposal.md、specs/design.md、specs/tasks.md 要求本地 HTTP 接口和 MockExternalAdapter。
本轮成功标准：浏览器从后端加载日报；点击生成得到真实生成器输出的正文；刷新和重启保留日报；复制得到正文；导出得到 Markdown 文件；接口失败时明确提示并可重试。

现状：web_ui/index.html 内嵌模拟数组；createTask 只创建未开始的记录；复制和导出只显示 Toast。Python 已有 generator.formatter.generate 和 shared.storage.ReportStorage，适合复用。

## 方案选择

选择 Python 标准库本地 HTTP 服务：新增 web_server.py 和 web_backend/，同源提供页面和 JSON API，无需增加产品依赖。
FastAPI 能提供自动接口文档，但本轮仅三个业务接口，增加框架依赖没有必要。
仅在前端实现模拟生成无法满足已有本地接口约定，也无法证明前后端联调，故不采用。

保留 OpenDesign 的 web_ui/ 目录和页面布局，将样式、脚本分别移入 style.css、app.js。后续同步已有规范里的 web/ 路径为 web_ui/，避免两个前端入口。

## 组件与数据流

- web_backend/mock_adapter.py：MockExternalAdapter 返回现有 MemberReport、CommitRecord、TaskRecord、MessageRecord 模型；不调用外部平台，不读取凭据。
- web_backend/service.py：ReportService 接受 adapter 和 ReportStorage，调用现有 generate，保存 Markdown/HTML，再返回前端所需数据。
- web_server.py：启动绑定 127.0.0.1 的本地服务；仅公开前端静态资源和约定 API。
- web_ui/app.js：请求列表、请求生成、请求详情；保留筛选、搜索、统计卡片与弹窗；执行实际复制和下载。

数据流：浏览器 → 同源 HTTP API → MockExternalAdapter → 现有 generator → 现有 SQLite 存储 → JSON → 页面。
沿用 SQLite 按日期和团队唯一的规则：同一天再次生成更新当日记录，不伪造不同历史任务；不同日期的记录可作为历史。
默认数据库使用项目 data/web_reports.db，加入 .gitignore；测试使用独立临时数据库。

## HTTP 契约

- GET /api/reports：200，返回 {"reports": [...]}；空库返回空数组。
- POST /api/reports：空请求体或空 JSON 对象，200，返回 {"report": {...}}；同步执行 Mock 采集、生成和持久化。
- GET /api/reports/<id>：200，返回 {"report": {...}}；未知记录返回 404 JSON 错误。
- GET /：返回 web_ui/index.html；/style.css、/app.js 只提供对应静态文件。
- GET /api/health：返回运行状态与 mode="mock"，便于启动及自动化验证。

记录字段：id（字符串）、name（团队与日期）、status（已完成）、owner（团队）、createdAt（生成时间）、reportDate（日期）、source（Mock GitHub / 飞书）、markdown（正文，仅详情/生成响应）、html（生成器输出，仅详情/生成响应）。
列表包含展示和筛选所需元数据；详情和生成包含完整正文。
不向前端承诺未实现的真实推送或流水线性能数字；页面明确显示模拟数据和本地保存完成。

错误响应统一为 {"error": "可读错误说明"}。非法路径、ID 返回 404；不支持的 API 方法返回 405；非法 POST 请求体返回 400；采集/生成/保存异常返回 500，记录服务器日志，不向用户返回堆栈或本地路径。
默认只监听本机。静态资源使用显式白名单，防止意外读取数据库、配置或目录外文件。

## 前端行为

1. 页面启动请求列表，显示加载状态。空库显示“暂无日报，点击生成新日报开始”。
2. 点击生成时按钮禁用，显示进行中；成功后刷新列表并打开生成结果；失败保留原列表，恢复按钮，提示错误，可再次点击。
3. 点击详情请求后端完整正文，避免以页面静态样例冒充数据。
4. 正文通过 textContent 渲染 Markdown，保留换行；不将未转义的正文插入 innerHTML。
5. 复制调用 Clipboard API；不支持时尝试兼容复制；只有实际成功才提示成功，失败明确提示。
6. 导出用 UTF-8 Blob 下载 .md，内容与后端返回的 Markdown 一致。
7. 筛选和搜索使用真实列表；缓存的非法筛选值回退到“全部”；持久化仅保存筛选偏好，日报来自数据库。
8. 弹窗支持 Esc、关闭按钮、遮罩关闭，并恢复焦点；避免过期详情请求覆盖新选择。
9. file:// 直接打开时提示从本地服务地址访问，不默默回退静态模拟数据。
10. 保留桌面布局，修正窄屏横向溢出，并验证 390px 与 1366px 视口。

## 验证与完成条件

遵循 Superpowers 的测试驱动开发流程：先新增测试并观察目标行为失败，再实现，随后运行通过。保留原有 48 个测试不变。

- 服务测试：空库、生成正文三部分、同日再次生成、重新实例化后的持久化、详情查找、适配器失败时不写入虚假记录。
- HTTP 测试：页面和资源可访问、生成→列表→详情完整链路、未知 ID、非法 JSON、非法方法、目录穿越、内部失败的错误响应。
- 浏览器端到端测试：空列表、生成完整正文、刷新恢复、筛选搜索、复制读取剪贴板、下载核对文件内容、后端异常后可重试、详情失败、移动端布局和控制台错误。
- 原有 Python 测试全部通过。
- 所有验收结论附本轮实际命令、结果和局限；不将测试后补描述为先测试，也不将未安装插件描述为已安装。

## 流程记录

已读取官方 using-superpowers、brainstorming、writing-plans、test-driven-development、verification-before-completion 技能文档。
插件查询确认 Superpowers 当前未安装；可由用户安装，也可在明确说明情况下继续遵循已读取的官方技能文档。
本设计经审阅后，进入 writing-plans，生成实施计划并按其交接流程执行。实现后同步三份项目规范，补充 README 启动命令和本轮验证记录。
本轮不自动发布或向老师发送消息；成果保留在项目目录供用户提交。
