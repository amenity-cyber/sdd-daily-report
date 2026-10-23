'use strict';

// 所有日报由本地 API 提供；localStorage 只保存显示偏好。
const $ = selector => document.querySelector(selector);
const STATUS_MAP = {
  '未开始': { cls: 'badge-idle', label: '未开始' },
  '进行中': { cls: 'badge-run', label: '进行中' },
  '已完成': { cls: 'badge-ok', label: '已完成' },
};
let tasks = [];
let currentFilter = 'all';
let currentQuery = '';
let currentReport = null;
let serviceMode = 'unknown';
let sendingEmail = false;
let generating = false;
let toastTimer;
let detailVersion = 0;
let listVersion = 0;
let returnFocus = null;
const ACTIVITY_TYPES = [
  { key: 'commits', label: '代码提交', color: 'commit' },
  { key: 'tasks', label: '飞书任务', color: 'task' },
];

function esc(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

async function api(path, options = {}) {
  const controller = new AbortController();
  // Real collection and SMTP each make several sequential network calls.
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败，请重试');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请重试');
    if (error instanceof TypeError) throw new Error('无法连接本地服务，请确认服务已启动');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function toast(message, error = false) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.toggle('is-error', error);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, 3500);
}

function syncNavActive() {
  document.querySelectorAll('[data-filter]').forEach(button => {
    const active = button.dataset.filter === currentFilter;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function saveState() {
  try {
    localStorage.setItem('dr.filter', currentFilter);
    localStorage.setItem('dr.query', currentQuery);
  } catch (_) { /* 显示偏好存储不可用不影响日报功能。 */ }
}

function loadState() {
  try {
    const filter = localStorage.getItem('dr.filter');
    currentFilter = filter === 'all' || Object.hasOwn(STATUS_MAP, filter) ? filter : 'all';
    currentQuery = localStorage.getItem('dr.query') || '';
  } catch (_) { /* 默认显示全部。 */ }
  $('#searchInput').value = currentQuery;
  syncNavActive();
}

function renderTable() {
  const query = currentQuery.trim().toLowerCase();
  const rows = tasks.filter(task => (currentFilter === 'all' || task.status === currentFilter)
    && (!query || [task.id, `DR-${task.id}`, task.name, task.owner].some(value => String(value).toLowerCase().includes(query))));
  $('#taskBody').innerHTML = rows.map(task => {
    const status = STATUS_MAP[task.status] || STATUS_MAP['未开始'];
    return `<tr data-id="${esc(task.id)}" tabindex="0">
      <td class="cell-id">DR-${esc(task.id)}</td>
      <td><div class="cell-main">${esc(task.name)}</div><div class="cell-sub meta">${esc(task.owner)}</div></td>
      <td><span class="badge ${status.cls}"><span class="dot"></span>${status.label}</span></td>
      <td class="col-time num">${esc(task.createdAt.replace('T', ' '))}</td>
      <td class="col-action"><button class="btn btn-secondary btn-sm" type="button" data-view="${esc(task.id)}">查看详情</button></td>
    </tr>`;
  }).join('');
  $('#emptyState').hidden = rows.length > 0 || !$('#loadError').hidden;
  $('#emptyTitle').textContent = tasks.length ? '没有匹配的日报' : '暂无日报';
  $('#emptyDescription').textContent = tasks.length ? '请调整筛选条件或搜索关键词。' : '点击生成新日报开始。';
  $('#resultCount').textContent = `共 ${rows.length} 条 · 全部 ${tasks.length} 条`;
  const counts = { all: tasks.length, '未开始': 0, '进行中': 0, '已完成': 0 };
  tasks.forEach(task => { if (Object.hasOwn(counts, task.status)) counts[task.status] += 1; });
  document.querySelectorAll('[data-count]').forEach(element => { element.textContent = counts[element.dataset.count]; });
  $('#kpiTotal').textContent = tasks.length;
  $('#kpiRunning').textContent = generating ? 1 : 0;
  $('#kpiDone').textContent = counts['已完成'];
  $('#kpiDate').textContent = tasks[0]?.reportDate || '—';
}

function showLoadError(message) {
  $('#loadErrorText').textContent = message;
  $('#loadError').hidden = false;
  $('#loadStatus').hidden = true;
  renderTable();
}

function renderAnalytics(analytics) {
  const sourceStatus = analytics.sources || {};
  const failedSources = Object.entries({
    github: 'GitHub API', feishu_tasks: '飞书任务',
  }).filter(([key]) => sourceStatus[key] === false).map(([, label]) => label);
  if (sourceStatus.local_git) failedSources.push('当前只使用本机 Git 克隆记录补充提交');
  $('#sourceWarning').hidden = failedSources.length === 0;
  $('#sourceWarning').textContent = failedSources.length
    ? `部分实时数据源不可用（${failedSources.join('、')}），图表数据可能不完整。请检查代理/网络、API 权限和服务日志。`
    : '';
  const today = analytics.today;
  const total = today.total;
  $('#chartTodayLabel').textContent = today.date;
  const polar = angle => {
    const radians = angle * Math.PI / 180;
    return [72 + 56 * Math.cos(radians), 72 + 56 * Math.sin(radians)];
  };
  let angle = -90;
  const arcs = ACTIVITY_TYPES.map(type => {
    const value = today.counts[type.key] || 0;
    const sweep = total ? 360 * value / total : 0;
    if (sweep <= 0) return '';
    const start = polar(angle);
    if (sweep >= 359.99) {
      const middle = polar(angle + 180);
      const end = polar(angle + 360);
      angle += sweep;
      return `<path class="donut-segment chart-${type.color}" d="M ${start[0]} ${start[1]} A 56 56 0 1 1 ${middle[0]} ${middle[1]} A 56 56 0 1 1 ${end[0]} ${end[1]}" />`;
    }
    const end = polar(angle + sweep);
    const arc = `<path class="donut-segment chart-${type.color}" d="M ${start[0]} ${start[1]} A 56 56 0 ${sweep > 180 ? 1 : 0} 1 ${end[0]} ${end[1]}" />`;
    angle += sweep;
    return arc;
  }).join('');
  $('#todayDonut').setAttribute('aria-label', `今日共 ${total} 项活动`);
  $('#todayDonut').innerHTML = `<svg viewBox="0 0 144 144" aria-hidden="true"><circle class="donut-track" cx="72" cy="72" r="56" />${arcs}<text class="donut-total" x="72" y="70">${total}</text><text class="donut-unit" x="72" y="91">项活动</text></svg>`;
  $('#todayLegend').innerHTML = ACTIVITY_TYPES.map(type => `<li><span class="legend-dot chart-${type.color}"></span><span>${type.label}</span><strong>${today.counts[type.key] || 0}</strong></li>`).join('');

  const points = analytics.week;
  const max = Math.max(1, ...points.map(point => point.total));
  const plot = { left: 42, right: 610, top: 28, bottom: 190 };
  const x = index => plot.left + (plot.right - plot.left) * index / Math.max(1, points.length - 1);
  const y = value => plot.bottom - (plot.bottom - plot.top) * value / max;
  const line = points.map((point, index) => `${x(index)},${y(point.total)}`).join(' ');
  const area = `${plot.left},${plot.bottom} ${line} ${plot.right},${plot.bottom}`;
  const grid = [0, Math.ceil(max / 2), max].filter((value, index, all) => all.indexOf(value) === index)
    .map(value => `<g><line class="chart-grid-line" x1="${plot.left}" y1="${y(value)}" x2="${plot.right}" y2="${y(value)}"/><text class="chart-axis-label" x="${plot.left - 12}" y="${y(value) + 4}" text-anchor="end">${value}</text></g>`).join('');
  const dots = points.map((point, index) => `<circle class="chart-point" cx="${x(index)}" cy="${y(point.total)}" r="4"><title>${point.date}：${point.total} 项活动</title></circle>`).join('');
  const labels = points.map((point, index) => `<text class="chart-date-label" x="${x(index)}" y="${plot.bottom + 25}" text-anchor="middle">${point.label}</text>`).join('');
  const weeklyTotal = points.reduce((sum, point) => sum + point.total, 0);
  $('#weeklyChart').setAttribute('aria-label', `近七天共 ${weeklyTotal} 项活动`);
  $('#weeklyChart').innerHTML = `<svg viewBox="0 0 640 240" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="activityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" class="chart-fill-start"/><stop offset="100%" class="chart-fill-end"/></linearGradient></defs>${grid}<polygon class="chart-area" points="${area}"/><polyline class="chart-line" points="${line}"/>${dots}${labels}</svg><p class="chart-footnote">近七天累计 <strong>${weeklyTotal}</strong> 项活动</p>`;
}

async function loadAnalytics() {
  try {
    const { analytics } = await api('/api/analytics');
    renderAnalytics(analytics);
  } catch (error) {
    $('#chartTodayLabel').textContent = '暂时无法加载';
    $('#todayDonut').setAttribute('aria-label', error.message);
    $('#weeklyChart').setAttribute('aria-label', error.message);
  }
}

async function loadHealth() {
  try {
    const { mode, source, sources = {} } = await api('/api/health');
    serviceMode = mode;
    const badge = $('#modeBadge');
    badge.textContent = mode === 'real' ? '真实数据 · 本地联调' : '模拟数据 · 本地联调';
    badge.classList.toggle('pill--warn', mode !== 'real');
    const configured = [sources.github && 'GitHub', sources.feishu && '飞书', sources.email && '邮件'].filter(Boolean);
    $('#sourceDescription').textContent = mode === 'real'
      ? `实时数据源：${source || configured.join(' / ') || '请检查配置'}。${configured.length ? `已配置：${configured.join('、')}。` : ''}邮件发送仅在点击后执行。`
      : '当前使用演示数据，保存到本机，不连接外部服务。';
    $('#pageLead').textContent = mode === 'real'
      ? '从 GitHub 与飞书实时采集工作记录，生成并保存日报；同一天再次生成会更新当日日报。'
      : '从模拟工作记录生成完整日报，保存在本机，随时查看、复制或导出。同一天再次生成会更新当日日报。';
  } catch (error) {
    $('#modeBadge').textContent = '服务连接失败';
    $('#sourceDescription').textContent = error.message;
  }
}

async function loadReports() {
  const version = ++listVersion;
  $('#loadError').hidden = true;
  $('#loadStatus').textContent = '正在加载日报…';
  $('#loadStatus').hidden = false;
  $('#retryBtn').disabled = true;
  try {
    const data = await api('/api/reports');
    if (version !== listVersion) return;
    if (!Array.isArray(data.reports)) throw new Error('日报列表格式异常，请重试');
    tasks = data.reports;
    $('#loadStatus').hidden = true;
    renderTable();
  } catch (error) {
    if (version === listVersion) showLoadError(error.message);
  } finally {
    if (version === listVersion) {
      $('#retryBtn').disabled = false;
      $('#createBtn').disabled = generating;
    }
  }
}

function showDetail(report, focusTarget) {
  if (typeof report.markdown !== 'string') throw new Error('日报正文格式异常');
  currentReport = report;
  returnFocus = focusTarget || document.activeElement;
  const status = STATUS_MAP[report.status] || STATUS_MAP['未开始'];
  $('#modalBadge').className = `badge ${status.cls}`;
  $('#modalBadge').textContent = status.label;
  $('#modalTitle').textContent = report.name;
  $('#modalSubtitle').textContent = `DR-${report.id} · ${report.owner}`;
  $('#modalEmail').hidden = report.mode !== 'real';
  $('#modalEmail').disabled = Boolean(report.emailSent);
  $('#modalEmail').classList.toggle('is-sent', Boolean(report.emailSent));
  $('#modalEmail').textContent = report.emailSent ? '已提交' : '发送邮件';
  if (report.emailSent) currentReport.emailSent = true;
  $('#modalBody').innerHTML = `
    <div class="pipeline" aria-label="处理结果">
      <div class="step is-ok"><div class="step-top"><span class="step-dot"></span><span class="step-name">${report.mode === 'real' ? '实时采集' : '模拟采集'}</span></div><p class="step-mod">${report.mode === 'real' ? '读取已配置的 GitHub / 飞书数据' : '使用演示工作记录'}</p></div>
      <div class="step is-ok"><div class="step-top"><span class="step-dot"></span><span class="step-name">生成日报</span></div><p class="step-mod">完整 Markdown 正文</p></div>
      <div class="step is-ok"><div class="step-top"><span class="step-dot"></span><span class="step-name">本地保存</span></div><p class="step-mod">可刷新、复制与导出</p></div>
    </div>
    <div class="meta-grid">
      <div class="meta-cell"><p class="meta-key">数据来源</p><p class="meta-val">${esc(report.source)}</p></div>
      <div class="meta-cell"><p class="meta-key">生成时间</p><p class="meta-val">${esc(report.createdAt.replace('T', ' '))}</p></div>
    </div>
    <div><div class="report-head"><h3>日报正文</h3></div><pre id="reportMarkdown" class="report-markdown"></pre></div>`;
  $('#reportMarkdown').textContent = report.markdown;
  $('#modalBackdrop').hidden = false;
  $('.app').inert = true;
  document.body.style.overflow = 'hidden';
  $('#modalClose').focus();
}

async function openDetail(id, focusTarget) {
  const version = ++detailVersion;
  try {
    const data = await api('/api/reports/' + encodeURIComponent(id));
    if (version === detailVersion) showDetail(data.report, focusTarget);
  } catch (error) {
    if (version === detailVersion) toast(error.message, true);
  }
}

function closeDetail() {
  ++detailVersion;
  $('#modalBackdrop').hidden = true;
  $('.app').inert = false;
  document.body.style.overflow = '';
  currentReport = null;
  if (returnFocus?.isConnected) returnFocus.focus();
}

async function createReport() {
  if (generating) return;
  generating = true;
  ++listVersion;
  $('#loadStatus').hidden = true;
  $('#createBtn').disabled = true;
  $('#createBtn').textContent = '正在生成…';
  renderTable();
  try {
    const { report } = await api('/api/reports', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const { markdown, html, ...metadata } = report;
    tasks = [metadata, ...tasks.filter(task => task.id !== report.id)]
      .sort((a, b) => b.reportDate.localeCompare(a.reportDate));
    currentFilter = 'all';
    currentQuery = '';
    $('#searchInput').value = '';
    saveState();
    syncNavActive();
    // POST 已持久化；重新读取完整历史，刷新失败由列表错误栏提供重试。
    await loadReports();
    await loadAnalytics();
    ++detailVersion;
    showDetail(report, $('#createBtn'));
    toast('日报已生成并保存到本机');
  } catch (error) {
    toast(error.message, true);
  } finally {
    generating = false;
    $('#createBtn').disabled = false;
    $('#createBtn').textContent = '生成新日报';
    $('#retryBtn').disabled = false;
    renderTable();
  }
}

async function copyReport() {
  if (!currentReport) return;
  const text = currentReport.markdown;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.className = 'copy-buffer';
      $('#modal').append(textarea);
      textarea.select();
      try {
        if (!document.execCommand('copy')) throw new Error('Copy unavailable');
      } finally {
        textarea.remove();
        $('#modalCopy').focus();
      }
    }
    toast('日报正文已复制');
  } catch (_) {
    toast('复制失败，请选中正文手动复制', true);
  }
}

function exportReport() {
  if (!currentReport) return;
  const blob = new Blob([currentReport.markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `daily-report-${currentReport.reportDate}-${currentReport.id}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('已发起 Markdown 下载');
}

async function emailReport() {
  if (!currentReport || sendingEmail) return;
  sendingEmail = true;
  const button = $('#modalEmail');
  button.disabled = true;
  button.textContent = '正在发送…';
  try {
    await api(`/api/reports/${encodeURIComponent(currentReport.id)}/email`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    currentReport.emailSent = true;
    button.textContent = '已提交';
    button.disabled = true;
    button.classList.add('is-sent');
    toast('邮件已提交至 SMTP 服务器；请检查收件箱或垃圾邮件');
  } catch (error) {
    toast(error.message, true);
  } finally {
    sendingEmail = false;
    if (currentReport && !currentReport.emailSent) {
      button.disabled = false;
      button.textContent = '发送邮件';
    }
  }
}

document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  currentFilter = button.dataset.filter;
  syncNavActive(); saveState(); renderTable();
}));
$('#searchInput').addEventListener('input', event => { currentQuery = event.target.value; saveState(); renderTable(); });
$('#taskBody').addEventListener('click', event => {
  const button = event.target.closest('[data-view]');
  const row = event.target.closest('tr[data-id]');
  if (row) openDetail(row.dataset.id, button || row);
});
$('#taskBody').addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.matches('tr[data-id]')) {
    event.preventDefault(); openDetail(event.target.dataset.id, event.target);
  }
});
$('#createBtn').addEventListener('click', createReport);
$('#retryBtn').addEventListener('click', loadReports);
$('#modalClose').addEventListener('click', closeDetail);
$('#modalBackdrop').addEventListener('click', event => { if (event.target === $('#modalBackdrop')) closeDetail(); });
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeDetail();
  if (event.key === 'Tab' && !$('#modalBackdrop').hidden) {
    const first = $('#modalClose');
    const last = $('#modalEmail').hidden ? $('#modalExport') : $('#modalEmail');
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
$('#modalCopy').addEventListener('click', copyReport);
$('#modalExport').addEventListener('click', exportReport);
$('#modalEmail').addEventListener('click', emailReport);
$('#aboutBtn').addEventListener('click', () => toast(serviceMode === 'real' ? '日报由已配置的数据源生成；邮件仅在点击发送后发出。' : '当前使用模拟工作记录生成日报，保存于本机。'));

loadState();
if (location.protocol === 'file:') {
  showLoadError('请先运行本地服务：python web_server.py，然后访问 http://127.0.0.1:8765');
  $('#retryBtn').hidden = true;
} else {
  loadHealth();
  loadReports();
  loadAnalytics();
}
