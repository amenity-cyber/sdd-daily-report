# 前后端联调验证记录

日期：2026-10-09（Asia/Shanghai）。审查前代码基线：9678da18e3dbee789996559966f457f6cbe35210。

## 流程与范围

用户先批准书面设计，再批准实施计划并明确选择当前 main 分支原地执行、完成后独立审查。采用读取的 Superpowers 官方技能文档：using-superpowers、brainstorming、writing-plans、executing-plans、test-driven-development、systematic-debugging、verification-before-completion，以及 requesting-code-review 审查模板。

插件查询确认当时尚未安装，已向用户提供安装入口；本次不声称已安装或调用插件。使用官方文档流程执行，任务状态和裁定保存在 progress.md。

本轮验证的是本机 Mock 联调：模拟记录经过原生成器生成 Markdown/HTML，保存到真实 SQLite，再通过真实 HTTP 请求和浏览器操作验证。没有验证真实 GitHub/飞书凭据、邮件投递、飞书推送或定时调度。

## RED → GREEN 证据

Task 1：先新增 tests/test_web_service.py，运行时报 `ModuleNotFoundError: No module named 'web_backend'`。实现后 5 个测试通过，包括空库、三部分正文、详情、重开数据库保留、同日更新、历史记录、未知 ID 和失败不写入。

Task 2：先新增 tests/test_web_http.py，运行时报 `ModuleNotFoundError: No module named 'web_server'`。实现后服务与 HTTP 合计 22 个测试通过，包含生成→列表→详情真实链路、404、非法 JSON、非法方法和内部异常恢复。

Task 3：先运行浏览器脚本验证旧页面，数据库为空但页面仍有硬编码样例，等待空列表断言失败。接入 API 后生成断言通过；复制测试发现 Windows 剪贴板自动将 LF 转换为 CRLF。归一化平台换行后比较完整正文，导出文件仍以原始 UTF-8 文本逐字节比较。

## 已执行命令与结果

以下命令在项目 SDD_text 目录执行。由于沙箱阻止 pytest 临时目录访问及浏览器子进程，实际验证使用获准的沙箱外执行；没有把环境权限错误算作产品失败或跳过测试。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=../web-final-verified-20261009
```

最终结果：`70 passed in 9.62s`，包括原有 48 项测试和新增 22 项；原有测试文件未修改。

```powershell
$env:PLAYWRIGHT_MODULE='C:/Users/15509/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
$env:WEB_TEST_BROWSER='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
& 'C:/Users/15509/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tests/web_e2e.cjs
```

最终结果：16 个浏览器验收检查通过。脚本使用独立数据库、随机本机端口、真实无窗口 Edge，结束后关闭进程。

1. 空库时页面显示空列表，列表来自 API。
2. 点击生成得到完整正文，与后端 Markdown 一致并持久化。
3. 点击复制后读取系统剪贴板，正文完整一致（只归一化平台换行）。
4. 点击导出后读取实际下载文件，UTF-8 内容与后端正文逐字节一致。
5. 刷新与同日再次生成保持一条记录，ID 稳定。
6. 搜索、显示编号 DR-<id> 搜索、状态筛选及失效的缓存筛选值恢复正常。
7. 模拟生成 500 后已有列表保留、按钮恢复，再次点击成功。
8. 模拟详情 404 有可读提示，恢复后可正常打开；Esc 关闭恢复焦点。
9. 含 HTML 标签的正文按文本展示，不执行脚本。
10. 模拟服务离线，列表显示错误，重新加载恢复。
11. 1366px 与 390px 视口页面无整体横向溢出，弹窗内容无横向溢出。
12. 测试服务停止并重新启动后，数据库中的日报仍在。
13. file:// 直接打开给出本地服务启动引导。
14. 无未捕获的页面 JavaScript 异常。
15. 初次加载失败后，生成成功重新读取完整历史，较早日期的日报仍显示。
16. 生成保存成功但列表刷新失败时，仍显示重试错误；恢复后能重新加载完整历史。

最终结果与截图：`test-results/web-UuuYxd/summary.json`，`desktop.png`、`mobile.png`、`desktop-detail.png`、`mobile-detail.png`，以及实际下载 `export.md`。目录被 Git 忽略，规范和本文可随代码提交。

已目视检查桌面列表和窄屏弹窗截图。固定定位弹窗截图按视口保存，避免全页截图把滚动位置与弹窗拼接；这不更改产品行为。

## 独立审查

独立 reviewer 已审阅设计、计划、进度、全部本轮变更和五项 Review Focus，发现 1 项重要问题、1 项轻微问题。

- 重要：初次列表加载失败后直接生成，客户端缓存缺少较早历史，成功提示后页面仅显示新记录。先写浏览器复现：数据库有两条但页面一条（1 !== 2）；修复为成功保存后重新获取完整列表，刷新失败保留错误和重试入口；最终 16 项浏览器检查通过。
- 轻微：页面显示 DR-1，但搜索只匹配原始 ID。新增浏览器断言先失败（0 !== 1），将显示编号加入搜索后通过。由于页面承诺编号搜索，本轮按功能缺陷处理，不留待后续。

审查为只读，未改动文件或 Git；审查者另行执行只读 Node VM 验证历史遗漏、编号搜索和剪贴板拒绝后的失败提示。未独立重跑全量测试；修复后由实施者实际运行最终 Python 与浏览器套件验证。无遗留已知审查问题。

审查明确未判断外部平台接入、真实通知、身份认证或调度，这些属于已批准设计的排除范围，不据此声称生产上线能力。

## 裁定与交付

- 插件未安装时，用官方技能文档及可提交的进度记录替代插件辅助脚本。代价：不能声称插件已安装或提供插件调用截图。
- Windows 剪贴板换行归一化后比较正文；下载仍逐字节比较。代价：剪贴板验证不保证跨平台换行字节相同，但正文与段落须完整。
- 用户明确授权当前 main 原地执行；成果保存到原项目。本地服务已启动并验证 health 返回 {"status":"ok","mode":"mock"}，可访问 http://127.0.0.1:8765 。
- 启动、验证和接口说明见 README；三份规范、设计、计划、此验证记录可用于本轮提交。

官方流程来源：[brainstorming](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md)、[writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md)、[executing-plans](https://github.com/obra/superpowers/blob/main/skills/executing-plans/SKILL.md)、[test-driven-development](https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md)、[verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)。

## 限制

已实际验证 Windows Edge；其他浏览器未运行。剪贴板依赖浏览器授权，拒绝授权时应提示失败；Web 界面为本机演示，无用户认证。默认无历史样例，需点击生成；同一日重复生成按原存储约束更新正文。

Superpowers 插件未安装；如果课程明确要求插件运行截图，本文不能替代该截图。OpenDesign 原型来源以已有 Git 记录和前端迭代报告为依据，本轮没有重新运行 OpenDesign。
