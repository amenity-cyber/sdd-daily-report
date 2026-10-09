/* 完整浏览器验收；运行环境和命令见 README。每次使用独立数据库。 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.WEB_TEST_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const browserPath = process.env.WEB_TEST_BROWSER;
const results = [];
let server, browser;

function startServer(db) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-B', 'web_server.py', '--port', '0', '--db', db], {
      cwd: root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    server = child;
    let output = '';
    const timer = setTimeout(() => reject(new Error('Server startup timeout: ' + output)), 15000);
    child.stdout.on('data', chunk => {
      output += chunk.toString();
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
    child.stderr.on('data', chunk => { output += chunk.toString(); });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', code => { clearTimeout(timer); if (!output.includes('http://127.0.0.1:')) reject(new Error('Server exited ' + code + ': ' + output)); });
  });
}

async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const child = server;
  await new Promise(resolve => { child.once('exit', resolve); child.kill(); });
  server = null;
}

async function check(name, fn) {
  await fn();
  results.push(name);
  console.log('PASS ' + name);
}

(async () => {
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true });
  const out = await fs.mkdtemp(path.join(root, 'test-results', 'web-'));
  const db = path.join(out, 'reports.db');
  let base = await startServer(db);
  browser = await chromium.launch({ headless: true, ...(browserPath ? { executablePath: browserPath } : {}) });
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, acceptDownloads: true });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);

  await check('empty history comes from API', async () => {
    await page.locator('#emptyState').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#taskBody tr').count(), 0);
    assert.match(await page.locator('#emptyState').innerText(), /暂无日报/);
  });
  let report;
  await check('generate produces persisted complete Markdown', async () => {
    await page.locator('#createBtn').click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    for (const heading of ['代码提交', '任务进展', '协作沟通']) assert.match(await page.locator('#modalBody').innerText(), new RegExp(heading));
    const rows = await (await context.request.get(base + '/api/reports')).json();
    assert.equal(rows.reports.length, 1);
    report = (await (await context.request.get(base + '/api/reports/' + rows.reports[0].id)).json()).report;
    assert.equal(await page.locator('#reportMarkdown').textContent(), report.markdown);
  });
  await check('copy writes actual Markdown to clipboard', async () => {
    await page.locator('#modalCopy').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('已复制'));
    // Windows 剪贴板把 LF 转成 CRLF；正文比较只归一化平台换行。
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    assert.equal(copied.replace(/\r\n/g, '\n'), report.markdown.replace(/\r\n/g, '\n'));
  });
  await check('export downloads matching UTF-8 Markdown', async () => {
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#modalExport').click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /\.md$/);
    const target = path.join(out, 'export.md');
    await download.saveAs(target);
    assert.equal(await fs.readFile(target, 'utf8'), report.markdown);
  });
  await page.locator('#modalClose').click();
  await check('refresh and same-day regeneration preserve one record', async () => {
    await page.reload();
    await page.locator('#taskBody tr').first().waitFor();
    assert.equal(await page.locator('#taskBody tr').count(), 1);
    await page.locator('#createBtn').click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    const rows = await (await context.request.get(base + '/api/reports')).json();
    assert.equal(rows.reports.length, 1);
    assert.equal(rows.reports[0].id, report.id);
    await page.locator('#modalClose').click();
  });
  await check('search, status filter and stale preference recovery', async () => {
    await page.locator('#searchInput').fill('不存在的日报');
    assert.equal(await page.locator('#taskBody tr').count(), 0);
    await page.locator('#searchInput').fill('DR-' + report.id);
    assert.equal(await page.locator('#taskBody tr').count(), 1);
    await page.locator('#searchInput').fill('演示');
    assert.equal(await page.locator('#taskBody tr').count(), 1);
    await page.locator('[data-filter="未开始"]').click();
    assert.equal(await page.locator('#taskBody tr').count(), 0);
    await page.evaluate(() => { localStorage.setItem('dr.filter', 'obsolete'); localStorage.setItem('dr.query', ''); });
    await page.reload();
    await page.locator('#taskBody tr').first().waitFor();
    assert.equal(await page.locator('[data-filter="all"]').getAttribute('aria-pressed'), 'true');
  });
  await check('generation failure preserves history and permits retry', async () => {
    await page.route('**/api/reports', route => route.request().method() === 'POST'
      ? route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: '测试生成失败' }) }) : route.continue());
    await page.locator('#createBtn').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('测试生成失败'));
    assert.equal(await page.locator('#taskBody tr').count(), 1);
    assert.equal(await page.locator('#createBtn').isEnabled(), true);
    await page.unroute('**/api/reports');
    await page.locator('#createBtn').click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    await page.locator('#modalClose').click();
  });
  await check('detail failure is visible and retry works', async () => {
    await page.route('**/api/reports/*', route => route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"测试日报不存在"}' }));
    await page.locator('[data-view]').first().click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('测试日报不存在'));
    assert.equal(await page.locator('#modalBackdrop').isHidden(), true);
    await page.unroute('**/api/reports/*');
    await page.locator('[data-view]').first().click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#modalBackdrop').isHidden(), true);
    assert.equal(await page.locator('[data-view]').first().evaluate(el => document.activeElement === el), true);
  });
  await check('untrusted Markdown is text rather than executable HTML', async () => {
    await page.route('**/api/reports/*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ report: { ...report, markdown: '<img src=x onerror="window.injected=true">中文正文' } }) }));
    await page.locator('[data-view]').first().click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    assert.match(await page.locator('#reportMarkdown').textContent(), /<img/);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator('#modalClose').click();
    await page.unroute('**/api/reports/*');
  });
  await check('offline list shows retryable failure, not fake history', async () => {
    await page.route('**/api/reports', route => route.abort());
    await page.reload();
    await page.locator('#loadError').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#taskBody tr').count(), 0);
    await page.unroute('**/api/reports');
    await page.locator('#retryBtn').click();
    await page.locator('#taskBody tr').first().waitFor();
  });
  await check('generation after failed initial load restores older database history', async () => {
    await execFileAsync(python, ['-B', '-c',
      'import sys; from datetime import date; from shared.storage import ReportStorage; ReportStorage(sys.argv[1]).save_report(date(2025,1,1),"历史团队","# 历史日报","<h1>历史日报</h1>")', db],
      { cwd: root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    await page.route('**/api/reports', route => route.request().method() === 'GET' ? route.abort() : route.continue());
    await page.reload();
    await page.locator('#loadError').waitFor({ state: 'visible' });
    await page.unroute('**/api/reports');
    await page.locator('#createBtn').click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    await page.locator('#modalClose').click();
    assert.equal(await page.locator('#taskBody tr').count(), 2);
    assert.match(await page.locator('#taskBody').innerText(), /历史团队/);
  });
  await check('successful generation with failed list refresh keeps explicit retry error', async () => {
    await page.route('**/api/reports', route => route.request().method() === 'GET' ? route.abort() : route.continue());
    await page.locator('#createBtn').click();
    await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
    await page.locator('#modalClose').click();
    assert.equal(await page.locator('#loadError').isVisible(), true);
    assert.equal(await page.locator('#createBtn').isEnabled(), true);
    await page.unroute('**/api/reports');
    await page.locator('#retryBtn').click();
    await page.waitForFunction(() => document.querySelectorAll('#taskBody tr').length === 2);
  });
  await check('desktop and mobile layouts have no page overflow', async () => {
    for (const width of [1366, 390]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(out, width === 390 ? 'mobile.png' : 'desktop.png'), fullPage: true });
      await page.locator('[data-view]').first().click();
      await page.locator('#modalBackdrop').waitFor({ state: 'visible' });
      assert.equal(await page.evaluate(() => document.querySelector('#modal').scrollWidth <= document.querySelector('#modal').clientWidth), true);
      await page.locator('#modal').evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
      // 固定定位弹窗使用当前视口截图，避免 fullPage 把已滚动页面与弹窗拼接。
      await page.screenshot({ path: path.join(out, width === 390 ? 'mobile-detail.png' : 'desktop-detail.png') });
      await page.keyboard.press('Escape');
    }
  });
  await check('server restart retains database history', async () => {
    await stopServer();
    base = await startServer(db);
    await page.goto(base);
    await page.locator('#taskBody tr').first().waitFor();
    assert.equal(await page.locator('#taskBody tr').count(), 2);
    assert.equal((await (await context.request.get(base + '/api/reports')).json()).reports[0].id, report.id);
  });
  await check('file open explains service startup', async () => {
    const local = await context.newPage();
    await local.goto('file:///' + path.join(root, 'web_ui', 'index.html').replaceAll('\\', '/'));
    assert.match(await local.locator('#loadError').innerText(), /本地服务/);
    await local.close();
  });
  await check('no uncaught page errors', async () => assert.deepEqual(errors, []));
  await fs.writeFile(path.join(out, 'summary.json'), JSON.stringify({ passed: results.length, checks: results }, null, 2));
  console.log(JSON.stringify({ passed: results.length, output: out }));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopServer();
});
