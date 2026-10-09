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
let generating = false;
let toastTimer;
let detailVersion = 0;
let listVersion = 0;
let returnFocus = null;

function esc(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
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
  $('#modalBody').innerHTML = `
    <div class="pipeline" aria-label="处理结果">
      <div class="step is-ok"><div class="step-top"><span class="step-dot"></span><span class="step-name">模拟采集</span></div><p class="step-mod">使用演示工作记录</p></div>
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
    const last = $('#modalExport');
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
$('#modalCopy').addEventListener('click', copyReport);
$('#modalExport').addEventListener('click', exportReport);
$('#aboutBtn').addEventListener('click', () => toast('模拟工作记录生成日报，保存于本机；演示不发送外部通知。'));

loadState();
if (location.protocol === 'file:') {
  showLoadError('请先运行本地服务：python web_server.py，然后访问 http://127.0.0.1:8765');
  $('#retryBtn').hidden = true;
} else {
  loadReports();
}
