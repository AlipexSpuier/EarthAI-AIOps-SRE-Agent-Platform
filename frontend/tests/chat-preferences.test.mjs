import { after, before, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-chat-preferences-tests');
await mkdir(cache, { recursive: true });
await build({ entryPoints: ['tests/harness.ts'], outfile: `${cache}/harness.mjs`, bundle: true, packages: 'external', platform: 'node', target: 'node22', jsx: 'automatic', format: 'esm' });
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/chat', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, { window, document: window.document, Node: window.Node, HTMLElement: window.HTMLElement, Event: window.Event, MouseEvent: window.MouseEvent, CustomEvent: window.CustomEvent, FormData: window.FormData, File: window.File, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.HTMLElement.prototype.scrollTo = function () {};
window.HTMLElement.prototype.scrollIntoView = function () {};
const { createRoot } = await import('react-dom/client');
const { App, AuthProvider, useAuth } = await import(pathToFileURL(`${cache}/harness.mjs`).href);
const originalFetch = globalThis.fetch;
const fields = ['agent_id', 'control_level', 'model', 'project_id', 'provider_id', 'server_id'];
const at = '2026-10-24T12:00:00.000Z';
const basePreferences = { server_id: 'server-one', provider_id: 'provider-one', model: 'my-custom-model', agent_id: 'agent-one', project_id: 'project-one', control_level: 'observe' };
const baseUser = { id: 'preferences-user', name: '偏好用户', email: 'preferences@example.com', avatar: 'EA', theme: 'light', control_level: 'approve' };
const collections = {
  servers: [{ id: 'server-one', name: '第一服务器', kind: 'ssh', host: '192.0.2.1', port: 22, tags: [], status: 'online' }, { id: 'server-two', name: '第二服务器', kind: 'ssh', host: '192.0.2.2', port: 22, tags: [], status: 'online' }],
  providers: [{ id: 'provider-one', name: '第一供应商', enabled: true, models: ['model-one', 'model-two'], default_model: 'model-one' }, { id: 'provider-two', name: '第二供应商', enabled: true, models: ['backup-model'], default_model: 'backup-model' }],
  agents: [{ id: 'agent-one', name: '第一智能体', description: '', skill_ids: [], knowledge_ids: [], provider_id: 'provider-one', model: 'model-two', control_level: 'approve' }, { id: 'agent-two', name: '第二智能体', description: '', skill_ids: [], knowledge_ids: [], provider_id: 'provider-two', model: 'agent-custom', control_level: 'autonomous' }],
  projects: [{ id: 'project-one', name: '第一项目', status: 'active', server_ids: [], knowledge_ids: [] }, { id: 'project-two', name: '第二项目', status: 'active', server_ids: [], knowledge_ids: [] }],
  skills: [], knowledge: [],
};
let root;
let auth;
let state;
let requests;
let gate;
let providerGate;
let preferencesGate;
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function response(data, status = 200) { return { ok: status < 400, status, json: async () => structuredClone(data) }; }
function mockFetch(path, options = {}) {
  const url = String(path);
  const body = options.body ? JSON.parse(options.body) : undefined;
  requests.push({ url, options, body });
  if (url === '/api/auth/me') {
    if (options.method === 'PATCH') Object.assign(state.user, body);
    return Promise.resolve(response(state.loggedIn ? state.user : { detail: '请先登录' }, state.loggedIn ? 200 : 401));
  }
  if (url === '/api/auth/login') { state.loggedIn = true; return Promise.resolve(response(state.user)); }
  if (url === '/api/auth/logout') { state.loggedIn = false; return Promise.resolve(response({ ok: true })); }
  if (url === '/api/preferences/chat') {
    if (options.method === 'PATCH') {
      const save = () => {
        if (state.saveFailure) return response({ detail: '测试保存失败' }, 503);
        Object.assign(state.preferences, body);
        return response(state.preferences);
      };
      if (gate) { const current = gate; gate = null; return current.promise.then(save); }
      return Promise.resolve(save());
    }
    if (preferencesGate) return preferencesGate.promise.then(() => response(state.preferences));
    return Promise.resolve(response(state.preferences));
  }
  if (url === '/api/runs') return Promise.resolve(response([]));
  if (url === '/api/runs/run-new') return Promise.resolve(response({ run: state.run, events: [], approvals: [] }));
  if (url === '/api/conversations') {
    if (options.method === 'POST') {
      const conv = { id: 'conversation-new', ...body, created_at: at, updated_at: at };
      state.conversations.push(conv);
      return Promise.resolve(response(conv));
    }
    return Promise.resolve(response(state.conversations));
  }
  const conversation = url.match(/^\/api\/conversations\/([^/]+)(\/messages)?$/);
  if (conversation) {
    const conv = state.conversations.find(item => item.id === conversation[1]);
    if (conversation[2]) {
      state.run = { id: 'run-new', conversation_id: conv.id, status: 'completed', goal: body.content, ...body, summary: '已完成', created_at: at, updated_at: at, step_count: 1 };
      return Promise.resolve(response(state.run));
    }
    if (options.method === 'PATCH') Object.assign(conv, body);
    return Promise.resolve(response({ conversation: conv, messages: [], runs: [] }));
  }
  const key = url.replace('/api/', '');
  if (key in state.collections) {
    if (key === 'providers' && providerGate) return providerGate.promise.then(() => response(state.collections[key]));
    return Promise.resolve(response(state.collections[key]));
  }
  return Promise.resolve(response({ detail: `Unexpected API ${url}` }, 404));
}
function Probe() { auth = useAuth(); return createElement('div', null, auth.user?.id || 'logged-out'); }
function picker(label) { const item = document.querySelector(`[role="combobox"][aria-label="${label}"]`); assert.ok(item, label); return item; }
function click(item) { assert.ok(item, 'click target exists'); item.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); }); }
async function render(node = createElement(App), path = '/chat') {
  window.history.replaceState(null, '', path);
  await act(async () => { root = createRoot(document.getElementById('root')); root.render(node); });
  await settle();
}
async function cleanup() {
  if (root) { await act(async () => root.unmount()); root = null; }
  document.body.innerHTML = '<div id="root"></div>';
}
async function choose(label, text) {
  await act(async () => click(picker(label)));
  const option = [...document.querySelectorAll('[role="option"]')].find(item => item.getAttribute('aria-label') === text);
  assert.ok(option, `${label}: ${text}`);
  await act(async () => click(option));
}
async function navigate(path) {
  await act(async () => { window.history.pushState(null, '', path); window.dispatchEvent(new window.PopStateEvent('popstate')); });
  await settle();
}
function patches() { return requests.filter(item => item.url === '/api/preferences/chat' && item.options.method === 'PATCH'); }
function assertBaseSelected() {
  for (const [label, text] of [['选择服务器', '第一服务器'], ['选择供应商', '第一供应商'], ['选择模型', 'my-custom-model'], ['选择智能体', '第一智能体'], ['项目上下文', '第一项目'], ['控制等级', '观察模式']]) assert.ok(picker(label).textContent.includes(text), `${label}: ${text}`);
}
before(() => { globalThis.fetch = mockFetch; });
beforeEach(async () => {
  await cleanup();
  state = { user: structuredClone(baseUser), preferences: structuredClone(basePreferences), collections: structuredClone(collections), conversations: [], loggedIn: true, saveFailure: false };
  requests = []; gate = null; providerGate = null; preferencesGate = null;
});
after(async () => { await cleanup(); globalThis.fetch = originalFetch; dom.window.close(); });

test('new chat waits for both catalogs and server preferences and never saves initialization defaults', async () => {
  providerGate = deferred(); preferencesGate = deferred();
  await render();
  assert.equal(picker('选择服务器').disabled, true);
  assert.equal(patches().length, 0);
  await act(async () => { preferencesGate.resolve(); }); await settle();
  assert.equal(picker('选择服务器').disabled, true);
  await act(async () => { providerGate.resolve(); }); await settle();
  assertBaseSelected();
  assert.equal(patches().length, 0);
});

test('all six preferences survive route changes, browser storage clearing, remount and re-login', async () => {
  window.localStorage.setItem('ignored-old-chat-state', 'stale');
  await render(); assertBaseSelected();
  await navigate('/servers');
  await navigate('/chat'); assertBaseSelected();
  window.localStorage.clear();
  await cleanup(); await render(); assertBaseSelected();
  await cleanup();
  await render(createElement(AuthProvider, null, createElement(Probe)));
  await act(async () => auth.logout());
  await act(async () => auth.login('preferences@example.com', 'fake-test-password'));
  await cleanup(); await render(); assertBaseSelected();
  assert.equal(patches().length, 0);
});

test('each manual control saves before sending; rapid controls use ordered patches without losing earlier choices', async () => {
  await render();
  const first = deferred(); gate = first;
  await choose('选择服务器', '第二服务器');
  assert.equal(patches().length, 1);
  assert.deepEqual(patches()[0].body, { server_id: 'server-two' });
  await choose('项目上下文', '第二项目');
  await choose('控制等级', '审批模式');
  await choose('选择模型', 'model-two');
  assert.equal(patches().length, 1, 'later patches wait for the in-flight request');
  assert.ok(picker('选择服务器').textContent.includes('第二服务器'));
  assert.ok(picker('项目上下文').textContent.includes('第二项目'));
  await act(async () => { first.resolve(); }); await settle();
  assert.deepEqual(patches().map(item => item.body), [{ server_id: 'server-two' }, { project_id: 'project-two' }, { control_level: 'approve' }, { provider_id: 'provider-one', model: 'model-two' }]);
  assert.equal(state.preferences.server_id, 'server-two');
  assert.equal(state.preferences.project_id, 'project-two');
  assert.equal(state.preferences.control_level, 'approve');
  assert.equal(state.preferences.model, 'model-two');
  await choose('选择智能体', '第二智能体');
  assert.deepEqual(patches().at(-1).body, { agent_id: 'agent-two', provider_id: 'provider-two', model: 'agent-custom', control_level: 'autonomous' });
  await choose('选择供应商', '第一供应商');
  assert.deepEqual(patches().at(-1).body, { provider_id: 'provider-one', model: 'model-one' });
  assert.ok(patches().every(item => item.options.keepalive && item.options.credentials === 'same-origin'));
  assert.equal(requests.some(item => item.url.endsWith('/messages')), false);
});

test('an in-flight save survives leaving chat and returning waits for persisted preferences', async () => {
  await render(); const first = deferred(); gate = first;
  await choose('选择服务器', '第二服务器');
  await navigate('/servers'); await navigate('/chat');
  assert.equal(picker('选择服务器').disabled, true);
  await act(async () => { first.resolve(); }); await settle();
  assert.ok(picker('选择服务器').textContent.includes('第二服务器'));
  assert.equal(patches().length, 1);
});

test('historical initialization never overwrites defaults and manual history edits only save changed fields', async () => {
  state.conversations = [{ id: 'history', title: '历史会话', server_id: 'server-two', provider_id: 'provider-two', model: 'history-only-model', agent_id: 'agent-two', project_id: 'project-two', control_level: 'autonomous', created_at: at, updated_at: at }];
  await render(createElement(App), '/chat/history');
  assert.ok(picker('选择模型').textContent.includes('history-only-model'));
  assert.ok(picker('控制等级').textContent.includes('自主模式'));
  assert.equal(patches().length, 0);
  await navigate('/chat'); assertBaseSelected();
  await navigate('/chat/history');
  await choose('选择服务器', '不连接服务器');
  assert.deepEqual(patches().at(-1).body, { server_id: null });
  assert.equal(state.preferences.model, 'my-custom-model');
  assert.equal(state.preferences.provider_id, 'provider-one');
  assert.equal(state.conversations[0].server_id, 'server-two', 'history is not mutated just by choosing next-session configuration');
  await navigate('/chat');
  assert.ok(picker('选择服务器').textContent.includes('不连接服务器'));
  assert.ok(picker('选择模型').textContent.includes('my-custom-model'));
});

test('manually changing a historical model saves its matching provider without copying unrelated history fields', async () => {
  state.conversations = [{ id: 'history-model', title: '另一供应商的历史', server_id: 'server-two', provider_id: 'provider-two', model: 'history-custom', agent_id: 'agent-two', project_id: 'project-two', control_level: 'autonomous', created_at: at, updated_at: at }];
  await render(createElement(App), '/chat/history-model');
  await choose('选择模型', 'backup-model');
  assert.deepEqual(patches().at(-1).body, { provider_id: 'provider-two', model: 'backup-model' });
  assert.equal(state.preferences.server_id, 'server-one');
  assert.equal(state.preferences.control_level, 'observe');
  await navigate('/chat');
  assert.ok(picker('选择供应商').textContent.includes('第二供应商'));
  assert.ok(picker('选择模型').textContent.includes('backup-model'));
  assert.ok(picker('控制等级').textContent.includes('观察模式'));
});

test('context links override only their fields and never silently elevate an observe default', async () => {
  await render(createElement(App), '/chat?server=server-two');
  assert.ok(picker('选择服务器').textContent.includes('第二服务器'));
  assert.ok(picker('项目上下文').textContent.includes('第一项目'));
  assert.ok(picker('选择模型').textContent.includes('my-custom-model'));
  await navigate('/chat?project=project-two');
  assert.ok(picker('选择服务器').textContent.includes('第一服务器'));
  assert.ok(picker('项目上下文').textContent.includes('第二项目'));
  await navigate('/chat?agent=agent-two');
  assert.ok(picker('选择智能体').textContent.includes('第二智能体'));
  assert.ok(picker('选择供应商').textContent.includes('第二供应商'));
  assert.ok(picker('选择模型').textContent.includes('agent-custom'));
  assert.ok(picker('控制等级').textContent.includes('观察模式'));
  await navigate('/chat?server=&agent=&project=');
  assert.ok(picker('选择服务器').textContent.includes('不连接服务器'));
  assert.ok(picker('选择智能体').textContent.includes('通用运维助手'));
  assert.ok(picker('项目上下文').textContent.includes('不关联项目'));
  assert.ok(picker('选择模型').textContent.includes('my-custom-model'));
  assert.equal(patches().length, 0);
});

test('sending a conversation and starting another chat retain preferences instead of resetting them', async () => {
  await render();
  await choose('选择服务器', '第二服务器');
  await act(async () => click(document.querySelector('.prompt-card')));
  await act(async () => document.querySelector('form.composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  await settle();
  const created = requests.find(item => item.url === '/api/conversations' && item.options.method === 'POST');
  assert.equal(created.body.server_id, 'server-two');
  assert.equal(created.body.provider_id, 'provider-one');
  assert.equal(created.body.model, 'my-custom-model');
  assert.equal(created.body.control_level, 'observe');
  assert.equal(window.location.pathname, '/chat/conversation-new');
  await navigate('/chat');
  assert.ok(picker('选择服务器').textContent.includes('第二服务器'));
  assert.ok(picker('选择模型').textContent.includes('my-custom-model'));
  assert.ok(picker('控制等级').textContent.includes('观察模式'));
  assert.equal(patches().length, 1);
});

test('failed saves are explicit and drafts, credentials and history fields never enter the preference request', async () => {
  state.saveFailure = true;
  await render();
  await act(async () => click(document.querySelector('.prompt-card')));
  await choose('选择服务器', '第二服务器');
  assert.match(document.querySelector('.toast-stack').textContent, /新会话配置保存失败.*测试保存失败/);
  assert.deepEqual(patches()[0].body, { server_id: 'server-two' });
  assert.ok(patches().every(item => Object.keys(item.body).every(key => fields.includes(key))));
  assert.equal(state.preferences.server_id, 'server-one');
  state.saveFailure = false;
  await choose('选择服务器', '第一服务器');
  assert.equal(state.preferences.server_id, 'server-one');
});

test('deleted or disabled catalog resources clear gently without selecting another provider or saving defaults', async () => {
  state.collections.servers = state.collections.servers.filter(item => item.id !== 'server-one');
  state.collections.agents = state.collections.agents.filter(item => item.id !== 'agent-one');
  state.collections.projects = state.collections.projects.filter(item => item.id !== 'project-one');
  state.collections.providers[0].enabled = false;
  await render();
  assert.ok(picker('选择服务器').textContent.includes('不连接服务器'));
  assert.ok(picker('选择智能体').textContent.includes('通用运维助手'));
  assert.ok(picker('项目上下文').textContent.includes('不关联项目'));
  assert.ok(picker('选择供应商').textContent.includes('选择供应商'));
  assert.ok(picker('选择模型').textContent.includes('先选择供应商'));
  assert.equal(picker('选择模型').disabled, true);
  assert.equal(patches().length, 0);
  assert.equal(document.querySelectorAll('select,datalist').length, 0);
});

test('logout drains pending preferences before removing the session and pagehide sends pending changes with keepalive', async () => {
  await render(createElement(AuthProvider, null, createElement(Probe)));
  const first = deferred(); gate = first;
  let saveOne; let saveTwo;
  await act(async () => {
    saveOne = auth.saveChatPreferences({ server_id: 'server-two' });
    saveTwo = auth.saveChatPreferences({ control_level: 'observe' });
  });
  assert.equal(patches().length, 1);
  await act(async () => window.dispatchEvent(new window.PageTransitionEvent('pagehide')));
  assert.equal(patches().length, 2);
  assert.deepEqual(patches()[1].body, { server_id: 'server-two', control_level: 'observe' });
  assert.equal(patches()[1].options.keepalive, true);
  let logout;
  await act(async () => { logout = auth.logout(); });
  assert.equal(requests.some(item => item.url === '/api/auth/logout'), false);
  await act(async () => { first.resolve(); await Promise.all([saveOne, saveTwo, logout]); });
  assert.equal(requests.at(-1).url, '/api/auth/logout');
  assert.equal(state.loggedIn, false);
  assert.equal(auth.user, null);
});
