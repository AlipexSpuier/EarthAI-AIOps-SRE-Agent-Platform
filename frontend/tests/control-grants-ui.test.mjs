import { after, afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-control-grants-tests');
await mkdir(cache, { recursive: true });
await build({
  stdin: { contents: "export { ControlSelect, MultiSelect } from './src/components/ui'; export { UserResourceImportButton } from './src/components/UserResourceImport'; export * from './src/lib/controlAccess';", resolveDir: resolve('.'), loader: 'ts' },
  outfile: `${cache}/control-grants-ui.mjs`, bundle: true, packages: 'external', platform: 'node', target: 'node22', jsx: 'automatic', format: 'esm',
  loader: { '.css': 'text' }, logOverride: { 'ignored-bare-import': 'silent' },
  plugins: [{ name: 'control-grants-fixture', setup(builder) {
    builder.onLoad({ filter: /\/context\/AuthContext\.tsx$/ }, () => ({ contents: 'export function useAuth() { return globalThis.__controlGrantsAuth; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/CatalogContext\.tsx$/ }, () => ({ contents: 'export function useCatalog() { return globalThis.__controlGrantsCatalog; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/ToastContext\.tsx$/ }, () => ({ contents: 'export function useToast() { return globalThis.__controlGrantsNotify; }', loader: 'js' }));
  } }],
});
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/agents', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, { window, document: window.document, Node: window.Node, HTMLElement: window.HTMLElement, Event: window.Event, MouseEvent: window.MouseEvent, KeyboardEvent: window.KeyboardEvent, FormData: window.FormData, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
const { createRoot } = await import('react-dom/client');
const { allowedControlLevels, canUseControl, fallbackControl, ControlSelect, MultiSelect, UserResourceImportButton } = await import(pathToFileURL(`${cache}/control-grants-ui.mjs`).href);
const selectStyles = await readFile('src/components/Select.css', 'utf8');
const originalFetch = globalThis.fetch;
const allLevels = ['observe', 'approve', 'autonomous'];
const baseUser = { id: 'control-grants-user', email: 'grants@example.com', name: '授权测试用户', avatar: 'EA', theme: 'light', role: 'user', control_level: 'observe', allowed_control_levels: ['observe'] };
const legacyUser = { id: 'legacy-user', email: 'legacy@example.com', name: '旧账户', avatar: 'EA', theme: 'light', role: 'user', control_level: 'autonomous' };
const importFixtures = {
  agents: { label: '智能体', item: { name: '巡检助手', kind: 'local', system_prompt: '只报告实际证据', skill_ids: [], knowledge_ids: [] } },
  skills: { label: '技能', item: { name: '巡检技能', content: '核对状态与日志', enabled: true } },
  knowledge: { label: '知识库', item: { name: '业务手册', description: '经审阅的知识' } },
  projects: { label: '项目', item: { name: '测试项目', server_ids: [], skill_ids: [], knowledge_ids: [], status: 'active', color: '#087f69' } },
  servers: { label: '服务器', item: { name: '测试主机', kind: 'ssh', host: '192.0.2.10', port: 22, username: 'ops', auth_type: 'key', private_key: 'TEST-ONLY-NOT-A-REAL-KEY', tags: [] } },
  providers: { label: '供应商', item: { name: '测试供应商', base_url: 'https://provider.example.test/v1', api_key: 'TEST-ONLY-NOT-A-REAL-KEY', models: ['test-model'], enabled: true } },
  schedules: { label: '定时任务', item: { name: '每日检查', prompt: '检查并报告', cron: '0 9 * * *', timezone: 'Asia/Shanghai' } },
  alerts: { label: '告警', item: { title: '待核实异常', description: '保留证据', severity: 'warning', status: 'open', source: 'manual' } },
};
let root;
let requests;
let notices;
let changeEvents;
let apiResult;
let responseStatus;
let requestGate;
window.addEventListener('earthai:data-changed', () => { changeEvents += 1; });
beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  root = createRoot(document.getElementById('root'));
  requests = []; notices = []; changeEvents = 0;
  apiResult = { ok: true, count: 1 }; responseStatus = 200; requestGate = null;
  globalThis.__controlGrantsAuth = { user: structuredClone(baseUser) };
  globalThis.__controlGrantsCatalog = { servers: [], providers: [], projects: [], knowledge: [], skills: [], agents: [
    { id: 'agent-observe', name: '只读助手', kind: 'local', control_level: 'observe' },
    { id: 'agent-approve', name: '审批助手', kind: 'local', control_level: 'approve' },
    { id: 'agent-remote', name: '远程助手', kind: 'remote', control_level: 'observe' },
  ], loading: false, error: '', reload: async () => undefined };
  globalThis.__controlGrantsNotify = (message, tone) => { notices.push({ message, tone }); };
  globalThis.fetch = async (input, options = {}) => {
    const request = { url: String(input), method: options.method || 'GET', body: options.body === undefined ? undefined : JSON.parse(options.body), credentials: options.credentials, headers: options.headers };
    requests.push(request);
    assert.match(request.url, /^\/api\/(agents|skills|knowledge|projects|servers|providers|schedules|alerts)\/import$/);
    assert.equal(request.method, 'POST');
    if (requestGate) await requestGate.promise;
    return { ok: responseStatus < 400, status: responseStatus, json: async () => structuredClone(apiResult) };
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  delete globalThis.__controlGrantsAuth;
  delete globalThis.__controlGrantsCatalog;
  delete globalThis.__controlGrantsNotify;
  globalThis.fetch = originalFetch;
});
after(() => dom.window.close());
async function render(node) { await act(async () => root.render(node)); }
async function click(node) {
  assert.ok(node, 'click target exists');
  await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
}
async function key(node, value) {
  assert.ok(node, 'keyboard target exists');
  await act(async () => { node.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })); });
}
function controlPicker() { return document.querySelector('[role="combobox"][aria-label="控制等级"]'); }
function activeControl() {
  const id = controlPicker().getAttribute('aria-activedescendant');
  return id ? document.getElementById(id) : null;
}
function formData() { return new FormData(document.querySelector('form')); }
function multi(name) { return document.querySelector(`[data-multi-select="${name}"]`); }
function checkbox(name, value) { return multi(name).querySelector(`input[value="${value}"]`); }
async function renderImport(kind) { await render(createElement(UserResourceImportButton, { kind, label: importFixtures[kind].label })); }
async function openImport(kind) {
  await renderImport(kind);
  await click(document.querySelector(`[data-user-import-trigger="${kind}"]`));
  assert.ok(document.querySelector('[role="dialog"]'));
}
async function fillImport(text) {
  const textarea = document.querySelector('textarea[name="json"]');
  assert.ok(textarea);
  await act(async () => { textarea.value = text; textarea.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function submitImport() {
  const form = document.querySelector('[role="dialog"] form');
  assert.ok(form);
  await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }

test('control access preserves all three legacy grants without mutating the user or sharing its result', () => {
  const before = JSON.stringify(legacyUser);
  assert.deepEqual(allowedControlLevels(legacyUser), allLevels);
  for (const level of allLevels) {
    assert.equal(canUseControl(legacyUser, level), true);
    assert.equal(fallbackControl(legacyUser, level), level);
  }
  const levels = allowedControlLevels(legacyUser);
  levels.length = 0;
  assert.deepEqual(allowedControlLevels(legacyUser), allLevels);
  assert.equal(fallbackControl(legacyUser), 'observe');
  assert.equal(JSON.stringify(legacyUser), before);
});

test('new observe-only accounts cannot reuse approve or autonomous defaults', () => {
  assert.deepEqual(allowedControlLevels(baseUser), ['observe']);
  assert.equal(canUseControl(baseUser, 'observe'), true);
  for (const level of ['approve', 'autonomous', 'unknown', '', null, undefined, {}, 1]) assert.equal(canUseControl(baseUser, level), false);
  assert.equal(fallbackControl(baseUser, 'approve'), 'observe');
  assert.equal(fallbackControl(baseUser, 'autonomous'), 'observe');
  const restricted = { ...baseUser, allowed_control_levels: ['autonomous', 'approve'] };
  assert.deepEqual(allowedControlLevels(restricted), ['approve', 'autonomous']);
  assert.equal(fallbackControl(restricted), 'approve');
  assert.equal(fallbackControl(restricted, 'autonomous'), 'autonomous');
});

test('missing users and malformed or empty grants fail closed instead of becoming legacy users', () => {
  for (const user of [null, undefined]) {
    assert.deepEqual(allowedControlLevels(user), []);
    assert.equal(fallbackControl(user, 'autonomous'), undefined);
    for (const level of allLevels) assert.equal(canUseControl(user, level), false);
  }
  for (const grants of [null, false, 0, 'observe', {}, [], ['unknown'], ['observe', 'unknown'], ['observe', 'observe'], [null, 7, {}], [['observe']]]) {
    const user = { ...baseUser, allowed_control_levels: grants };
    assert.deepEqual(allowedControlLevels(user), [], JSON.stringify(grants));
    assert.equal(fallbackControl(user, 'observe'), undefined, JSON.stringify(grants));
    for (const level of allLevels) assert.equal(canUseControl(user, level), false, JSON.stringify(grants));
  }
});

test('administrators can configure all three modes regardless of their saved execution grants', () => {
  for (const grants of [undefined, [], ['observe'], null]) {
    const admin = { ...baseUser, role: 'admin', allowed_control_levels: grants };
    assert.deepEqual(allowedControlLevels(admin), allLevels);
    for (const level of allLevels) {
      assert.equal(canUseControl(admin, level), true);
      assert.equal(fallbackControl(admin, level), level);
    }
    assert.equal(canUseControl(admin, 'unknown'), false);
  }
});

test('ControlSelect keeps ungranted modes visibly disabled and clicking them cannot change FormData', async () => {
  const changes = [];
  await render(createElement('form', null, createElement(ControlSelect, { defaultValue: 'autonomous', onChange: value => changes.push(value) })));
  assert.equal(formData().get('control_level'), 'observe');
  await click(controlPicker());
  const options = [...document.querySelectorAll('[role="option"]')];
  assert.deepEqual(options.map(option => [option.getAttribute('aria-label'), option.getAttribute('aria-disabled')]), [['观察模式', null], ['审批模式', 'true'], ['自主模式', 'true']]);
  for (const option of options.slice(1)) {
    assert.match(option.textContent, /管理员未授权/);
    await click(option);
    assert.equal(formData().get('control_level'), 'observe');
    assert.equal(controlPicker().getAttribute('aria-expanded'), 'true');
  }
  assert.deepEqual(changes, []);
  const disabledRule = selectStyles.match(/\.ea-select-option\[aria-disabled=['"]true['"]\]\s*\{([^}]*)\}/)?.[1];
  assert.ok(disabledRule, 'disabled options have a dedicated visual rule');
  assert.match(disabledRule, /color:\s*var\(--muted\)/);
  assert.match(disabledRule, /opacity:\s*\.?\d+/);
  assert.match(disabledRule, /cursor:\s*not-allowed/);
  assert.equal(document.querySelectorAll('select,datalist').length, 0);
});

test('ControlSelect keyboard navigation skips a disabled middle mode in both directions', async () => {
  globalThis.__controlGrantsAuth.user.allowed_control_levels = ['observe', 'autonomous'];
  const changes = [];
  await render(createElement('form', null, createElement(ControlSelect, { onChange: value => changes.push(value) })));
  await key(controlPicker(), 'Home');
  assert.equal(activeControl().getAttribute('aria-label'), '观察模式');
  for (const [pressed, label] of [['ArrowDown', '自主模式'], ['ArrowDown', '观察模式'], ['ArrowUp', '自主模式'], ['Home', '观察模式'], ['End', '自主模式']]) {
    await key(controlPicker(), pressed);
    assert.equal(activeControl().getAttribute('aria-label'), label);
    assert.notEqual(activeControl().getAttribute('aria-disabled'), 'true');
  }
  await key(controlPicker(), 'Enter');
  assert.deepEqual(changes, ['autonomous']);
  assert.equal(formData().get('control_level'), 'autonomous');
  assert.equal(controlPicker().getAttribute('aria-expanded'), 'false');
});

test('ControlSelect uses a safe authorized default without emitting initialization changes', async () => {
  const changes = [];
  const cases = [
    { user: legacyUser, props: {}, expected: 'observe' },
    { user: baseUser, props: { defaultValue: 'autonomous' }, expected: 'observe' },
    { user: baseUser, props: { value: 'approve' }, expected: 'observe' },
    { user: { ...baseUser, allowed_control_levels: ['approve', 'autonomous'] }, props: {}, expected: 'approve' },
    { user: { ...baseUser, allowed_control_levels: ['autonomous'] }, props: { defaultValue: 'observe' }, expected: 'autonomous' },
    { user: { ...baseUser, allowed_control_levels: allLevels }, props: { defaultValue: 'approve' }, expected: 'approve' },
  ];
  for (const [index, item] of cases.entries()) {
    globalThis.__controlGrantsAuth.user = structuredClone(item.user);
    await render(createElement('form', { key: index }, createElement(ControlSelect, { ...item.props, name: 'safe_control', onChange: value => changes.push(value) })));
    assert.equal(formData().get('safe_control'), item.expected);
  }
  assert.deepEqual(changes, []);
});

test('ControlSelect immediately drops a revoked mode and never selects anything when no grant remains', async () => {
  const changes = [];
  globalThis.__controlGrantsAuth.user.allowed_control_levels = [...allLevels];
  const node = () => createElement('form', null, createElement(ControlSelect, { defaultValue: 'autonomous', onChange: value => changes.push(value) }));
  await render(node());
  assert.equal(formData().get('control_level'), 'autonomous');
  globalThis.__controlGrantsAuth.user.allowed_control_levels = ['observe'];
  await render(node());
  assert.equal(formData().get('control_level'), 'observe');
  globalThis.__controlGrantsAuth.user.allowed_control_levels = [];
  await render(node());
  assert.equal(formData().get('control_level'), '');
  assert.match(document.querySelector('.control-permission-hint').textContent, /尚未授权任何控制等级/);
  await key(controlPicker(), 'End');
  assert.equal(activeControl(), null);
  assert.equal(document.querySelectorAll('[role="option"][aria-disabled="true"]').length, 3);
  await key(controlPicker(), 'ArrowDown');
  await key(controlPicker(), 'Enter');
  assert.equal(formData().get('control_level'), '');
  assert.deepEqual(changes, []);
});

test('administrator ControlSelect exposes all three configuration options, even with an empty saved grant', async () => {
  globalThis.__controlGrantsAuth.user = { ...baseUser, role: 'admin', allowed_control_levels: [] };
  await render(createElement('form', null, createElement(ControlSelect)));
  await click(controlPicker());
  assert.equal(document.querySelectorAll('[role="option"]').length, 3);
  assert.equal(document.querySelectorAll('[role="option"][aria-disabled="true"]').length, 0);
  await click(document.querySelector('[role="option"][aria-label="自主模式"]'));
  assert.equal(formData().get('control_level'), 'autonomous');
});

const smallOptions = [{ id: 'one', name: '第一项' }, { id: 'two', name: '第二项' }, { id: 'locked', name: '停用项', disabled: true }];

test('MultiSelect select-all and clear preserve disabled selections and submit only enabled checked values', async () => {
  let submitted = 0;
  await render(createElement('form', { onSubmit: event => { event.preventDefault(); submitted += 1; } }, createElement(MultiSelect, { label: '技能', name: 'skill_ids', options: smallOptions, selected: ['one', 'locked'] })));
  const fieldset = multi('skill_ids');
  assert.equal(fieldset.tagName, 'FIELDSET');
  assert.equal(fieldset.querySelector('legend').textContent, '技能');
  assert.match(document.getElementById(fieldset.getAttribute('aria-describedby')).textContent, /已选 1 \/ 可选 2/);
  assert.match(fieldset.textContent, /另有 1 项已选但不可用/);
  assert.equal(checkbox('skill_ids', 'locked').disabled, true);
  assert.deepEqual(formData().getAll('skill_ids'), ['one']);
  await click(checkbox('skill_ids', 'locked'));
  assert.equal(checkbox('skill_ids', 'locked').checked, true);
  await click(fieldset.querySelector('.multi-select-all'));
  assert.equal(fieldset.querySelector('.multi-select-all').disabled, true);
  assert.equal(fieldset.querySelector('.multi-select-clear').disabled, false);
  assert.deepEqual(formData().getAll('skill_ids'), ['one', 'two']);
  assert.match(fieldset.querySelector('[role="status"]').textContent, /已选 2 \/ 可选 2/);
  await click(fieldset.querySelector('.multi-select-clear'));
  assert.deepEqual(formData().getAll('skill_ids'), []);
  assert.equal(checkbox('skill_ids', 'locked').checked, true);
  assert.equal(fieldset.querySelector('.multi-select-clear').disabled, true);
  assert.equal(fieldset.querySelector('.multi-select-all').disabled, false);
  await click(checkbox('skill_ids', 'two'));
  assert.deepEqual(formData().getAll('skill_ids'), ['two']);
  assert.match(fieldset.querySelector('[role="status"]').textContent, /已选 1 \/ 可选 2/);
  assert.equal(submitted, 0, 'bulk action buttons must not submit the containing form');
});

test('MultiSelect honors a disabled ancestor fieldset for all, clear, individual choices and FormData', async () => {
  await render(createElement('form', null, createElement('fieldset', { disabled: true, 'data-parent': true }, createElement(MultiSelect, { label: '知识库', name: 'knowledge_ids', options: smallOptions, selected: ['one'] }))));
  const fieldset = multi('knowledge_ids');
  const all = fieldset.querySelector('.multi-select-all');
  const clear = fieldset.querySelector('.multi-select-clear');
  assert.equal(all.matches(':disabled'), true);
  assert.equal(clear.matches(':disabled'), true);
  await click(all);
  await click(clear);
  await click(checkbox('knowledge_ids', 'two'));
  assert.equal(checkbox('knowledge_ids', 'one').checked, true);
  assert.equal(checkbox('knowledge_ids', 'two').checked, false);
  assert.match(fieldset.querySelector('[role="status"]').textContent, /已选 1 \/ 可选 2/);
  assert.deepEqual(formData().getAll('knowledge_ids'), []);
  document.querySelector('[data-parent]').disabled = false;
  assert.deepEqual(formData().getAll('knowledge_ids'), ['one']);
  await click(all);
  assert.deepEqual(formData().getAll('knowledge_ids'), ['one', 'two']);
});

test('MultiSelect disables empty or wholly unavailable bulk actions without submitting unavailable values', async () => {
  await render(createElement('form', null,
    createElement(MultiSelect, { label: '空技能', name: 'skill_ids', options: [], hint: '请先创建技能' }),
    createElement(MultiSelect, { label: '停用知识库', name: 'knowledge_ids', options: [smallOptions[2]], selected: ['locked'] })));
  for (const name of ['skill_ids', 'knowledge_ids']) {
    assert.equal(multi(name).querySelector('.multi-select-all').disabled, true);
    assert.equal(multi(name).querySelector('.multi-select-clear').disabled, true);
    assert.deepEqual(formData().getAll(name), []);
    assert.match(multi(name).querySelector('[role="status"]').textContent, /已选 0 \/ 可选 0/);
  }
  assert.match(multi('skill_ids').textContent, /请先创建技能/);
  assert.equal(checkbox('knowledge_ids', 'locked').checked, true);
});

test('MultiSelect independently selects and clears 100 skills and 50 knowledge bases through native FormData', async () => {
  const skills = Array.from({ length: 100 }, (_, index) => ({ id: `skill-${index}`, name: `技能 ${index + 1}` }));
  const knowledge = Array.from({ length: 50 }, (_, index) => ({ id: `knowledge-${index}`, name: `知识库 ${index + 1}` }));
  await render(createElement('form', null,
    createElement(MultiSelect, { label: '技能', name: 'skill_ids', options: skills }),
    createElement(MultiSelect, { label: '知识库', name: 'knowledge_ids', options: knowledge })));
  assert.equal(multi('skill_ids').querySelectorAll('input[type="checkbox"]').length, 100);
  assert.equal(multi('knowledge_ids').querySelectorAll('input[type="checkbox"]').length, 50);
  await click(multi('skill_ids').querySelector('.multi-select-all'));
  assert.deepEqual(formData().getAll('skill_ids'), skills.map(item => item.id));
  assert.deepEqual(formData().getAll('knowledge_ids'), []);
  await click(multi('knowledge_ids').querySelector('.multi-select-all'));
  assert.deepEqual(formData().getAll('knowledge_ids'), knowledge.map(item => item.id));
  assert.match(multi('skill_ids').querySelector('[role="status"]').textContent, /已选 100 \/ 可选 100/);
  assert.match(multi('knowledge_ids').querySelector('[role="status"]').textContent, /已选 50 \/ 可选 50/);
  await click(checkbox('skill_ids', 'skill-49'));
  assert.equal(formData().getAll('skill_ids').length, 99);
  assert.equal(formData().getAll('knowledge_ids').length, 50);
  await click(multi('skill_ids').querySelector('.multi-select-all'));
  assert.deepEqual(formData().getAll('skill_ids'), skills.map(item => item.id));
  await click(multi('knowledge_ids').querySelector('.multi-select-clear'));
  assert.deepEqual(formData().getAll('knowledge_ids'), []);
  assert.equal(formData().getAll('skill_ids').length, 100);
  await click(multi('skill_ids').querySelector('.multi-select-clear'));
  assert.deepEqual([...formData().entries()], []);
});

for (const [index, [kind, fixture]] of Object.entries(importFixtures).entries()) {
  test(`${kind} import rejects malformed JSON, invalid item shapes and out-of-range counts before any request`, async () => {
    await openImport(kind);
    const invalidInputs = [
      ['{', /JSON 格式有误/],
      ['', /JSON 格式有误/],
      ['null', /1–200/],
      ['42', /1–200/],
      ['{}', /1–200/],
      ['{"items":{}}', /1–200/],
      ['[]', /1–200/],
      ['{"items":[]}', /1–200/],
      ['[null]', /1–200/],
      ['[[]]', /1–200/],
      ['["not an object"]', /1–200/],
      [JSON.stringify(Array.from({ length: 201 }, () => fixture.item)), /1–200/],
    ];
    for (const [text, expected] of invalidInputs) {
      await fillImport(text);
      await submitImport();
      assert.match(document.querySelector('[role="alert"]').textContent, expected, `${kind}: ${text.slice(0, 60)}`);
      assert.equal(document.querySelector('textarea[name="json"]').value, text, 'invalid input is kept for correction');
      assert.equal(document.querySelector('button[type="submit"]').disabled, false);
      assert.equal(requests.length, 0);
      assert.equal(changeEvents, 0);
      assert.deepEqual(notices, []);
    }
  });

  test(`${kind} import makes exactly one POST to its resource path and treats follow-up warnings as success`, async () => {
    const warning = `${fixture.label}导入后的同步提醒`;
    apiResult = { ok: true, count: 1, warnings: [warning] };
    await openImport(kind);
    const sample = JSON.parse(document.querySelector('textarea[name="json"]').placeholder);
    assert.equal(sample.length, 1);
    if (kind === 'agents' || kind === 'schedules') assert.equal(sample[0].control_level, 'observe');
    if (kind === 'schedules') assert.equal(sample[0].enabled, false);
    if (kind === 'servers' || kind === 'providers') assert.match(document.querySelector('[role="dialog"]').textContent, /占位值/);
    const items = [fixture.item];
    await fillImport(JSON.stringify(index % 2 ? { items } : items));
    await submitImport();
    const expectedItem = kind === 'schedules' ? { enabled: false, ...fixture.item, control_level: 'observe' } : kind === 'agents' ? { ...fixture.item, control_level: 'observe' } : fixture.item;
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0], { url: `/api/${kind}/import`, method: 'POST', body: { items: [expectedItem] }, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } });
    assert.equal(changeEvents, 1);
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(document.querySelector('[role="alert"]'), null);
    assert.equal(notices.length, 2);
    assert.equal(notices[0].message, `已成功导入 1 个${fixture.label}，仅当前账号可见。`);
    assert.equal(notices[1].message, `资源已成功导入，无需重复提交。${warning}`);
    assert.equal(notices[1].tone, 'info');
    assert.ok(notices.every(notice => notice.tone !== 'error'));
  });
}

for (const kind of ['agents', 'schedules']) {
  test(`${kind} import blocks every ungranted or malformed control level without partially submitting the batch`, async () => {
    await openImport(kind);
    const item = importFixtures[kind].item;
    for (const control_level of ['approve', 'autonomous', 'unknown', '', null, 1, [], {}]) {
      const text = JSON.stringify([{ ...item, control_level: 'observe' }, { ...item, name: '未授权资源', control_level }]);
      await fillImport(text);
      await submitImport();
      assert.match(document.querySelector('[role="alert"]').textContent, /当前账号获准的控制模式/);
      assert.equal(document.querySelector('textarea[name="json"]').value, text);
      assert.equal(requests.length, 0);
      assert.equal(changeEvents, 0);
      assert.deepEqual(notices, []);
    }
  });

  test(`${kind} import defaults only to the first granted mode when observe is unavailable`, async () => {
    globalThis.__controlGrantsAuth.user.allowed_control_levels = ['autonomous', 'approve'];
    await openImport(kind);
    assert.equal(JSON.parse(document.querySelector('textarea[name="json"]').placeholder)[0].control_level, 'approve');
    await fillImport(JSON.stringify([importFixtures[kind].item]));
    await submitImport();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].body.items[0].control_level, 'approve');
    if (kind === 'schedules') assert.equal(requests[0].body.items[0].enabled, false);
    assert.equal(document.querySelector('[role="dialog"]'), null);
  });

  test(`${kind} import cannot submit an already-open dialog after its grant is revoked`, async () => {
    await openImport(kind);
    await fillImport(JSON.stringify([{ ...importFixtures[kind].item, control_level: 'observe' }]));
    globalThis.__controlGrantsAuth.user = { ...baseUser, allowed_control_levels: [] };
    await renderImport(kind);
    assert.equal(document.querySelector(`[data-user-import-trigger="${kind}"]`).disabled, true);
    await submitImport();
    assert.match(document.querySelector('[role="alert"]').textContent, /当前账号获准的控制模式/);
    assert.equal(requests.length, 0);
    assert.equal(changeEvents, 0);
  });
}

test('import triggers require a user and control-bearing resource triggers fail closed for empty or corrupt grants', async () => {
  globalThis.__controlGrantsAuth.user = null;
  for (const kind of Object.keys(importFixtures)) {
    await render(createElement(UserResourceImportButton, { key: kind, kind, label: importFixtures[kind].label }));
    const trigger = document.querySelector(`[data-user-import-trigger="${kind}"]`);
    assert.equal(trigger.disabled, true);
    await click(trigger);
    assert.equal(document.querySelector('[role="dialog"]'), null);
  }
  for (const grants of [[], null, 'observe']) {
    globalThis.__controlGrantsAuth.user = { ...baseUser, allowed_control_levels: grants };
    for (const kind of ['agents', 'schedules']) {
      await render(createElement(UserResourceImportButton, { key: `${kind}-${JSON.stringify(grants)}`, kind, label: importFixtures[kind].label }));
      const trigger = document.querySelector(`[data-user-import-trigger="${kind}"]`);
      assert.equal(trigger.disabled, true);
      assert.match(trigger.title, /没有可创建资源的控制模式/);
      await click(trigger);
      assert.equal(document.querySelector('[role="dialog"]'), null);
    }
  }
  assert.equal(requests.length, 0);
});

test('import suppresses duplicate submit events while its single request is pending', async () => {
  requestGate = deferred();
  await openImport('skills');
  await fillImport(JSON.stringify([importFixtures.skills.item]));
  const form = document.querySelector('[role="dialog"] form');
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  assert.equal(requests.length, 1);
  assert.equal(document.querySelector('button[type="submit"]').disabled, true);
  assert.equal(changeEvents, 0);
  await act(async () => { requestGate.resolve(); await requestGate.promise; });
  assert.equal(requests.length, 1);
  assert.equal(changeEvents, 1);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(notices.length, 1);
});

test('failed import requests retain input and permit one explicit corrected retry', async () => {
  responseStatus = 422; apiResult = { detail: '关联技能不存在' };
  await openImport('projects');
  const text = JSON.stringify([importFixtures.projects.item]);
  await fillImport(text);
  await submitImport();
  assert.equal(requests.length, 1);
  assert.match(document.querySelector('[role="alert"]').textContent, /关联技能不存在/);
  assert.equal(document.querySelector('textarea[name="json"]').value, text);
  assert.equal(document.querySelector('button[type="submit"]').disabled, false);
  assert.equal(changeEvents, 0);
  assert.deepEqual(notices, []);
  responseStatus = 200; apiResult = { ok: true, count: 1 };
  await submitImport();
  assert.equal(requests.length, 2);
  assert.equal(changeEvents, 1);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(notices.length, 1);
});

test('import accepts the 200-object upper boundary as a single batch', async () => {
  apiResult = { ok: true, count: 200 };
  await openImport('skills');
  const items = Array.from({ length: 200 }, (_, index) => ({ ...importFixtures.skills.item, name: `技能 ${index + 1}` }));
  await fillImport(JSON.stringify({ items }));
  await submitImport();
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].body, { items });
  assert.equal(changeEvents, 1);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.match(notices[0].message, /成功导入 200 个技能/);
});

test('observe-only schedule import rejects an enabled schedule linked to an approve agent before any HTTP request', async () => {
  await openImport('schedules');
  const item = { ...importFixtures.schedules.item, agent_id: 'agent-approve', control_level: 'observe', enabled: true };
  const text = JSON.stringify([item]);
  await fillImport(text);
  await submitImport();
  assert.match(document.querySelector('[role="alert"]').textContent, /定时任务关联了不可执行或控制等级未获授权的智能体/);
  assert.equal(document.querySelector('textarea[name="json"]').value, text);
  assert.equal(document.querySelector('button[type="submit"]').disabled, false);
  assert.equal(requests.length, 0);
  assert.equal(changeEvents, 0);
  assert.deepEqual(notices, []);
});

test('schedule import rejects unknown and remote linked agents without submitting any part of the batch', async () => {
  await openImport('schedules');
  for (const agent_id of ['agent-missing', 'agent-remote']) {
    const items = [
      { ...importFixtures.schedules.item, agent_id: 'agent-observe', control_level: 'observe', enabled: true },
      { ...importFixtures.schedules.item, name: '不可执行关联', agent_id, control_level: 'observe', enabled: true },
    ];
    const text = JSON.stringify(items);
    await fillImport(text);
    await submitImport();
    assert.match(document.querySelector('[role="alert"]').textContent, /定时任务关联了不可执行或控制等级未获授权的智能体/);
    assert.equal(document.querySelector('textarea[name="json"]').value, text);
    assert.equal(requests.length, 0);
    assert.equal(changeEvents, 0);
    assert.deepEqual(notices, []);
  }
});

test('schedule import permits one explicit retry after the linked agent control level is granted', async () => {
  await openImport('schedules');
  const item = { ...importFixtures.schedules.item, agent_id: 'agent-approve', control_level: 'observe', enabled: true };
  await fillImport(JSON.stringify([item]));
  await submitImport();
  assert.match(document.querySelector('[role="alert"]').textContent, /控制等级未获授权的智能体/);
  assert.equal(requests.length, 0);
  globalThis.__controlGrantsAuth.user = { ...baseUser, allowed_control_levels: ['observe', 'approve'] };
  await renderImport('schedules');
  await submitImport();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/schedules/import');
  assert.equal(requests[0].method, 'POST');
  assert.deepEqual(requests[0].body, { items: [item] });
  assert.equal(changeEvents, 1);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(notices.length, 1);
});

test('schedule import refuses linked agents while their catalog is still loading', async () => {
  globalThis.__controlGrantsCatalog.loading = true;
  await openImport('schedules');
  const item = { ...importFixtures.schedules.item, agent_id: 'agent-observe', control_level: 'observe', enabled: true };
  const text = JSON.stringify([item]);
  await fillImport(text);
  await submitImport();
  assert.match(document.querySelector('[role="alert"]').textContent, /智能体目录尚未加载完成/);
  assert.equal(document.querySelector('textarea[name="json"]').value, text);
  assert.equal(document.querySelector('button[type="submit"]').disabled, false);
  assert.equal(requests.length, 0);
  assert.equal(changeEvents, 0);
  assert.deepEqual(notices, []);
});

test('schedule import preserves explicit enabled true for an authorized observe schedule and local agent', async () => {
  await openImport('schedules');
  const item = { ...importFixtures.schedules.item, agent_id: 'agent-observe', control_level: 'observe', enabled: true };
  await fillImport(JSON.stringify([item]));
  await submitImport();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/schedules/import');
  assert.equal(requests[0].method, 'POST');
  assert.deepEqual(requests[0].body, { items: [item] });
  assert.equal(requests[0].body.items[0].enabled, true);
  assert.equal(changeEvents, 1);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(notices.length, 1);
  assert.match(notices[0].message, /已成功导入 1 个定时任务/);
});
