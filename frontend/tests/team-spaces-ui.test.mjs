import { after, afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-team-spaces-tests');
await mkdir(cache, { recursive: true });
await build({
  stdin: { contents: "export * from './src/lib/spaceAccess'; export { AdminUsersPage } from './src/pages/AdminPages'; export { SpacePage } from './src/pages/KnowledgePages'; export { Layout } from './src/components/Layout'; export { TeamSpacesPage, AdminTeamSpacesPage } from './src/pages/TeamSpacesPage';", resolveDir: resolve('.'), loader: 'ts' },
  outfile: `${cache}/team-spaces-ui.mjs`, bundle: true, packages: 'external', platform: 'node', target: 'node22', jsx: 'automatic', format: 'esm',
  loader: { '.css': 'text' }, logOverride: { 'ignored-bare-import': 'silent' },
  plugins: [{ name: 'team-spaces-fixture', setup(builder) {
    builder.onLoad({ filter: /\/context\/AuthContext\.tsx$/ }, () => ({ contents: 'export function useAuth() { return globalThis.__teamSpacesAuth; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/ToastContext\.tsx$/ }, () => ({ contents: 'export function useToast() { return globalThis.__teamSpacesNotify; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/CatalogContext\.tsx$/ }, () => ({ contents: 'export function useCatalog() { return { servers: [], providers: [], agents: [], projects: [], knowledge: [], skills: [], loading: false, error: "" }; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/ExecutionContext\.tsx$/ }, () => ({ contents: 'export function useExecutions() { return { runs: {}, loading: false, error: "", refresh: async () => {} }; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/BrandingContext\.tsx$/ }, () => ({ contents: 'export const defaultBranding = { name: "EarthAI", subtitle: "团队测试", tagline: "测试工作空间", title_color: "#123", subtitle_color: "#456" }; export function useBranding() { return defaultBranding; }', loader: 'js' }));
  } }],
});
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/space', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, { window, document: window.document, Node: window.Node, HTMLElement: window.HTMLElement, Event: window.Event, MouseEvent: window.MouseEvent, KeyboardEvent: window.KeyboardEvent, FormData: window.FormData, File: window.File, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const { enabledSpaceModules, canUseSpace, AdminUsersPage, SpacePage, Layout, TeamSpacesPage, AdminTeamSpacesPage } = await import(pathToFileURL(`${cache}/team-spaces-ui.mjs`).href);
const appSource = await readFile('src/App.tsx', 'utf8');
const originalFetch = globalThis.fetch;
const at = '2026-10-29T08:00:00.000Z';
const baseUser = { id: 'space-user', name: '空间测试用户', email: 'spaces@example.com', avatar: 'EA', theme: 'light', role: 'user', control_level: 'observe', allowed_control_levels: ['observe'], space_modules: ['personal'] };
const adminUser = { ...baseUser, id: 'space-admin', name: '测试管理员', email: 'admin@example.com', role: 'admin', space_modules: [] };
let root;
let requests;
let users;
let space;
let files;
let members;
let renderId = 0;

function mockAuth(user = baseUser) {
  globalThis.__teamSpacesAuth = { user: structuredClone(user), loading: false, retry: async () => undefined };
}
function response(data) { return { ok: true, status: 200, json: async () => structuredClone(data) }; }
function mockFetch(input, options = {}) {
  const url = String(input);
  const method = options.method || 'GET';
  const body = options.body instanceof FormData ? options.body : options.body === undefined ? undefined : JSON.parse(options.body);
  requests.push({ url, method, body, credentials: options.credentials });
  assert.equal(options.credentials, 'same-origin');
  if (url === '/api/files' && method === 'GET') return Promise.resolve(response([]));
  if (url === '/api/admin/users/batch' && method === 'POST') {
    for (const item of users.filter(item => body.ids.includes(item.id))) Object.assign(item, body.changes);
    return Promise.resolve(response({ ok: true }));
  }
  if (url === '/api/admin/users') {
    if (method === 'POST') { const item = { id: 'created-user', ...body }; users.push(item); return Promise.resolve(response(item)); }
    assert.equal(method, 'GET');
    return Promise.resolve(response(users));
  }
  const account = url.match(/^\/api\/admin\/users\/([^/]+)$/);
  if (account && method === 'PATCH') {
    const item = users.find(item => item.id === account[1]);
    assert.ok(item, 'edited account exists'); Object.assign(item, body);
    return Promise.resolve(response(item));
  }
  const team = url.match(/^\/api\/(?:admin\/)?team-spaces(?:\/([^/?]+))?(?:\/(files|members))?$/);
  if (team && method === 'GET') return Promise.resolve(response(!team[1] ? [space] : team[2] === 'files' ? files : team[2] === 'members' ? members : space));
  throw new Error(`Unexpected API ${method} ${url}`);
}

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  root = createRoot(document.getElementById('root'));
  requests = [];
  users = [{ ...baseUser, id: 'closed-user', email: 'closed@example.com', name: '已关闭空间账户', space_modules: [] }];
  space = { id: 'space-one', name: '协作资料', description: '团队共享内容', owner_id: 'owner-user', owner_name: '空间所有者', role: 'viewer', archived: false, member_count: 5, file_count: 1, total_size: 12, created_at: at, updated_at: at };
  files = [{ id: 'file-one', space_id: space.id, name: '协作手册.txt', size: 12, mime: 'text/plain', uploader_id: 'owner-user', uploader_name: '空间所有者', created_at: at, updated_at: at }];
  members = ['owner', 'manager', 'editor', 'viewer'].map(role => ({ user_id: `${role}-user`, email: `${role}@example.com`, name: `${role} 成员`, role, team_module_enabled: true, created_at: at, updated_at: at }));
  members.push({ ...members[1], user_id: 'other-manager', email: 'other-manager@example.com', name: '另一管理者' });
  mockAuth();
  globalThis.__teamSpacesNotify = () => undefined;
  globalThis.fetch = mockFetch;
});
afterEach(async () => {
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  delete globalThis.__teamSpacesAuth;
  delete globalThis.__teamSpacesNotify;
});
after(() => dom.window.close());
async function render(node) { await act(async () => root.render(createElement('div', { key: ++renderId }, node))); }
async function click(node) {
  assert.ok(node, 'click target exists');
  await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
}
function button(text, scope = document) { return [...scope.querySelectorAll('button')].find(node => node.textContent.trim() === text); }
function form() { const node = document.querySelector('[role="dialog"] form'); assert.ok(node, 'dialog contains a form'); return node; }
function spaceChecks() { return [...form().querySelectorAll('input[name="space_modules"]')]; }
async function submit() { await act(async () => { form().dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); }); }
async function choose(label, option) {
  await click(document.querySelector(`[role="combobox"][aria-label="${label}"]`));
  await click(document.querySelector(`[role="option"][aria-label="${option}"]`));
}
function writes() { return requests.filter(request => request.method !== 'GET'); }
function assertTeamDialog() {
  const dialog = document.querySelector('[role="dialog"]'); assert.ok(dialog);
  assert.doesNotMatch(dialog.textContent, /数据仅对当前账户可见|当前账户私有/);
  assert.match(dialog.querySelector('.modal-footer').textContent, /团队成员/);
}

test('space access defaults legacy and new accounts to personal, preserves empty grants and fails closed for malformed grants and administrators', () => {
  const { space_modules, ...legacy } = baseUser;
  for (const user of [legacy, baseUser]) {
    assert.deepEqual(enabledSpaceModules(user), ['personal']);
    assert.equal(canUseSpace(user, 'personal'), true);
    assert.equal(canUseSpace(user, 'team'), false);
  }
  const both = { ...baseUser, space_modules: ['team', 'personal'] };
  const before = JSON.stringify(both);
  assert.deepEqual(enabledSpaceModules(both), ['personal', 'team']);
  enabledSpaceModules(both).pop();
  assert.equal(JSON.stringify(both), before);
  for (const module of ['personal', 'team']) assert.equal(canUseSpace(both, module), true);
  for (const grants of [[], null, false, 'personal', {}, ['unknown'], ['personal', 'unknown'], ['personal', 'personal'], ['team', null], [['team']]]) {
    const user = { ...baseUser, space_modules: grants };
    assert.deepEqual(enabledSpaceModules(user), [], JSON.stringify(grants));
    for (const module of ['personal', 'team']) assert.equal(canUseSpace(user, module), false, JSON.stringify(grants));
  }
  for (const user of [null, undefined, { ...both, disabled: true }, { ...both, must_change_password: true }, { ...both, role: 'admin' }, { ...legacy, role: 'admin' }]) {
    for (const module of ['personal', 'team']) assert.equal(canUseSpace(user, module), false);
  }
  assert.deepEqual(enabledSpaceModules(null), []);
  assert.equal(canUseSpace(both, 'unknown'), false);
});

test('account forms create personal-only users, retain explicit empty edits and show legacy personal grants without re-enabling closed modules', async () => {
  mockAuth(adminUser);
  const { space_modules, ...legacy } = baseUser;
  users.push({ ...legacy, id: 'legacy-user', email: 'legacy@example.com' });
  await render(createElement(AdminUsersPage));
  await click(button('创建账户'));
  assert.deepEqual(spaceChecks().map(input => [input.value, input.checked]), [['personal', true], ['team', false]]);
  form().elements.namedItem('email').value = 'new@example.com';
  form().elements.namedItem('name').value = '新空间账户';
  form().elements.namedItem('password').value = 'test-password-only';
  await submit();
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.deepEqual(writes()[0].body.space_modules, ['personal']);
  assert.deepEqual(writes()[0].body.allowed_control_levels, ['observe']);
  const closedRow = [...document.querySelectorAll('.ea-admin-user-row')].find(row => row.textContent.includes('closed@example.com'));
  assert.equal(closedRow.querySelector('[data-space-module="personal"]'), null);
  await click(button('编辑', closedRow));
  assert.deepEqual(spaceChecks().map(input => input.checked), [false, false]);
  await submit();
  assert.equal(writes()[1].url, '/api/admin/users/closed-user');
  assert.equal(writes()[1].method, 'PATCH');
  assert.deepEqual(writes()[1].body.space_modules, []);
  const legacyRow = [...document.querySelectorAll('.ea-admin-user-row')].find(row => row.textContent.includes('legacy@example.com'));
  await click(button('编辑', legacyRow));
  assert.deepEqual(spaceChecks().map(input => input.checked), [true, false]);
  await click(document.querySelector('[aria-label="关闭对话框"]'));
  assert.equal(writes().length, 2);
});

test('batch space changes are opt-in, independent of control grants, and explicitly support disabling all spaces', async () => {
  mockAuth(adminUser);
  users[0].space_modules = ['personal', 'team'];
  await render(createElement(AdminUsersPage));
  await click(document.querySelector('input[aria-label="选择账户 closed@example.com"]'));
  await click([...document.querySelectorAll('button')].find(node => node.textContent.includes('批量') && !node.textContent.includes('删除')));
  assert.equal(form().elements.namedItem('apply_space_modules').checked, false);
  assert.equal(form().elements.namedItem('apply_control_levels').checked, false);
  assert.ok(spaceChecks().every(input => input.matches(':disabled')));
  await choose('统一账户状态', '全部启用登录');
  await submit();
  assert.deepEqual(writes()[0].body, { ids: ['closed-user'], action: 'update', changes: { disabled: false } });
  assert.deepEqual(users[0].space_modules, ['personal', 'team']);
  await click(document.querySelector('input[aria-label="选择账户 closed@example.com"]'));
  await click([...document.querySelectorAll('button')].find(node => node.textContent.includes('批量') && !node.textContent.includes('删除')));
  assert.equal(form().elements.namedItem('apply_space_modules').checked, false);
  await click(form().elements.namedItem('apply_space_modules'));
  assert.ok(spaceChecks().every(input => !input.matches(':disabled')));
  assert.equal(form().elements.namedItem('apply_control_levels').checked, false);
  for (const input of spaceChecks().filter(input => input.checked)) await click(input);
  await submit();
  assert.deepEqual(writes()[1].body, { ids: ['closed-user'], action: 'update', changes: { space_modules: [] } });
  assert.deepEqual(users[0].space_modules, []);
  assert.deepEqual(users[0].allowed_control_levels, ['observe']);
  assert.equal(document.querySelector('[role="dialog"]'), null);
});

test('personal space rejects disabled grants before fetching files and navigation hides unauthorized space links', async () => {
  const { space_modules, ...legacy } = baseUser;
  for (const [user, personal, team] of [[legacy, true, false], [baseUser, true, false], [{ ...baseUser, space_modules: ['team'] }, false, true], [{ ...baseUser, space_modules: [] }, false, false], [{ ...baseUser, space_modules: ['personal', 'bad'] }, false, false], [adminUser, false, false]]) {
    mockAuth(user); requests = [];
    await render(createElement(MemoryRouter, { initialEntries: ['/space'] }, createElement(Routes, null, createElement(Route, { element: createElement(Layout) }, createElement(Route, { path: '/space', element: createElement(SpacePage) })))));
    assert.equal(Boolean(document.querySelector('nav a[href="/space"]')), personal);
    assert.equal(Boolean(document.querySelector('nav a[href="/team-spaces"]')), team);
    assert.equal(requests.filter(request => request.url === '/api/files').length, personal ? 1 : 0);
    if (!personal) assert.match(document.querySelector('main').textContent, /个人空间暂未开启/);
  }
  assert.match(appSource, /if\s*\(!canUseSpace\(user, module\)\)/);
  assert.match(appSource, /path="space"\s+element=\{<SpaceRoute module="personal"><SpacePage/);
  assert.match(appSource, /path="team-spaces"\s+element=\{<SpaceRoute module="team"><TeamSpacesPage/);
  assert.match(appSource, /path="admin\/team-spaces"\s+element=\{<AdminTeamSpacesPage/);
});

test('team role matrix restricts file and member actions, keeps manager role choices bounded and uses shared-scope dialog copy', async () => {
  for (const role of ['owner', 'manager', 'editor', 'viewer', 'admin']) {
    space.role = role;
    mockAuth(role === 'admin' ? adminUser : { ...baseUser, id: `${role}-user`, space_modules: ['team'] });
    requests = [];
    await render(createElement(role === 'admin' ? AdminTeamSpacesPage : TeamSpacesPage));
    const owner = role === 'owner' || role === 'admin';
    const canWrite = role !== 'viewer';
    const canManage = owner || role === 'manager';
    const action = name => document.querySelector(`[data-team-action="${name}"]`);
    assert.equal(document.querySelector('[data-team-disabled]'), null, role);
    assert.ok(document.querySelector(`[data-team-role="${role}"]`), role);
    assert.equal(Boolean(action('archive')), owner, role);
    assert.equal(Boolean(action('transfer')), owner, role);
    assert.equal(Boolean(action('edit-space')), canManage, role);
    if (role === 'manager') {
      await click(action('edit-space'));
      assert.equal(form().elements.namedItem('name').value, space.name);
      assertTeamDialog();
      await click(document.querySelector('[aria-label="关闭对话框"]'));
    }
    assert.equal(Boolean(action('upload')), canWrite, role);
    assert.equal(document.querySelector('input[aria-label="上传团队文件"]').disabled, !canWrite, role);
    for (const label of ['重命名', '替换', '永久删除']) assert.equal(Boolean(document.querySelector(`[aria-label="${label} 协作手册.txt"]`)), canWrite, `${role}: ${label}`);
    assert.equal(document.querySelector('[aria-label="下载 协作手册.txt"]').disabled, false, role);
    if (role === 'editor') {
      await click(document.querySelector('[aria-label="重命名 协作手册.txt"]'));
      assert.equal(form().elements.namedItem('name').value, '协作手册.txt');
      assertTeamDialog();
      await click(document.querySelector('[aria-label="关闭对话框"]'));
    }
    await click(document.querySelector('[role="tab"][id="team-members-space-one"]'));
    assert.equal(Boolean(action('add-member')), canManage, role);
    for (const member of members) {
      const row = document.querySelector(`[data-team-member-id="${member.user_id}"]`); assert.ok(row, role);
      const canEdit = canManage && member.role !== 'owner' && member.user_id !== globalThis.__teamSpacesAuth.user.id && (owner || ['editor', 'viewer'].includes(member.role));
      assert.equal(row.querySelectorAll('button').length, canEdit ? 2 : 0, `${role}: ${member.user_id}`);
    }
    if (canManage) {
      await click(action('add-member'));
      assertTeamDialog();
      await click(document.querySelector('[role="combobox"][aria-label="成员角色"]'));
      assert.deepEqual([...document.querySelectorAll('[role="option"]')].map(node => node.dataset.value || node.getAttribute('aria-label')), owner ? ['浏览者', '编辑者', '管理者'] : ['浏览者', '编辑者']);
      await click(document.querySelector('[role="option"][aria-label="浏览者"]'));
      await click(document.querySelector('[aria-label="关闭对话框"]'));
    }
    assert.equal(writes().length, 0, 'opening role-limited controls does not mutate data');
    assert.ok(requests.some(request => request.url === `/api/${role === 'admin' ? 'admin/' : ''}team-spaces/space-one/files`), role);
    assert.equal(requests.some(request => request.url === '/api/files'), false, 'team pages never read personal files');
  }
  space.role = 'owner'; space.archived = true;
  requests = [];
  mockAuth({ ...baseUser, id: 'owner-user', space_modules: ['team'] });
  await render(createElement(TeamSpacesPage));
  assert.ok(document.querySelector('[data-team-action="restore"]'));
  assert.equal(document.querySelector('[data-team-action="transfer"]'), null);
  assert.equal(document.querySelector('[data-team-action="edit-space"]'), null);
  assert.equal(document.querySelector('[data-team-action="leave"]'), null);
  assert.ok(document.querySelector('[data-team-archived]'));
  assert.equal(document.querySelector('[aria-label="下载 协作手册.txt"]'), null);
  assert.equal(requests.some(request => request.url.endsWith('/team-spaces/space-one/files') || request.url.endsWith('/admin/team-spaces/space-one/files')), false);
  assert.equal(document.querySelector('input[aria-label="上传团队文件"]').disabled, true);
});

test('team workbench refuses malformed, suspended and password-change accounts before loading shared data', async () => {
  for (const user of [
    { ...baseUser, space_modules: ['team', 'team'] },
    { ...baseUser, space_modules: ['team', 'unknown'] },
    { ...baseUser, space_modules: ['team'], must_change_password: true },
    { ...baseUser, space_modules: ['team'], disabled: true },
    { ...adminUser, must_change_password: true },
  ]) {
    mockAuth(user); requests = [];
    await render(createElement(user.role === 'admin' ? AdminTeamSpacesPage : TeamSpacesPage));
    assert.ok(document.querySelector('[data-team-disabled]'));
    assert.equal(requests.length, 0);
    assert.equal(document.querySelector('[data-team-action="create-space"]'), null);
  }
});

test('a fresh team 403 clears detail data and asks auth to refresh module availability', async () => {
  mockAuth({ ...baseUser, space_modules: ['team'] });
  const events = [];
  const changed = () => events.push('refresh');
  window.addEventListener('earthai:permissions-refresh', changed);
  globalThis.fetch = (input, options) => String(input) === '/api/team-spaces/space-one'
    ? Promise.resolve({ ok: false, status: 403, json: async () => ({ detail: '管理员未启用此空间，请联系管理员' }) })
    : mockFetch(input, options);
  try {
    await render(createElement(TeamSpacesPage));
    assert.ok(events.length > 0);
    assert.ok(document.querySelector('[data-team-access-error]'));
    assert.equal(document.querySelector('[data-team-file-id]'), null);
    assert.equal(document.querySelector('[data-team-action="upload"]'), null);
  } finally { window.removeEventListener('earthai:permissions-refresh', changed); }
});
