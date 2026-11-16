import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-tests');
await mkdir(cache, { recursive: true });
await build({ entryPoints: ['tests/harness.ts'], outfile: `${cache}/harness.mjs`, bundle: true, packages: 'external', platform: 'node', target: 'node22', jsx: 'automatic', format: 'esm' });
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/chat', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, { window, document: window.document, Node: window.Node, HTMLElement: window.HTMLElement, Event: window.Event, MouseEvent: window.MouseEvent, CustomEvent: window.CustomEvent, FormData: window.FormData, File: window.File, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.HTMLElement.prototype.scrollTo = function () {};
window.HTMLElement.prototype.scrollIntoView = function () {};
Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: async () => undefined } });
const { createRoot } = await import('react-dom/client');
const { App, AuthProvider, ExecutionProvider, ToastProvider, useExecutions, Select, Content, mergeEvents, applyRunEvents, mergeApprovals } = await import(pathToFileURL(`${cache}/harness.mjs`).href);
const originalFetch = globalThis.fetch;
const at = n => `2026-10-24T10:00:${String(n).padStart(2, '0')}.000Z`;
const user = { id: 'user-test', name: '测试账户', email: 'test@example.com', avatar: 'EA', theme: 'light', control_level: 'approve' };
const makeRun = (extra = {}) => ({ id: 'run-test', conversation_id: 'conversation-test', status: 'running', goal: '测试任务', model: 'test-model', control_level: 'approve', created_at: at(0), updated_at: at(1), step_count: 1, ...extra });
const event = (id, type, data, time = id + 1) => ({ id, run_id: 'run-test', type, data, created_at: at(time) });
let root;
let execution;
let serverDetail;
let requestLog = [];
let routeState = { conversations: [] };
let streamInstances = [];
class FakeEventSource {
  static CLOSED = 2;
  readyState = 1;
  closed = false;
  constructor(url, options) { this.url = url; this.options = options; streamInstances.push(this); }
  emit(value) { if (!this.closed) this.onmessage?.({ data: JSON.stringify(value) }); }
  close() { this.closed = true; this.readyState = 2; }
}
globalThis.EventSource = FakeEventSource;
function response(data, status = 200) { return { ok: status < 400, status, json: async () => structuredClone(data) }; }
function mockFetch(path, options = {}) {
  const url = String(path); requestLog.push({ url, options });
  if (url === '/api/auth/me') return Promise.resolve(response(user));
  if (url === '/api/runs') return Promise.resolve(response(routeState.runs || []));
  if (url === '/api/runs/run-test') return Promise.resolve(response(serverDetail));
  if (url === '/api/approvals/approval-test') {
    const approved = JSON.parse(options.body).approved;
    serverDetail = { ...serverDetail, approvals: serverDetail.approvals.map(approval => ({ ...approval, status: approved ? 'approved' : 'rejected' })) };
    return Promise.resolve(response(serverDetail.approvals[0]));
  }
  if (url === '/api/runs/run-test/cancel') {
    serverDetail = { ...serverDetail, run: { ...serverDetail.run, status: 'cancelled', updated_at: at(40) } };
    return Promise.resolve(response(serverDetail.run));
  }
  if (url === '/api/overview') return Promise.resolve(response({ counts: Object.fromEntries(['servers', 'conversations', 'runs', 'files', 'knowledge', 'skills', 'projects', 'schedules', 'alerts', 'providers'].map(key => [key, 0])), active_runs: [], recent_runs: [], alerts: [], daily_runs: [], recent_audit: [], health: { status: 'ok', database: 'ok', version: 'test' } }));
  if (url === '/api/conversations' && options.method === 'POST') {
    const conversation = { id: 'conversation-test', ...JSON.parse(options.body), created_at: at(0), updated_at: at(0) };
    routeState.conversations = [conversation]; return Promise.resolve(response(conversation));
  }
  if (url === '/api/conversations/conversation-test/messages' && options.method === 'POST') {
    const payload = JSON.parse(options.body);
    serverDetail = { run: makeRun({ goal: payload.content, ...payload }), events: [event(1, 'status', { status: 'running' })], approvals: [] };
    routeState.runs = [serverDetail.run]; routeState.messages = [{ id: 'message-test', role: 'user', content: payload.content, created_at: at(0), run_id: 'run-test' }];
    return Promise.resolve(response(serverDetail.run));
  }
  if (url === '/api/conversations') return Promise.resolve(response(routeState.conversations));
  if (url === '/api/conversations/conversation-test') return Promise.resolve(response({ conversation: routeState.conversations?.[0] || { id: 'conversation-test', title: '测试对话', control_level: 'approve', created_at: at(0), updated_at: at(0) }, messages: routeState.messages || [], runs: routeState.runs || [] }));
  if (url.startsWith('/api/knowledge/') && url.endsWith('/documents')) return Promise.resolve(response([]));
  const collection = url.match(/^\/api\/(servers|providers|agents|projects|knowledge|skills|schedules|alerts|audit|files)(?:\/([^/]+))?$/);
  if (collection) {
    const key = `/api/${collection[1]}`; routeState.collections ||= {}; const items = routeState.collections[key] ||= [];
    if (options.method === 'POST') {
      const payload = options.body instanceof window.FormData ? { name: options.body.get('file')?.name, size: options.body.get('file')?.size, mime: 'text/plain', created_at: at(0) } : JSON.parse(options.body);
      const item = { id: `created-${collection[1]}`, ...(collection[1] === 'knowledge' ? { document_count: 0, chunk_count: 0 } : {}), ...payload }; items.push(item); return Promise.resolve(response(item));
    }
    if (options.method === 'DELETE') { routeState.collections[key] = items.filter(item => item.id !== collection[2]); return Promise.resolve(response({ ok: true })); }
    if (options.method === 'PATCH') { const item = items.find(item => item.id === collection[2]); if (item) Object.assign(item, JSON.parse(options.body)); return Promise.resolve(response(item || {})); }
    return Promise.resolve(response(items));
  }
  return Promise.resolve(response({ detail: `Unexpected API ${url}` }, 404));
}
function Probe() { execution = useExecutions(); return createElement('span', null, Object.values(execution.runs).map(snapshot => `${snapshot.run.id}:${snapshot.run.status}:${snapshot.events.length}`).join(',')); }
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); }); }
async function render(node) { await act(async () => { root = createRoot(document.getElementById('root')); root.render(node); }); await settle(); }
async function cleanup() { if (root) { await act(async () => root.unmount()); root = null; } document.body.innerHTML = '<div id="root"></div>'; }
function providers(node) { return createElement(ToastProvider, null, createElement(AuthProvider, null, createElement(ExecutionProvider, null, node))); }
function click(button) { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
before(() => { globalThis.fetch = mockFetch; });
after(async () => { await cleanup(); globalThis.fetch = originalFetch; dom.window.close(); });

test('events merge by ID and remain in chronological order', () => {
  const one = event(1, 'status', { status: 'running' }); const two = event(2, 'assistant', { content: '答案' });
  assert.deepEqual(mergeEvents([two, one], [one, two]).map(item => item.id), [1, 2]);
});
test('persisted terminal status is not reverted by historical running events', () => {
  const run = makeRun({ status: 'interrupted', updated_at: at(30) });
  assert.equal(applyRunEvents(run, [event(1, 'status', { status: 'running' })]).status, 'interrupted');
  assert.equal(applyRunEvents(makeRun(), [event(2, 'status', { status: 'waiting_approval' }), event(3, 'done', { status: 'completed', summary: '已完成' })]).status, 'completed');
});
test('approval decisions cannot regress to pending and terminal approvals expire', () => {
  const approval = { id: 'approval-test', run_id: 'run-test', status: 'approved' };
  const pending = event(2, 'approval', { ...approval, status: 'pending' });
  assert.equal(mergeApprovals([approval], [{ ...approval, status: 'pending' }], [pending], 'running')[0].status, 'approved');
  assert.equal(mergeApprovals([], [], [pending], 'cancelled')[0].status, 'expired');
});
test('SSE restores history, resumes after cursor, deduplicates, survives page changes and can cancel', async () => {
  streamInstances = []; requestLog = []; routeState = { runs: [makeRun()] };
  serverDetail = { run: makeRun(), events: [event(1, 'status', { status: 'running' })], approvals: [] };
  await render(providers(createElement(Probe)));
  assert.equal(streamInstances.length, 1);
  const stream = streamInstances[0]; assert.match(stream.url, /after=1$/); assert.equal(stream.options.withCredentials, true);
  const next = event(2, 'assistant', { content: '真实事件' });
  await act(async () => { stream.emit(next); stream.emit(next); });
  assert.equal(execution.runs['run-test'].events.length, 2);
  await act(async () => root.render(providers(createElement('div', null, '另一页', createElement(Probe)))));
  assert.equal(stream.closed, false); assert.equal(streamInstances.length, 1);
  await act(async () => execution.cancel('run-test'));
  assert.equal(execution.runs['run-test'].run.status, 'cancelled'); assert.equal(stream.closed, true);
  assert.ok(requestLog.every(request => request.options.credentials === 'same-origin'));
  await cleanup();
});
test('persisted approval can be allowed through real decision endpoint', async () => {
  streamInstances = []; const approval = { id: 'approval-test', run_id: 'run-test', tool_name: 'ssh_exec', arguments: { command: 'systemctl restart example' }, risk: 'write', status: 'pending', created_at: at(2) };
  serverDetail = { run: makeRun({ status: 'waiting_approval', updated_at: at(3) }), events: [event(1, 'approval', approval, 2)], approvals: [approval] };
  routeState = { runs: [serverDetail.run] };
  await render(providers(createElement(Probe)));
  assert.equal(execution.runs['run-test'].approvals[0].status, 'pending');
  await act(async () => execution.decide(approval, true));
  assert.equal(execution.runs['run-test'].approvals[0].status, 'approved');
  assert.ok(requestLog.some(request => request.url === '/api/approvals/approval-test' && JSON.parse(request.options.body).approved === true));
  await cleanup();
});
test('message rendering escapes raw HTML, including malicious image handlers', async () => {
  await render(createElement(Content, { text: '<img src=x onerror="alert(1)">\n<script>alert(2)</script>\n**安全文本**\n```html\n<iframe src="x"></iframe>\n```' }));
  assert.equal(document.querySelectorAll('img,script,iframe').length, 0);
  assert.match(document.body.textContent, /<img src=x/); assert.ok(document.querySelector('strong'));
  await cleanup();
});
test('all authenticated routes render truthful empty states without errors', async () => {
  routeState = { runs: [], conversations: [] }; streamInstances = [];
  const routes = { '/chat': '今天想解决什么', '/overview': '让一切，尽在掌握', '/servers': '连接你的工作现场', '/providers': '为工作空间注入智能', '/agents': '让专业，有专属的伙伴', '/space': '一处收纳，随时取用', '/knowledge': '让知识，参与每一次决策', '/skills': '把经验，变成可复用的能力', '/projects': '以业务，组织你的世界', '/schedules': '把规律的事，放心交给时间', '/alerts': '重要的问题，不被错过', '/settings': '你的空间，你的节奏' };
  for (const [route, expected] of Object.entries(routes)) {
    window.history.replaceState(null, '', route);
    await render(createElement(App));
    assert.ok(document.body.textContent.includes(expected), `${route}: expected heading ${expected}`);
    assert.ok(!document.body.textContent.includes('页面暂时遇到问题'), `${route}: no fatal render error`);
    await cleanup();
  }
});
test('new resource forms open, expose required fields and close accessibly', async () => {
  const forms = { '/servers': '添加服务器', '/providers': '添加供应商', '/agents': '创建智能体', '/knowledge': '创建知识库', '/skills': '创建技能', '/projects': '创建项目', '/schedules': '创建定时任务', '/alerts': '记录告警' };
  for (const [route, label] of Object.entries(forms)) {
    window.history.replaceState(null, '', route);
    await render(createElement(App));
    const button = [...document.querySelectorAll('button')].find(button => button.textContent.includes(label));
    assert.ok(button, `${route}: create action`);
    await act(async () => click(button));
    const dialog = document.querySelector('[role="dialog"]');
    assert.ok(dialog, `${route}: accessible dialog`); assert.ok(dialog.querySelector('[required]'), `${route}: real form fields`);
    const closeButton = dialog.querySelector('[aria-label="关闭对话框"]');
    await act(async () => click(closeButton));
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await cleanup();
  }
});
test('resource forms submit correct API fields and CRUD mutations update lists', async () => {
  const cases = [
    { route: '/servers', label: '添加服务器', endpoint: '/api/servers', fields: { name: '测试服务器', host: '192.0.2.1', username: 'ubuntu', private_key: 'test-private-key-not-real', fingerprint: 'SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' }, expected: { kind: 'ssh', port: 22, auth_type: 'key' } },
    { route: '/providers', label: '添加供应商', endpoint: '/api/providers', fields: { name: '测试供应商', base_url: 'https://example.com/v1', api_key: 'test-secret', default_model: 'example-model', models: 'example-model,model-two' }, expected: { enabled: true, models: ['example-model', 'model-two'] } },
    { route: '/agents', label: '创建智能体', endpoint: '/api/agents', fields: { name: '测试智能体', system_prompt: '请进行只读诊断。' }, expected: { skill_ids: [], knowledge_ids: [], control_level: 'approve' } },
    { route: '/knowledge', label: '创建知识库', endpoint: '/api/knowledge', fields: { name: '测试知识库', description: '真实文档上下文' }, expected: { description: '真实文档上下文' } },
    { route: '/skills', label: '创建技能', endpoint: '/api/skills', fields: { name: '测试技能', content: '# 只读诊断\n不要执行变更。' }, expected: { enabled: true } },
    { route: '/projects', label: '创建项目', endpoint: '/api/projects', fields: { name: '测试项目' }, expected: { server_ids: [], knowledge_ids: [], status: 'active' } },
    { route: '/schedules', label: '创建定时任务', endpoint: '/api/schedules', fields: { name: '测试定时任务', prompt: '请进行只读健康检查。' }, expected: { cron: '0 9 * * *', timezone: 'Asia/Shanghai', enabled: true } },
    { route: '/alerts', label: '记录告警', endpoint: '/api/alerts', fields: { title: '测试告警', description: '服务异常' }, expected: { severity: 'warning', status: 'open', server_id: null } },
  ];
  for (const item of cases) {
    routeState = { runs: [], conversations: [], collections: {} }; requestLog = [];
    window.history.replaceState(null, '', item.route); await render(createElement(App));
    await act(async () => click([...document.querySelectorAll('button')].find(button => button.textContent.includes(item.label))));
    const form = document.querySelector('[role="dialog"] form'); assert.ok(form);
    for (const [name, value] of Object.entries(item.fields)) { const input = form.elements.namedItem(name); assert.ok(input, `${item.route} ${name}`); input.value = value; }
    await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); await settle();
    const posted = requestLog.find(request => request.url === item.endpoint && request.options.method === 'POST'); assert.ok(posted, `${item.route}: POST collection`);
    const payload = JSON.parse(posted.options.body);
    for (const [key, value] of Object.entries(item.expected)) assert.deepEqual(payload[key], value, `${item.route} payload ${key}`);
    assert.equal(document.querySelector('[role="dialog"]'), null, `${item.route}: success closes form`);
    assert.ok(document.body.textContent.includes(item.fields.name || item.fields.title), `${item.route}: saved entity visible`);
    await cleanup();
  }
  routeState = { runs: [], conversations: [], collections: { '/api/skills': [{ id: 'skill-edit', name: '原技能', description: '描述', content: '原指令', enabled: true }] } }; requestLog = [];
  window.history.replaceState(null, '', '/skills'); await render(createElement(App));
  await act(async () => click(document.querySelector('[aria-label="编辑技能"]')));
  const editForm = document.querySelector('[role="dialog"] form'); editForm.elements.namedItem('name').value = '更新后的技能';
  await act(async () => editForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); await settle();
  assert.ok(requestLog.some(request => request.url === '/api/skills/skill-edit' && request.options.method === 'PATCH'));
  assert.ok(document.body.textContent.includes('更新后的技能'));
  await act(async () => click(document.querySelector('[aria-label="删除技能"]')));
  await act(async () => click([...document.querySelectorAll('[role="dialog"] button')].find(button => button.textContent === '确认操作'))); await settle();
  assert.ok(requestLog.some(request => request.url === '/api/skills/skill-edit' && request.options.method === 'DELETE'));
  assert.ok(document.body.textContent.includes('每一份经验，都值得复用')); await cleanup();
});
test('chat sends actual server/provider/model/control selection and stream survives real route navigation', async () => {
  routeState = { runs: [], conversations: [], collections: {
    '/api/servers': [{ id: 'server-one', name: '测试服务器', kind: 'ssh', status: 'online', host: '192.0.2.1', tags: [] }],
    '/api/providers': [{ id: 'provider-one', name: '测试模型服务', enabled: true, models: ['model-one'], default_model: 'model-one' }],
  } }; requestLog = []; streamInstances = [];
  window.history.replaceState(null, '', '/chat'); await render(createElement(App));
  await act(async () => click([...document.querySelectorAll('.prompt-card')][0]));
  await act(async () => click(document.querySelector('[role="combobox"][aria-label="选择服务器"]')));
  await act(async () => click([...document.querySelectorAll('[role="option"]')].find(item => item.getAttribute('aria-label') === '测试服务器')));
  await act(async () => click(document.querySelector('[role="combobox"][aria-label="控制等级"]')));
  await act(async () => click([...document.querySelectorAll('[role="option"]')].find(item => item.getAttribute('aria-label') === '观察模式')));
  await act(async () => document.querySelector('form.composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); await settle();
  const posted = requestLog.find(request => request.url.endsWith('/messages') && request.options.method === 'POST'); assert.ok(posted);
  const payload = JSON.parse(posted.options.body); assert.equal(payload.server_id, 'server-one'); assert.equal(payload.provider_id, 'provider-one'); assert.equal(payload.model, 'model-one'); assert.equal(payload.control_level, 'observe');
  assert.equal(window.location.pathname, '/chat/conversation-test'); assert.equal(streamInstances.length, 1); const stream = streamInstances[0];
  await act(async () => click(document.querySelector('nav a[href="/servers"]'))); await settle();
  assert.equal(window.location.pathname, '/servers'); assert.equal(stream.closed, false);
  await act(async () => stream.emit(event(2, 'assistant', { content: '跨路由继续收到执行结果' })));
  assert.ok(document.querySelector('.execution-dock').textContent.includes('1 个任务正在运行'));
  await act(async () => click(document.querySelector('.dock-run'))); await settle();
  assert.ok(document.body.textContent.includes('跨路由继续收到执行结果')); assert.equal(stream.closed, false); await cleanup();
});
test('account settings, new chat and resource creation have a single visible entry', async () => {
  const cases = [['/chat', null], ['/servers', '添加服务器'], ['/providers', '添加供应商'], ['/agents', '创建智能体'], ['/projects', '创建项目'], ['/knowledge', '创建知识库'], ['/skills', '创建技能'], ['/schedules', '创建定时任务'], ['/alerts', '记录告警']];
  for (const [route, label] of cases) {
    routeState = { runs: [], conversations: [], collections: {} };
    window.history.replaceState(null, '', route); await render(createElement(App));
    assert.equal(document.querySelectorAll('a[href="/settings"]').length, 1, `${route}: one settings entry`);
    assert.equal(document.querySelectorAll('a[href="/chat"]').length, 1, `${route}: one new-chat entry`);
    assert.equal(document.querySelectorAll('select,datalist').length, 0, `${route}: no native selector`);
    if (label) assert.equal([...document.querySelectorAll('button')].filter(button => button.textContent.trim() === label).length, 1, `${route}: one create entry`);
    await cleanup();
  }
});
test('custom Select handles keyboard selection, focus and FormData without a native control', async () => {
  await render(createElement('form', null, createElement(Select, { name: 'choice', label: '测试选择器', defaultValue: 'first', options: [{ value: 'first', label: '第一个' }, { value: 'second', label: '第二个' }] })));
  const trigger = document.querySelector('[role="combobox"]'); trigger.focus();
  await act(async () => click(trigger));
  assert.equal(trigger.getAttribute('aria-expanded'), 'true');
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })));
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  assert.equal(new FormData(document.querySelector('form')).get('choice'), 'second');
  assert.equal(document.activeElement, trigger);
  assert.equal(document.querySelector('[role="listbox"]'), null);
  await act(async () => click(trigger));
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  assert.equal(trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(document.querySelectorAll('select,datalist').length, 0);
  await cleanup();
});
test('provider picker filters models and changing providers resets the previous model', async () => {
  routeState = { runs: [], conversations: [], collections: {
    '/api/providers': [
      { id: 'provider-one', name: '主供应商', enabled: true, models: ['model-one', 'model-two'], default_model: 'model-one' },
      { id: 'provider-two', name: '备供应商', enabled: true, models: ['backup-model'], default_model: 'backup-model' },
    ],
    '/api/agents': [{ id: 'agent-linked', name: '偏好主供应商', description: '', skill_ids: [], knowledge_ids: [], provider_id: 'provider-one', model: 'model-two', control_level: 'observe' }],
  } };
  requestLog = []; streamInstances = [];
  window.history.replaceState(null, '', '/chat'); await render(createElement(App));
  const picker = label => document.querySelector(`[role="combobox"][aria-label="${label}"]`);
  const select = async (label, name) => {
    await act(async () => click(picker(label)));
    await act(async () => click([...document.querySelectorAll('[role="option"]')].find(option => option.getAttribute('aria-label') === name)));
  };
  await select('选择供应商', '备供应商');
  assert.ok(picker('选择模型').textContent.includes('backup-model'));
  await act(async () => click(picker('选择模型')));
  assert.deepEqual([...document.querySelectorAll('[role="option"]')].map(option => option.getAttribute('aria-label')), ['backup-model']);
  await act(async () => picker('选择模型').dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  await select('选择智能体', '偏好主供应商');
  assert.ok(picker('选择供应商').textContent.includes('主供应商'));
  assert.ok(picker('选择模型').textContent.includes('model-two'));
  await select('选择供应商', '备供应商');
  await act(async () => click(document.querySelector('.prompt-card')));
  await act(async () => document.querySelector('form.composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  await settle();
  const request = requestLog.find(entry => entry.url.endsWith('/messages') && entry.options.method === 'POST');
  const payload = JSON.parse(request.options.body);
  assert.equal(payload.provider_id, 'provider-two');
  assert.equal(payload.model, 'backup-model');
  await cleanup();
});
