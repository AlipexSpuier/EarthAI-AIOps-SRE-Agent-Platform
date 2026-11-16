const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { setTimeout: delay } = require('node:timers/promises');

const root = path.resolve(__dirname, '..');
const reportPath = path.join(root, 'docs/team-spaces-verification.json');
const modulePath = process.env.PLAYWRIGHT_MODULE || path.resolve(root, '../.tools/browser-check/node_modules/playwright');
const { chromium } = require(modulePath);
const password = 'Team-Browser-Isolated-2026!';
const sharedBytes = Buffer.from('团队保留文件：只在隔离测试中读写，不调用模型或基础设施。\n');
const personalBytes = Buffer.from('个人文件保留原 ID 与 bytes；与团队文件隔离。\n');
const report = {
  ok: false, at: new Date().toISOString(), checks: [], layouts: [], negativeAssertions: [],
  console: [], pageErrors: [], externalRequests: [], unexpectedHttp: [], requestFailures: [],
  expectedHttp: [], expectedConsole: [], expectedCancellations: [], browserWrites: [],
  backendBlockedOperations: [], scope: 'real headless Chromium; temporary local data; dedicated 0.0.0.0 server; no paid model, production, SSH or NAS access',
};
let stage = 'initialization', server, browser, dataDir, base, origin, serverOutput = '', cleaned = false;
const contexts = [];
const expected = [];
const browserRequests = [];
const responseStatuses = new WeakMap();
const navigating = new Set();
const closing = new Set();
const pass = text => { report.checks.push(text); console.log('PASS', text); };
const expectHttp = (actor, method, endpoint, status, reason, optional = false) => {
  const rule = { actor, method, endpoint, status, reason, hits: 0, optional };
  expected.push(rule); return rule;
};
const endpointOf = url => { const value = new URL(url); return value.pathname.replace(/^\/api/, '') + value.search; };

async function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const [name] of contexts) closing.add(name);
  if (browser) await browser.close().catch(() => {});
  if (server && server.exitCode === null && server.signalCode === null) {
    const exited = new Promise(resolve => server.once('exit', resolve));
    process.kill(-server.pid, 'SIGTERM');
    let timer;
    await Promise.race([exited, new Promise(resolve => { timer = setTimeout(() => {
      try { process.kill(-server.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
      resolve();
    }, 5000); })]);
    clearTimeout(timer);
    await exited;
  }
  report.cleanup = { browserClosed: !browser || !browser.isConnected(), serverStopped: !server || server.exitCode !== null || server.signalCode !== null };
  if (dataDir) { fs.rmSync(dataDir, { recursive: true, force: true }); report.cleanup.temporaryDataRemoved = !fs.existsSync(dataDir); }
}
for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {
  void cleanup().then(() => process.exit(128 + (signal === 'SIGINT' ? 2 : 15)));
});

async function startServer() {
  const dist = path.join(root, 'frontend/dist');
  const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
  const asset = html.match(/src="(\/assets\/[^\"]+\.js)"/)[1];
  const bundle = fs.readFileSync(path.join(dist, asset), 'utf8');
  assert(bundle.includes('ea-team-workbench') && bundle.includes('恢复空间'), 'frontend dist does not contain team spaces; build it before running this test');
  report.frontend = { asset, modifiedAt: fs.statSync(path.join(dist, asset)).mtime.toISOString() };
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'earthai-team-browser-'));
  const port = await new Promise((resolve, reject) => {
    const socket = net.createServer(); socket.once('error', reject);
    socket.listen(0, '0.0.0.0', () => { const selected = socket.address().port; socket.close(error => error ? reject(error) : resolve(selected)); });
  });
  base = `http://127.0.0.1:${port}`; origin = base;
  report.isolation = { bind: '0.0.0.0', port, temporaryData: true, backendEgressDenied: true, schedulerDisabled: true };
  const python = `import asyncio, json, socket, sys\n\ndef audit(event, args):\n    if event == 'socket.connect' and args[0].family in (socket.AF_INET, socket.AF_INET6):\n        print('E2E_BLOCKED ' + json.dumps({'kind': 'socket.connect', 'target': str(args[1])}), flush=True)\n        raise RuntimeError('isolated browser test forbids backend outbound connections')\nsys.addaudithook(audit)\nfrom backend import engine, text_tools, tools\nasync def blocked(*args, **kwargs):\n    print('E2E_BLOCKED ' + json.dumps({'kind': 'model-or-tool'}), flush=True)\n    raise RuntimeError('isolated browser test forbids model and infrastructure execution')\ndef blocked_sync(*args, **kwargs):\n    print('E2E_BLOCKED ' + json.dumps({'kind': 'infrastructure-test'}), flush=True)\n    raise RuntimeError('isolated browser test forbids infrastructure connections')\nasync def idle_scheduler():\n    await asyncio.Event().wait()\nengine.model_completion = blocked\ntext_tools.complete = blocked\ntools.execute = blocked\ntools.test_server = blocked_sync\nengine.scheduler_loop = idle_scheduler\nimport uvicorn\nuvicorn.run('backend.main:app', host='0.0.0.0', port=${port}, access_log=False, log_level='warning', loop='asyncio')\n`;
  server = spawn(path.join(root, '.venv/bin/python'), ['-c', python], {
    cwd: root, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', EARTHAI_DATA_DIR: dataDir, EARTHAI_STATE_DIR: dataDir,
      EARTHAI_UPLOADS_DIR: path.join(dataDir, 'uploads'), EARTHAI_MASTER_KEY: crypto.randomBytes(32).toString('base64url') + '=',
      EARTHAI_SQLITE_JOURNAL_MODE: 'WAL', EARTHAI_COOKIE_SECURE: 'false', EARTHAI_ALLOW_REGISTRATION: 'true', EARTHAI_ALLOWED_ORIGINS: origin },
  });
  let startupError;
  server.once('error', error => { startupError = error; });
  for (const stream of [server.stdout, server.stderr]) stream.on('data', chunk => { serverOutput += chunk.toString(); });
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (startupError) throw startupError;
    assert(server.exitCode === null && server.signalCode === null, `isolated uvicorn stopped: ${serverOutput}`);
    try {
      const response = await fetch(base + '/api/health', { signal: AbortSignal.timeout(2500) });
      if (response.ok) { delete report.lastHealth; return; }
      report.lastHealth = { status: response.status(), body: await response.text() };
    } catch (error) { report.lastHealth = { message: error.message, code: error.cause?.code }; }
    await delay(200);
  }
  throw new Error(`isolated uvicorn startup timed out: ${serverOutput}`);
}

async function newActor(name) {
  const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 900 }, serviceWorkers: 'block', acceptDownloads: true });
  contexts.push([name, context]);
  context.on('page', page => {
    page.on('pageerror', error => report.pageErrors.push({ actor: name, message: error.message }));
    page.on('console', message => report.console.push({ actor: name, type: message.type(), text: message.text(), ...message.location() }));
  });
  context.on('request', request => {
    const url = new URL(request.url());
    if (['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol) && url.origin !== origin) return;
    const value = { actor: name, method: request.method(), endpoint: endpointOf(request.url()), isApi: url.pathname.startsWith('/api/'), at: Date.now() };
    browserRequests.push(value);
    if (url.pathname.startsWith('/api/team-spaces') && !['GET', 'HEAD', 'OPTIONS'].includes(value.method)) report.browserWrites.push(value);
  });
  context.on('response', response => {
    responseStatuses.set(response.request(), response.status());
    if (response.status() < 400) return;
    const value = { actor: name, method: response.request().method(), endpoint: endpointOf(response.url()), status: response.status() };
    const rule = expected.find(item => item.actor === name && item.method === value.method && item.endpoint === value.endpoint && item.status === value.status);
    if (rule) { rule.hits += 1; report.expectedHttp.push({ ...value, reason: rule.reason }); }
    else report.unexpectedHttp.push(value);
  });
  context.on('requestfailed', request => {
    const value = { actor: name, method: request.method(), endpoint: endpointOf(request.url()), error: request.failure()?.errorText };
    const completedReplace = value.method === 'PUT' && /\/files\/[^/]+\/content$/.test(value.endpoint) && responseStatuses.get(request) === 200;
    if ((navigating.has(name) || closing.has(name)) && (value.method === 'GET' || completedReplace) && value.error === 'net::ERR_ABORTED') report.expectedCancellations.push({ ...value, reason: completedReplace ? 'successful PUT body not consumed by UI; fixture verified bytes before controlled navigation' : closing.has(name) ? 'controlled context teardown' : 'controlled page navigation' });
    else report.requestFailures.push(value);
  });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['blob:', 'data:', 'about:'].includes(url.protocol) && url.origin !== origin) {
      report.externalRequests.push({ actor: name, url: url.href }); return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage(); page.setDefaultTimeout(15000); page.setDefaultNavigationTimeout(25000);
  return { name, context, page };
}
async function api(actor, method, endpoint, data, options = {}) {
  const response = await actor.context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }), ...options });
  assert(response.ok(), `${actor.name}: ${method} ${endpoint}: ${response.status()} ${await response.text()}`);
  return response.json();
}
async function denied(actor, method, endpoint, status, reason, data, options = {}) {
  const response = await actor.context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }), ...options });
  const body = await response.json(); assert.equal(response.status(), status, `${reason}: ${JSON.stringify(body)}`);
  report.negativeAssertions.push({ actor: actor.name, method, endpoint, status, reason, detail: body.detail });
  return body;
}
const multipart = (name, buffer = sharedBytes) => ({ multipart: { file: { name, mimeType: 'text/plain', buffer } } });
async function bytes(actor, endpoint, expectedBytes) {
  const response = await actor.context.request.get(base + '/api' + endpoint); assert(response.ok(), `${endpoint}: ${response.status()}`);
  const content = await response.body(); assert(content.equals(expectedBytes), `${endpoint}: bytes changed`); return content.length;
}
async function goto(actor, route) {
  navigating.add(actor.name);
  try { await actor.page.goto(base + route, { waitUntil: 'networkidle' }); } finally { navigating.delete(actor.name); }
}
async function detailReady(actor, id) {
  await actor.page.waitForFunction(id_ => {
    const detail = document.querySelector(`[data-team-detail-id="${id_}"]`);
    return detail && detail.getAttribute('aria-busy') === 'false' && detail.querySelector('h2') && !detail.querySelector('[data-team-access-error]');
  }, id);
  return actor.page.locator(`[data-team-detail-id="${id}"]`);
}
async function openSpace(actor, id, admin = false) {
  await goto(actor, admin ? '/admin/team-spaces' : '/team-spaces');
  const card = actor.page.locator(`[data-team-space-id="${id}"]`);
  if (!await card.count()) await actor.page.getByText('包含已归档', { exact: true }).click();
  await card.click(); return detailReady(actor, id);
}
async function choose(page, dialog, name, label) {
  await dialog.getByRole('combobox', { name, exact: true }).click();
  await page.getByRole('option', { name: label, exact: true }).click();
}
async function submit(actor, dialog, label, method, endpoint) {
  const response = actor.page.waitForResponse(value => value.request().method() === method && endpointOf(value.url()) === endpoint);
  await dialog.getByRole('button', { name: label, exact: true }).click();
  const result = await response;
  if (!result.ok()) throw new Error(`${method} ${endpoint}: ${await result.text()}`);
  const body = method === 'PUT' ? null : await result.json(); await dialog.waitFor({ state: 'hidden' }); return body;
}
async function addMember(actor, space, account, role = 'viewer', admin = false) {
  await detailReady(actor, space.id);
  await actor.page.getByRole('tab', { name: /团队成员/ }).click();
  await actor.page.locator('[data-team-action="add-member"]').click();
  const dialog = actor.page.getByRole('dialog', { name: '添加已有账户', exact: true });
  await dialog.locator('input[name="email"]').fill(account.email);
  await choose(actor.page, dialog, '成员角色', { viewer: '浏览者', editor: '编辑者', manager: '管理者' }[role]);
  const value = await submit(actor, dialog, '添加成员', 'POST', `${admin ? '/admin' : ''}/team-spaces/${space.id}/members`);
  await actor.page.locator(`[data-team-member-id="${account.id}"]`).waitFor(); return value;
}
async function createSpace(actor, name, owner) {
  const admin = Boolean(owner), prefix = admin ? '/admin' : '';
  await actor.page.locator('[data-team-action="create-space"]').click();
  const dialog = actor.page.getByRole('dialog', { name: '创建团队空间', exact: true });
  if (admin) await choose(actor.page, dialog, '空间所有者', `${owner.name} · ${owner.email}`);
  await dialog.locator('input[name="name"]').fill(name);
  await dialog.locator('textarea[name="description"]').fill('隔离真实浏览器协作测试，不连接任何外部系统。');
  const space = await submit(actor, dialog, '创建空间', 'POST', `${prefix}/team-spaces`);
  await detailReady(actor, space.id); return space;
}
async function uploadUI(actor, space, name, buffer = sharedBytes, admin = false) {
  await detailReady(actor, space.id); await actor.page.getByRole('tab', { name: /共享文件/ }).click();
  const chooser = actor.page.waitForEvent('filechooser');
  await actor.page.locator('[data-team-action="upload"]').click();
  const response = actor.page.waitForResponse(value => value.request().method() === 'POST' && endpointOf(value.url()) === `${admin ? '/admin' : ''}/team-spaces/${space.id}/files`);
  await (await chooser).setFiles({ name, mimeType: 'text/plain', buffer });
  const result = await response; if (!result.ok()) throw new Error(await result.text()); const file = await result.json();
  await actor.page.locator(`[data-team-file-id="${file.id}"]`).waitFor(); await detailReady(actor, space.id); return file;
}
async function editModules(admin, account, modules) {
  await goto(admin, '/admin/users');
  await admin.page.locator('.ea-admin-user-row').filter({ hasText: account.email }).getByRole('button', { name: '编辑', exact: true }).click();
  const dialog = admin.page.getByRole('dialog', { name: '编辑账户', exact: true });
  for (const module of ['personal', 'team']) await dialog.locator(`input[name="space_modules"][value="${module}"]`).setChecked(modules.includes(module));
  assert(await dialog.getByText('关闭模块不删除数据，可重新开放恢复访问', { exact: true }).isVisible());
  return submit(admin, dialog, '保存账户', 'PATCH', '/admin/users/' + account.id);
}
async function widthSnapshot(actor, label) {
  const value = await actor.page.evaluate(() => {
    const route = document.querySelector('.route-content');
    return { viewport: { width: innerWidth, height: innerHeight }, document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth, route: route && { width: route.clientWidth, scrollWidth: route.scrollWidth },
      dialog: [...document.querySelectorAll('[role="dialog"]')].map(node => ({ width: node.clientWidth, scrollWidth: node.scrollWidth, left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right })) };
  });
  assert(value.document <= value.viewport.width + 1 && value.body <= value.viewport.width + 1, `${label}: document overflow ${JSON.stringify(value)}`);
  if (value.route) assert(value.route.scrollWidth <= value.route.width + 1, `${label}: route overflow ${JSON.stringify(value)}`);
  for (const dialog of value.dialog) assert(dialog.scrollWidth <= dialog.width + 1 && dialog.left >= -1 && dialog.right <= value.viewport.width + 1, `${label}: dialog overflow ${JSON.stringify(value)}`);
  return { actor: actor.name, label, ...value };
}
async function scrollLayout(actor, space, admin = false) {
  await openSpace(actor, space.id, admin);
  const layout = await widthSnapshot(actor, 'team files workbench');
  layout.panels = await actor.page.evaluate(() => Object.fromEntries(['.ea-team-list-scroll', '.ea-team-detail'].map(selector => {
    const element = document.querySelector(selector); element.scrollTop = 0;
    return [selector, { clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, clientHeight: element.clientHeight, scrollHeight: element.scrollHeight, overflowY: getComputedStyle(element).overflowY }];
  })));
  for (const [selector, panel] of Object.entries(layout.panels)) {
    assert(panel.scrollWidth <= panel.clientWidth + 1 && panel.scrollHeight > panel.clientHeight + 30 && ['auto', 'scroll'].includes(panel.overflowY), `${selector}: ${JSON.stringify(panel)}`);
  }
  const snapshot = () => actor.page.evaluate(() => ({ directory: document.querySelector('.ea-team-list-scroll').scrollTop, detail: document.querySelector('.ea-team-detail').scrollTop, route: document.querySelector('.route-content').scrollTop, document: document.scrollingElement.scrollTop }));
  const directory = actor.page.locator('.ea-team-list-scroll');
  await directory.scrollIntoViewIfNeeded(); const beforeDirectory = await snapshot();
  await directory.hover({ position: { x: 30, y: 50 } }); await actor.page.mouse.wheel(0, 350);
  await actor.page.waitForFunction(() => document.querySelector('.ea-team-list-scroll').scrollTop > 0);
  const afterDirectory = await snapshot();
  assert(afterDirectory.directory > beforeDirectory.directory && afterDirectory.detail === beforeDirectory.detail && afterDirectory.route === beforeDirectory.route && afterDirectory.document === beforeDirectory.document, `directory scroll chained: ${JSON.stringify({ beforeDirectory, afterDirectory })}`);
  const detail = actor.page.locator('.ea-team-detail'); await detail.scrollIntoViewIfNeeded();
  const beforeDetail = await snapshot(); await detail.hover({ position: { x: 40, y: 200 } }); await actor.page.mouse.wheel(0, 420);
  await actor.page.waitForFunction(() => document.querySelector('.ea-team-detail').scrollTop > 0);
  const afterDetail = await snapshot();
  assert(afterDetail.detail > beforeDetail.detail && afterDetail.directory === beforeDetail.directory && afterDetail.route === beforeDetail.route && afterDetail.document === beforeDetail.document, `detail scroll chained: ${JSON.stringify({ beforeDetail, afterDetail })}`);
  layout.wheel = { beforeDirectory, afterDirectory, beforeDetail, afterDetail }; report.layouts.push(layout);
  await actor.page.getByRole('tab', { name: /团队成员/ }).click(); report.layouts.push(await widthSnapshot(actor, 'team members'));
}

(async () => {
  try {
    await startServer();
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-background-networking', '--disable-component-update', '--no-first-run'] });
    report.browser = { name: 'Chromium', version: browser.version(), headless: true };
    const [admin, owner, viewer, editor, manager] = await Promise.all(['admin', 'owner', 'viewer', 'editor', 'manager'].map(newActor));
    await api(admin, 'POST', '/auth/login', { email: 'admin', password: 'admin' });
    await api(admin, 'POST', '/auth/password', { current_password: 'admin', new_password: password });
    await api(admin, 'PATCH', '/auth/me', { theme: 'light' });
    stage = 'administrator account defaults, multi-select and batch';
    await goto(admin, '/admin/users');
    async function createAccountUI(name, email, both = false) {
      await goto(admin, '/admin/users');
      await admin.page.getByRole('button', { name: '创建账户', exact: true }).click();
      const dialog = admin.page.getByRole('dialog', { name: '创建账户', exact: true });
      assert.equal(await dialog.locator('input[name="space_modules"][value="personal"]').isChecked(), true);
      assert.equal(await dialog.locator('input[name="space_modules"][value="team"]').isChecked(), false);
      assert.equal(await dialog.locator('input[name="space_modules"]').count(), 2);
      await dialog.locator('input[name="name"]').fill(name); await dialog.locator('input[name="email"]').fill(email); await dialog.locator('input[name="password"]').fill(password);
      if (both) await dialog.locator('input[name="space_modules"][value="team"]').check();
      return submit(admin, dialog, '创建账户', 'POST', '/admin/users');
    }
    const ownerAccount = await createAccountUI('团队浏览器所有者', 'team-owner@earthai.test');
    const buddy = await createAccountUI('双模块账户', 'team-buddy@earthai.test', true);
    assert.deepEqual(ownerAccount.space_modules, ['personal']); assert.deepEqual(buddy.space_modules, ['personal', 'team']);
    async function batchDialog() {
      for (const account of [ownerAccount, buddy]) await admin.page.getByRole('checkbox', { name: '选择账户 ' + account.email, exact: true }).check();
      await admin.page.getByRole('button', { name: '批量账户配置', exact: true }).click();
      return admin.page.getByRole('dialog', { name: '批量修改 2 个账户', exact: true });
    }
    let batch = await batchDialog();
    assert.equal(await batch.locator('input[name="apply_space_modules"]').isChecked(), false);
    for (const input of await batch.locator('input[name="space_modules"]').all()) assert(await input.isDisabled());
    await choose(admin.page, batch, '统一账户状态', '全部启用登录');
    await submit(admin, batch, '保存账户变更', 'POST', '/admin/users/batch');
    let accounts = await api(admin, 'GET', '/admin/users');
    assert.deepEqual(accounts.find(item => item.id === ownerAccount.id).space_modules, ['personal']);
    assert.deepEqual(accounts.find(item => item.id === buddy.id).space_modules, ['personal', 'team']);
    batch = await batchDialog();
    await batch.getByText('统一修改开放空间（未勾选保持不变）', { exact: true }).click();
    assert.equal(await batch.locator('input[name="allowed_control_levels"][value="observe"]').isDisabled(), true);
    await batch.locator('input[name="space_modules"][value="team"]').check();
    await submit(admin, batch, '保存账户变更', 'POST', '/admin/users/batch');
    accounts = await api(admin, 'GET', '/admin/users');
    for (const account of [ownerAccount, buddy]) {
      const actual = accounts.find(item => item.id === account.id); assert.deepEqual(actual.space_modules, ['personal', 'team']); assert.deepEqual(actual.allowed_control_levels, ['observe']);
    }
    pass('管理端真实创建账户默认 personal；新增支持双模块多选；批量默认保留各自模块，独立开关批量开放不改变控制授权');

    const people = {};
    for (const role of ['viewer', 'editor', 'manager', 'outsider']) people[role] = await api(admin, 'POST', '/admin/users', { name: '团队' + role, email: `team-${role}@earthai.test`, password });
    for (const actor of [owner, viewer, editor, manager]) {
      const account = actor === owner ? ownerAccount : people[actor.name];
      await api(actor, 'POST', '/auth/login', { email: account.email, password });
      await api(actor, 'PATCH', '/auth/me', { theme: 'light' });
    }
    stage = 'owner creates space and invites personal-only users';
    await goto(owner, '/team-spaces');
    const space = await createSpace(owner, '浏览器真实团队协作');
    assert.equal(space.owner_id, ownerAccount.id); assert.equal(space.role, 'owner');
    for (const role of ['viewer', 'editor', 'manager']) {
      assert.deepEqual((await api({ ...admin }, 'GET', '/admin/users')).find(item => item.id === people[role].id).space_modules, ['personal']);
      await addMember(owner, space, people[role], role);
      assert.deepEqual((await api({ viewer, editor, manager }[role], 'GET', '/auth/me')).space_modules, ['personal', 'team']);
    }
    await api(owner, 'POST', `/team-spaces/${space.id}/members`, { email: buddy.email, role: 'manager' });
    const shared = await api(owner, 'POST', `/team-spaces/${space.id}/files`, undefined, multipart('preserved-team.txt'));
    pass('用户通过真实表单创建团队并成为唯一 owner；准确邮箱邀请 viewer/editor/manager，personal-only 账户自动并集开启 team');

    stage = 'viewer read-only UI and file authorization';
    await openSpace(viewer, space.id);
    const viewerFile = viewer.page.locator(`[data-team-file-id="${shared.id}"]`); await viewerFile.waitFor();
    assert.equal(await viewer.page.locator('[data-team-action="upload"], [data-team-action="edit-space"], [data-team-action="transfer"], [data-team-action="archive"]').count(), 0);
    assert(await viewer.page.getByLabel('上传团队文件', { exact: true }).isDisabled());
    assert.equal(await viewerFile.getByRole('button', { name: /^(重命名|替换|永久删除)/ }).count(), 0);
    const downloadResponse = viewer.page.waitForResponse(value => endpointOf(value.url()) === `/team-spaces/${space.id}/files/${shared.id}/download`);
    const downloadEvent = viewer.page.waitForEvent('download');
    await viewerFile.getByRole('button', { name: '下载 preserved-team.txt', exact: true }).click();
    assert((await (await downloadResponse).body()).equals(sharedBytes)); assert.equal((await downloadEvent).suggestedFilename(), 'preserved-team.txt');
    await viewer.page.getByRole('tab', { name: /团队成员/ }).click();
    assert.equal(await viewer.page.locator('[data-team-action="add-member"], .ea-team-member-actions button').count(), 0);
    assert.equal(report.browserWrites.filter(item => item.actor === 'viewer').length, 0);
    for (const [method, suffix, data, options] of [
      ['POST', '/files', undefined, multipart('denied.txt')], ['PATCH', `/files/${shared.id}`, { name: 'denied.txt' }],
      ['PUT', `/files/${shared.id}/content`, undefined, multipart('denied.txt')], ['DELETE', `/files/${shared.id}`],
    ]) await denied(viewer, method, `/team-spaces/${space.id}${suffix}`, 403, 'viewer file write denied', data, options);
    await bytes(viewer, `/team-spaces/${space.id}/files/${shared.id}/download`, sharedBytes);
    pass('viewer 可查看成员、文件并通过真实下载按钮读取原 bytes；写入按钮不存在、隐藏上传输入禁用、未发出浏览器写请求，四类文件写 API 均 403');

    stage = 'editor UI upload rename replace delete and personal file fixture';
    await openSpace(editor, space.id);
    assert.equal(await editor.page.locator('[data-team-action="edit-space"], [data-team-action="add-member"], [data-team-action="transfer"]').count(), 0);
    const scratch = await uploadUI(editor, space, 'editor-upload.txt', Buffer.from('original editor bytes'));
    let row = editor.page.locator(`[data-team-file-id="${scratch.id}"]`);
    await row.getByRole('button', { name: '重命名 editor-upload.txt', exact: true }).click();
    let dialog = editor.page.getByRole('dialog', { name: '重命名团队文件', exact: true });
    await dialog.locator('input[name="name"]').fill('editor-renamed.txt');
    const renamed = await submit(editor, dialog, '保存', 'PATCH', `/team-spaces/${space.id}/files/${scratch.id}`);
    assert.equal(renamed.id, scratch.id); await row.getByRole('button', { name: '替换 editor-renamed.txt', exact: true }).click();
    dialog = editor.page.getByRole('dialog', { name: '替换团队文件内容', exact: true });
    const replacement = Buffer.from('replacement bytes from real editor form\n');
    await dialog.locator('input[type="file"]').setInputFiles({ name: 'replacement.txt', mimeType: 'text/plain', buffer: replacement });
    await submit(editor, dialog, '确认替换', 'PUT', `/team-spaces/${space.id}/files/${scratch.id}/content`);
    const replaced = await api(editor, 'GET', `/team-spaces/${space.id}/files/${scratch.id}`);
    assert.equal(replaced.id, scratch.id); assert.equal(replaced.created_at, scratch.created_at); assert.equal(replaced.name, renamed.name);
    await bytes(editor, `/team-spaces/${space.id}/files/${scratch.id}/download`, replacement);
    await detailReady(editor, space.id); await row.getByRole('button', { name: '永久删除 editor-renamed.txt', exact: true }).click();
    dialog = editor.page.getByRole('dialog', { name: '永久删除这个团队文件？', exact: true });
    await submit(editor, dialog, '永久删除文件', 'DELETE', `/team-spaces/${space.id}/files/${scratch.id}`); await row.waitFor({ state: 'hidden' });
    await denied(editor, 'GET', `/team-spaces/${space.id}/files/${scratch.id}/download`, 404, 'UI-deleted scratch file no longer downloads');
    await goto(editor, '/space');
    const personalResponse = editor.page.waitForResponse(value => value.request().method() === 'POST' && endpointOf(value.url()) === '/files');
    const chooser = editor.page.waitForEvent('filechooser'); await editor.page.getByRole('button', { name: '选择文件', exact: true }).click();
    await (await chooser).setFiles({ name: 'preserved-personal.txt', mimeType: 'text/plain', buffer: personalBytes });
    const personal = await (await personalResponse).json();
    await editor.page.getByText('preserved-personal.txt', { exact: true }).waitFor(); await bytes(editor, `/files/${personal.id}/download`, personalBytes);
    pass('editor 通过真实文件选择、重命名表单、替换表单和永久删除确认完成 CRUD；重命名/替换保留文件 ID；个人文件也通过真实上传入口建立');

    stage = 'manager metadata and limited member roles';
    await openSpace(manager, space.id);
    await manager.page.locator('[data-team-action="edit-space"]').click(); dialog = manager.page.getByRole('dialog', { name: '编辑团队空间', exact: true });
    await dialog.locator('textarea[name="description"]').fill('管理者在真实浏览器中更新的协作描述');
    await submit(manager, dialog, '保存', 'PATCH', `/team-spaces/${space.id}`);
    assert.equal((await api(owner, 'GET', `/team-spaces/${space.id}`)).description, '管理者在真实浏览器中更新的协作描述');
    await manager.page.getByRole('tab', { name: /团队成员/ }).click();
    for (const id of [ownerAccount.id, people.manager.id, buddy.id]) assert.equal(await manager.page.locator(`[data-team-member-id="${id}"] button`).count(), 0);
    await manager.page.locator('[data-team-action="add-member"]').click(); dialog = manager.page.getByRole('dialog', { name: '添加已有账户', exact: true });
    await dialog.getByRole('combobox', { name: '成员角色', exact: true }).click();
    assert.deepEqual(await manager.page.getByRole('option').allTextContents().then(values => values.map(value => value.split('查看成员')[0].split('上传')[0].trim())), ['浏览者', '编辑者']);
    assert.equal(await manager.page.getByRole('option', { name: '管理者', exact: true }).count(), 0); await manager.page.keyboard.press('Escape');
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    for (const role of ['editor', 'viewer']) {
      await manager.page.locator(`[data-team-member-id="${people.viewer.id}"]`).getByRole('button', { name: `修改 ${people.viewer.name} 的角色`, exact: true }).click();
      dialog = manager.page.getByRole('dialog', { name: '调整成员角色', exact: true });
      await choose(manager.page, dialog, '成员角色', role === 'editor' ? '编辑者' : '浏览者');
      await submit(manager, dialog, '保存', 'PATCH', `/team-spaces/${space.id}/members/${people.viewer.id}`); await detailReady(manager, space.id);
    }
    await denied(manager, 'POST', `/team-spaces/${space.id}/members`, 403, 'manager cannot grant peer manager', { email: people.outsider.email, role: 'manager' });
    await denied(manager, 'PATCH', `/team-spaces/${space.id}/members/${people.editor.id}`, 403, 'manager cannot promote editor to manager', { role: 'manager' });
    await denied(manager, 'PATCH', `/team-spaces/${space.id}/members/${ownerAccount.id}`, 409, 'manager cannot demote owner', { role: 'viewer' });
    await denied(manager, 'PATCH', `/team-spaces/${space.id}/members/${people.editor.id}`, 422, 'owner role is not a member-role grant', { role: 'owner' });
    await denied(manager, 'POST', `/team-spaces/${space.id}/transfer`, 403, 'manager cannot transfer ownership', { user_id: people.editor.id });
    pass('manager 真实编辑空间并往返调整 viewer/editor；角色选择只列两种，owner/自己/同级 manager 无操作；提权 manager/owner 和转交均被 API 拒绝');

    stage = 'disable both modules, blocked invites, preserve IDs and bytes';
    const second = await api(manager, 'POST', '/team-spaces', { name: '邀请停用边界空间' });
    const closed = await editModules(admin, people.editor, []); assert.deepEqual(closed.space_modules, []); assert.equal(closed.team_invites_blocked, true);
    await goto(editor, '/team-spaces');
    assert(await editor.page.getByRole('heading', { name: '团队空间暂未开启', exact: true }).isVisible());
    const disabledAt = browserRequests.length;
    await goto(editor, '/space'); assert(await editor.page.getByRole('heading', { name: '个人空间暂未开启', exact: true }).isVisible());
    await goto(editor, '/team-spaces'); assert(await editor.page.getByRole('heading', { name: '团队空间暂未开启', exact: true }).isVisible());
    assert.equal(await editor.page.locator('a[href="/space"], a[href="/team-spaces"]').count(), 0);
    assert.equal(browserRequests.slice(disabledAt).filter(item => item.actor === 'editor' && item.isApi && (item.endpoint === '/files' || item.endpoint.startsWith('/team-spaces'))).length, 0);
    for (const endpoint of ['/files', `/files/${personal.id}/download`, '/team-spaces', `/team-spaces/${space.id}/files/${shared.id}/download`]) await denied(editor, 'GET', endpoint, 403, 'explicitly disabled module rejects old session');
    await openSpace(manager, second.id);
    await manager.page.getByRole('tab', { name: /团队成员/ }).click(); await manager.page.locator('[data-team-action="add-member"]').click();
    dialog = manager.page.getByRole('dialog', { name: '添加已有账户', exact: true }); await dialog.locator('input[name="email"]').fill(people.editor.email);
    expectHttp('manager', 'POST', `/team-spaces/${second.id}/members`, 409, 'administrator-closed team cannot be re-enabled by invitation');
    const blockedInvite = manager.page.waitForResponse(value => value.request().method() === 'POST' && endpointOf(value.url()) === `/team-spaces/${second.id}/members`);
    await dialog.getByRole('button', { name: '添加成员', exact: true }).click(); assert.equal((await blockedInvite).status(), 409);
    await dialog.getByRole('alert').filter({ hasText: '团队入口已被平台关闭' }).waitFor(); assert(await dialog.isVisible());
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await denied(admin, 'POST', `/admin/team-spaces/${second.id}/members`, 409, 'global administrator invitation also respects explicit module closure', { email: people.editor.email, role: 'viewer' });
    const reopened = await editModules(admin, people.editor, ['personal', 'team']); assert.equal(reopened.team_invites_blocked, false);
    assert((await api(editor, 'GET', '/files')).some(item => item.id === personal.id && item.name === personal.name));
    assert((await api(editor, 'GET', `/team-spaces/${space.id}/files`)).some(item => item.id === shared.id && item.name === shared.name));
    await bytes(editor, `/files/${personal.id}/download`, personalBytes); await bytes(editor, `/team-spaces/${space.id}/files/${shared.id}/download`, sharedBytes);
    assert.equal((await api(editor, 'GET', `/team-spaces/${space.id}`)).role, 'editor');
    await openSpace(editor, space.id); await editor.page.locator(`[data-team-file-id="${shared.id}"]`).waitFor();
    await goto(editor, '/space'); await editor.page.getByText('preserved-personal.txt', { exact: true }).waitFor();
    await addMember(manager, second, people.editor, 'viewer');
    report.preservation = { personal: { id: personal.id, bytes: personalBytes.length, identical: true }, team: { id: shared.id, bytes: sharedBytes.length, identical: true }, membershipRole: 'editor' };
    pass('管理端真实关闭两个模块后旧会话接口均 403、路由无数据请求且入口隐藏；普通与全局管理员邀请不能绕过；重新开放后个人/团队原 ID、名称、bytes 与成员角色均保留');

    stage = 'archive skips files, blocks all mutation, owner deletion preflight and restore';
    await openSpace(owner, space.id);
    assert.equal(await owner.page.locator('[data-team-action="leave"]').count(), 0);
    await denied(owner, 'POST', `/team-spaces/${space.id}/leave`, 409, 'owner cannot leave before transfer');
    const archiveStart = browserRequests.length;
    await owner.page.locator('[data-team-action="archive"]').click(); dialog = owner.page.getByRole('dialog', { name: '归档团队空间？', exact: true });
    await submit(owner, dialog, '归档空间', 'DELETE', `/team-spaces/${space.id}`);
    await owner.page.locator('[data-team-archived]').waitFor(); await detailReady(owner, space.id);
    assert(await owner.page.locator('[data-team-action="restore"]').isEnabled());
    assert.equal(await owner.page.locator('[data-team-action="upload"], [data-team-action="transfer"], [data-team-action="leave"], [data-team-access-error]').count(), 0);
    assert.equal(browserRequests.slice(archiveStart).filter(item => item.actor === 'owner' && item.method === 'GET' && item.endpoint === `/team-spaces/${space.id}/files`).length, 0, 'archived detail must not request forbidden file listing');
    const archived = await api(owner, 'GET', `/team-spaces/${space.id}`); assert(archived.archived); assert.equal(archived.file_count, 1);
    const archiveCalls = [
      [owner, 'PATCH', '', { name: 'must restore' }], [owner, 'POST', '/members', { email: people.outsider.email, role: 'viewer' }],
      [owner, 'PATCH', `/members/${people.viewer.id}`, { role: 'editor' }], [owner, 'DELETE', `/members/${people.viewer.id}`],
      [owner, 'POST', '/files', undefined, multipart('blocked.txt')], [owner, 'PATCH', `/files/${shared.id}`, { name: 'blocked.txt' }],
      [owner, 'PUT', `/files/${shared.id}/content`, undefined, multipart('blocked.txt')], [owner, 'DELETE', `/files/${shared.id}`],
      [owner, 'POST', '/transfer', { user_id: people.manager.id }], [editor, 'POST', '/leave'], [editor, 'DELETE', `/members/${people.editor.id}`],
      [admin, 'POST', '/transfer', { user_id: people.manager.id }], [admin, 'PATCH', '', { name: 'admin must restore' }],
    ];
    for (const [actor, method, suffix, data, options] of archiveCalls) {
      const body = await denied(actor, method, `${actor === admin ? '/admin' : ''}/team-spaces/${space.id}${suffix}`, 409, 'archived operation requires restore', data, options);
      assert.match(body.detail, /先恢复/);
    }
    await denied(viewer, 'GET', `/team-spaces/${space.id}/files/${shared.id}/download`, 409, 'archived file downloads paused');
    await openSpace(viewer, space.id); await viewer.page.locator('[data-team-archived]').waitFor();
    assert.equal(await viewer.page.locator('[data-team-action="leave"], [data-team-action="restore"]').count(), 0);
    await goto(admin, '/admin/users'); await admin.page.getByRole('button', { name: '删除账户 ' + ownerAccount.email, exact: true }).click();
    dialog = admin.page.getByRole('dialog', { name: '删除 1 个账户及其数据？', exact: true });
    expectHttp('admin', 'DELETE', '/admin/users/' + ownerAccount.id, 409, 'archived team owner cannot be deleted before ownership transfer');
    const deletion = admin.page.waitForResponse(value => value.request().method() === 'DELETE' && endpointOf(value.url()) === '/admin/users/' + ownerAccount.id);
    await dialog.getByRole('button', { name: '确认操作', exact: true }).click(); assert.equal((await deletion).status(), 409);
    await dialog.locator('.inline-error').filter({ hasText: '先转交所有权' }).waitFor(); await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await denied(admin, 'PATCH', '/admin/users/' + ownerAccount.id, 409, 'archived team owner cannot be promoted to platform admin', { role: 'admin' });
    const restoreResponse = owner.page.waitForResponse(value => value.request().method() === 'POST' && endpointOf(value.url()) === `/team-spaces/${space.id}/restore`);
    await owner.page.locator('[data-team-action="restore"]').click(); assert((await restoreResponse).ok());
    await owner.page.locator('[data-team-archived]').waitFor({ state: 'hidden' }); await owner.page.locator(`[data-team-file-id="${shared.id}"]`).waitFor();
    await bytes(owner, `/team-spaces/${space.id}/files/${shared.id}/download`, sharedBytes);
    pass('真实归档不请求 files，仍能显示恢复按钮；13 项归档写操作（含用户/管理员 transfer 和两种 leave）须先恢复；owner 无离开入口且不可删除/升级；恢复后原文件可读');

    stage = 'removed member loses browser and API access';
    await openSpace(viewer, space.id); await viewer.page.locator(`[data-team-file-id="${shared.id}"]`).waitFor();
    await owner.page.getByRole('tab', { name: /团队成员/ }).click();
    await owner.page.locator(`[data-team-member-id="${people.viewer.id}"]`).getByRole('button', { name: '移除 ' + people.viewer.name, exact: true }).click();
    dialog = owner.page.getByRole('dialog', { name: '移除团队成员？', exact: true });
    await submit(owner, dialog, '移除成员', 'DELETE', `/team-spaces/${space.id}/members/${people.viewer.id}`);
    expectHttp('viewer', 'GET', `/team-spaces/${space.id}`, 404, 'removed member refresh must clear stale team data');
    await viewer.page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await viewer.page.waitForFunction(() => document.querySelectorAll('[data-team-file-id]').length === 0 && /无权限或已变化/.test(document.body.textContent));
    assert.equal(await viewer.page.locator('[data-team-action="upload"], [data-team-action="leave"], .ea-team-member-actions button').count(), 0);
    for (const suffix of ['', '/files', `/files/${shared.id}/download`]) await denied(viewer, 'GET', `/team-spaces/${space.id}${suffix}`, 404, 'removed member cannot read known team or file ID');
    assert(!(await api(viewer, 'GET', '/team-spaces')).some(item => item.id === space.id));
    await bytes(owner, `/team-spaces/${space.id}/files/${shared.id}/download`, sharedBytes);
    pass('所有者通过真实成员移除确认撤权；viewer 焦点刷新清除旧文件和操作，已知空间/文件 ID 均 404，其他成员原 bytes 不变');

    stage = 'global administration without membership or enabled modules';
    const adminAccount = await api(admin, 'GET', '/auth/me');
    await api(admin, 'PATCH', '/admin/users/' + adminAccount.id, { space_modules: [] });
    await goto(admin, '/admin/team-spaces');
    for (const value of [space, second]) await admin.page.locator(`[data-team-space-id="${value.id}"]`).waitFor();
    assert.equal((await api(admin, 'GET', `/admin/team-spaces/${space.id}`)).role, 'admin');
    assert(!(await api(admin, 'GET', `/admin/team-spaces/${space.id}/members`)).some(item => item.user_id === adminAccount.id));
    const globalSpace = await createSpace(admin, '全局管理员真实管理空间', people.manager);
    assert.equal(globalSpace.owner_id, people.manager.id); assert.equal(globalSpace.role, 'admin');
    await admin.page.locator('[data-team-action="edit-space"]').click(); dialog = admin.page.getByRole('dialog', { name: '编辑团队空间', exact: true });
    await dialog.locator('textarea[name="description"]').fill('无成员身份且空间模块全关闭的管理员仍能全球管理');
    await submit(admin, dialog, '保存', 'PATCH', `/admin/team-spaces/${globalSpace.id}`);
    const globalFile = await uploadUI(admin, globalSpace, 'global-admin-upload.txt', Buffer.from('global admin fixture'), true);
    await addMember(admin, globalSpace, buddy, 'manager', true);
    await admin.page.locator('[data-team-action="transfer"]').click(); dialog = admin.page.getByRole('dialog', { name: '转移团队空间所有权', exact: true });
    await choose(admin.page, dialog, '新所有者', `${buddy.name} · ${buddy.email}`);
    await submit(admin, dialog, '确认转移所有权', 'POST', `/admin/team-spaces/${globalSpace.id}/transfer`);
    assert.equal((await api(admin, 'GET', `/admin/team-spaces/${globalSpace.id}`)).owner_id, buddy.id);
    await detailReady(admin, globalSpace.id); await admin.page.locator('[data-team-action="archive"]').click(); dialog = admin.page.getByRole('dialog', { name: '归档团队空间？', exact: true });
    await submit(admin, dialog, '归档空间', 'DELETE', `/admin/team-spaces/${globalSpace.id}`);
    await admin.page.locator('[data-team-archived]').waitFor(); await detailReady(admin, globalSpace.id);
    const globalRestore = admin.page.waitForResponse(value => value.request().method() === 'POST' && endpointOf(value.url()) === `/admin/team-spaces/${globalSpace.id}/restore`);
    await admin.page.locator('[data-team-action="restore"]').click(); assert((await globalRestore).ok());
    await admin.page.getByRole('tab', { name: /共享文件/ }).click(); await admin.page.locator(`[data-team-file-id="${globalFile.id}"]`).waitFor();
    await detailReady(admin, globalSpace.id);
    await admin.page.getByRole('button', { name: '永久删除 global-admin-upload.txt', exact: true }).click(); dialog = admin.page.getByRole('dialog', { name: '永久删除这个团队文件？', exact: true });
    await submit(admin, dialog, '永久删除文件', 'DELETE', `/admin/team-spaces/${globalSpace.id}/files/${globalFile.id}`);
    await denied(admin, 'GET', '/team-spaces', 403, 'administrator remains forbidden from ordinary user team route');
    assert.deepEqual((await api(admin, 'GET', '/auth/me')).space_modules, []);
    pass('管理员无成员身份且模块全关闭仍可看到全局团队，并真实创建指定普通 owner、编辑、上传、授 manager、转交、归档、恢复与删除文件；普通用户接口仍 403');

    stage = 'desktop and mobile independent panel scrolling';
    for (let i = 0; i < 13; i += 1) await api(manager, 'POST', '/team-spaces', { name: `独立滚动空间 ${String(i + 1).padStart(2, '0')} ${'很长的目录名称'.repeat(6)}`, description: '用于真实目录滚动与文字截断的隔离 fixture' });
    for (let i = 0; i < 12; i += 1) await api(manager, 'POST', `/team-spaces/${space.id}/files`, undefined, multipart(`layout-${i}-${'long-unbroken-name-'.repeat(5)}.txt`, Buffer.from('small local layout fixture ' + i)));
    for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
      for (const [actor, isAdmin] of [[manager, false], [admin, true]]) {
        await actor.page.setViewportSize(viewport); await scrollLayout(actor, space, isAdmin);
      }
      await goto(admin, '/admin/users');
      await admin.page.locator('.ea-admin-user-row').filter({ hasText: people.editor.email }).getByRole('button', { name: '编辑', exact: true }).click();
      report.layouts.push(await widthSnapshot(admin, 'account module edit dialog'));
      await admin.page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    }
    pass('1366×900 与 390×844 用户端和管理端文档/route/目录/详情无横向越界；真实鼠标滚轮分别滚动目录与详情，不带动另一面板或页面；成员页及模块编辑弹窗宽度通过');

    stage = 'owner transfer unlocks leave and account deletion';
    await openSpace(owner, space.id);
    await owner.page.locator('[data-team-action="transfer"]').click(); dialog = owner.page.getByRole('dialog', { name: '转移团队空间所有权', exact: true });
    await choose(owner.page, dialog, '新所有者', `${people.manager.name} · ${people.manager.email}`);
    const transferred = await submit(owner, dialog, '确认转移所有权', 'POST', `/team-spaces/${space.id}/transfer`);
    assert.equal(transferred.owner_id, people.manager.id); assert.equal(transferred.role, 'manager');
    const members = await api(manager, 'GET', `/team-spaces/${space.id}/members`);
    assert.equal(members.filter(item => item.role === 'owner').length, 1); assert.equal(members.find(item => item.user_id === ownerAccount.id).role, 'manager');
    await detailReady(owner, space.id); await owner.page.locator('[data-team-action="leave"]').click();
    dialog = owner.page.getByRole('dialog', { name: '离开团队空间？', exact: true });
    expectHttp('owner', 'GET', `/team-spaces/${space.id}`, 404, 'former owner leaving triggers safe stale-data refresh', true);
    await submit(owner, dialog, '确认离开', 'DELETE', `/team-spaces/${space.id}/members/${ownerAccount.id}`);
    assert(!(await api(manager, 'GET', `/team-spaces/${space.id}/members`)).some(item => item.user_id === ownerAccount.id));
    closing.add(owner.name); await owner.page.close();
    await goto(admin, '/admin/users'); await admin.page.getByRole('button', { name: '删除账户 ' + ownerAccount.email, exact: true }).click();
    dialog = admin.page.getByRole('dialog', { name: '删除 1 个账户及其数据？', exact: true });
    await submit(admin, dialog, '确认操作', 'DELETE', '/admin/users/' + ownerAccount.id);
    assert(!(await api(admin, 'GET', '/admin/users')).some(item => item.id === ownerAccount.id));
    await bytes(manager, `/team-spaces/${space.id}/files/${shared.id}/download`, sharedBytes);
    await bytes(editor, `/files/${personal.id}/download`, personalBytes);
    pass('所有者真实转交后原 owner 立即降为 manager，可真实离开且账户可删除；唯一新 owner、共享原文件 bytes 与他人个人文件均保留');

    stage = 'telemetry and isolation assertions';
    for (const rule of expected) assert(rule.optional || rule.hits > 0, `expected browser denial was not observed: ${JSON.stringify(rule)}`);
    report.unexpectedConsole = report.console.filter(message => {
      if (!['error', 'warning', 'warn'].includes(message.type)) return false;
      const match = report.expectedHttp.find(item => item.actor === message.actor && message.url && endpointOf(message.url) === item.endpoint && message.text.includes(String(item.status)) && /^Failed to load resource:/.test(message.text));
      if (match) { report.expectedConsole.push({ ...message, reason: match.reason }); return false; }
      return true;
    });
    report.backendBlockedOperations = serverOutput.split('\n').filter(line => line.startsWith('E2E_BLOCKED ')).map(line => JSON.parse(line.slice('E2E_BLOCKED '.length)));
    assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.externalRequests, []); assert.deepEqual(report.unexpectedHttp, []);
    assert.deepEqual(report.requestFailures, []); assert.deepEqual(report.unexpectedConsole, []); assert.deepEqual(report.backendBlockedOperations, []);
    assert.equal(report.browserWrites.filter(item => item.actor === 'viewer').length, 0);
    assert.equal(browserRequests.filter(item => /\/messages$|\/run$|\/test$|\/completion/.test(item.endpoint) && item.method !== 'GET').length, 0);
    pass('console/pageerror/非预期 HTTP/请求失败/浏览器外联/后端外联与模型或工具调用全部为零；预期 403/404/409/422 独立记录且不掩盖异常');
    report.ok = true;
  } catch (error) {
    report.failure = { stage, message: error.message, stack: error.stack };
    report.recentRequests = browserRequests.slice(-40);
    report.failurePages = [];
    for (const [name, context] of contexts) for (const page of context.pages()) {
      report.failurePages.push({ actor: name, url: page.url(), snapshot: await page.evaluate(() => ({ text: document.body.innerText.slice(-12000), dialogs: [...document.querySelectorAll('[role="dialog"]')].map(dialog => ({ text: dialog.textContent, fields: [...dialog.querySelectorAll('input,textarea,button[type="submit"]')].map(field => ({ name: field.name, type: field.type, value: field.type === 'password' ? '[redacted]' : field.value, checked: field.checked, disabled: field.disabled, validity: field.validationMessage })) })) })).catch(() => null) });
    }
    console.error(`FAIL [${stage}]`, error);
    process.exitCode = 1;
  } finally {
    report.stage = stage;
    report.backendBlockedOperations = serverOutput.split('\n').filter(line => line.startsWith('E2E_BLOCKED ')).map(line => JSON.parse(line.slice('E2E_BLOCKED '.length)));
    if (!report.ok) report.serverOutput = serverOutput.slice(-12000);
    await cleanup();
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
    console.log('REPORT', reportPath);
    console.log(JSON.stringify({ ok: report.ok, checks: report.checks.length, layouts: report.layouts.length, negatives: report.negativeAssertions.length, pageErrors: report.pageErrors.length, externalRequests: report.externalRequests.length, unexpectedHttp: report.unexpectedHttp.length, requestFailures: report.requestFailures.length, cleanup: report.cleanup }));
  }
})();
