const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const origin = new URL(base).origin;
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const contexts = await Promise.all([1366, 1366, 1366].map(width => browser.newContext({ locale: 'zh-CN', viewport: { width, height: 960 } })));
  const [admin, user, other] = contexts;
  const errors = [], external = [], checks = [];
  const pass = text => { checks.push(text); console.log('PASS', text); };
  for (const context of contexts) {
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) { external.push(url.href); return route.abort(); }
      if (url.pathname === '/isolated-remote-target') return route.fulfill({ contentType: 'text/html', body: '<title>受控远程站点</title><p>仅用于本地点击验收。</p>' });
      return route.continue();
    });
  }
  const [adminPage, userPage] = await Promise.all([admin.newPage(), user.newPage()]);
  const api = async (context, method, endpoint, data) => {
    const response = await context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }) });
    assert(response.ok(), `${method} ${endpoint}: ${await response.text()}`);
    return response.json();
  };
  const all = (context, kind) => api(context, 'GET', '/' + kind);
  const copy = async (context, kind, template) => {
    const value = (await all(context, kind)).find(item => item.default_template_id === template.id);
    assert(value, `missing copy ${kind}/${template.id}`); return value;
  };
  const widthCheck = async page => {
    const sizes = await page.evaluate(() => ({ viewport: innerWidth, full: document.documentElement.scrollWidth, scroll: document.querySelector('.route-content').scrollWidth, main: document.querySelector('.route-content').clientWidth }));
    assert(sizes.full <= sizes.viewport + 1 && sizes.scroll <= sizes.main + 1, JSON.stringify(sizes));
  };
  const run = async (agent, text, provider) => {
    const conversation = await api(user, 'POST', '/conversations', { agent_id: agent.id, provider_id: provider.id, model: provider.default_model, control_level: 'observe' });
    const task = await api(user, 'POST', `/conversations/${conversation.id}/messages`, { content: text });
    await userPage.goto(base + '/chat/' + conversation.id, { waitUntil: 'networkidle' });
    await userPage.getByText('本地验收已收到角色指令和知识参考。本回复来自受控测试模型，不代表生产检查。', { exact: true }).waitFor();
    assert.equal((await api(user, 'GET', '/runs/' + task.id)).run.status, 'completed');
  };
  try {
    await api(admin, 'POST', '/auth/login', { email: 'admin', password: 'admin' });
    await api(admin, 'POST', '/auth/password', { current_password: 'admin', new_password: 'Resources-Admin-2026!' });
    const initial = await api(admin, 'GET', '/admin/defaults/agents');
    const local = initial.find(item => item.builtin_domain === 'pod-troubleshooting'); assert(local);
    const skill = await api(admin, 'GET', '/admin/defaults/skills/' + local.skill_ids[0]);
    const knowledge = await api(admin, 'GET', '/admin/defaults/knowledge/' + local.knowledge_ids[0]);
    const remote = await api(admin, 'POST', '/admin/defaults/agents', { name: '远程点击验收', kind: 'remote', url: base + '/isolated-remote-target' });
    await api(admin, 'POST', '/admin/defaults/providers', { name: '供应商间距验收', base_url: 'http://127.0.0.1:9909/v1', api_key: 'isolated-catalog' });
    await api(user, 'POST', '/auth/register', { email: 'personal-ui@earthai.local', password: 'Resources-User-2026!', name: '个人副本验收' });
    await api(other, 'POST', '/auth/register', { email: 'other-ui@earthai.local', password: 'Resources-Other-2026!', name: '隔离对照账户' });
    const selected = await copy(user, 'agents', local), inheritedRemote = await copy(user, 'agents', remote);
    assert.equal(selected.read_only, false); assert.equal(inheritedRemote.read_only, true);
    const inheritedSkill = await copy(user, 'skills', skill), inheritedKnowledge = await copy(user, 'knowledge', knowledge);
    const providers = await all(user, 'providers'); const provider = providers[0]; assert(provider.default_model);
    await run(selected, 'CrashLoopBackOff', provider);
    const privateKnowledge = await api(user, 'POST', '/knowledge', { name: '私有计数库' });
    const indexed = await user.request.post(base + `/api/knowledge/${privateKnowledge.id}/documents`, { multipart: { file: { name: 'private.txt', mimeType: 'text/plain', buffer: Buffer.from('private_usage_marker 专用检索证据') } } });
    assert(indexed.ok(), await indexed.text());
    const privateSkill = await api(user, 'POST', '/skills', { name: '私有计数技能', content: '仅阅读给定资料并作简短说明。', enabled: true });
    const privateAgent = await api(user, 'POST', '/agents', { name: '私有计数智能体', system_prompt: '仅解释资料。', skill_ids: [privateSkill.id], knowledge_ids: [privateKnowledge.id] });
    await run(privateAgent, 'private_usage_marker', provider);
    let overview = await api(admin, 'GET', '/admin/overview');
    assert.deepEqual(overview.usage.totals, { agents: 2, knowledge: 2, skills: 2 });
    assert.equal(overview.usage.scope, 'all_resources');
    pass('真实默认和自建本地任务均进入三类全量统计');

    await userPage.goto(base + '/agents', { waitUntil: 'networkidle' });
    const remoteCard = userPage.locator(`[data-agent-id="${inheritedRemote.id}"]`);
    assert.equal(await remoteCard.getByRole('button', { name: '编辑智能体', exact: true }).count(), 0);
    assert.equal(await remoteCard.getByRole('button', { name: '删除智能体', exact: true }).count(), 0);
    const remoteLink = remoteCard.getByRole('link', { name: '打开远程智能体' });
    for (const mode of ['mouse', 'keyboard', 'control', 'middle']) {
      const recorded = userPage.waitForResponse(response => response.url().endsWith(`/api/agents/${inheritedRemote.id}/open`) && response.request().method() === 'POST');
      const popup = user.waitForEvent('page');
      if (mode === 'keyboard') { await remoteLink.focus(); await remoteLink.press('Enter'); }
      else if (mode === 'control') await remoteLink.click({ modifiers: ['Control'] });
      else await remoteLink.click(mode === 'middle' ? { button: 'middle' } : {});
      const opened = await popup; assert((await recorded).ok()); await opened.close();
    }
    assert.equal((await api(admin, 'GET', '/admin/defaults/agents/' + remote.id)).usage_count, 4);
    const personalRemote = await api(user, 'POST', '/agents', { name: '个人远程计数', kind: 'remote', url: base + '/isolated-remote-target' });
    await userPage.reload({ waitUntil: 'networkidle' });
    const privateLink = userPage.locator(`[data-agent-id="${personalRemote.id}"]`).getByRole('link', { name: '打开远程智能体' });
    const privateRecorded = userPage.waitForResponse(response => response.url().endsWith(`/api/agents/${personalRemote.id}/open`));
    const privatePopup = user.waitForEvent('page'); await privateLink.click(); await (await privatePopup).close(); assert((await privateRecorded).ok());
    overview = await api(admin, 'GET', '/admin/overview'); assert.deepEqual(overview.usage.totals, { agents: 7, knowledge: 2, skills: 2 });
    pass('默认远程鼠标、键盘、修饰键、中键与私人远程逐次计数；默认远程无写入口');

    const localCard = userPage.locator(`[data-agent-id="${selected.id}"]`);
    await localCard.getByRole('button', { name: '编辑智能体', exact: true }).click();
    const localForm = userPage.getByRole('dialog', { name: '编辑智能体', exact: true });
    await localForm.getByLabel('智能体名称', { exact: false }).fill('个人定制本地助手');
    await localForm.getByRole('button', { name: '保存', exact: true }).click(); await localForm.waitFor({ state: 'hidden' });
    assert.equal((await copy(user, 'agents', local)).name, '个人定制本地助手');
    assert.equal((await copy(user, 'agents', local)).personal_override, true);
    assert.equal((await copy(other, 'agents', local)).name, local.name);
    await api(admin, 'PATCH', '/admin/defaults/agents/' + local.id, { description: '管理员后续修订' });
    assert.equal((await copy(user, 'agents', local)).name, '个人定制本地助手');
    assert.equal((await copy(user, 'agents', local)).personal_override, true);

    await userPage.goto(base + '/skills', { waitUntil: 'networkidle' });
    await userPage.getByPlaceholder('查找技能…').fill(inheritedSkill.name);
    await userPage.getByRole('button', { name: '编辑技能', exact: true }).click();
    const skillForm = userPage.getByRole('dialog', { name: '编辑技能', exact: true });
    await skillForm.getByLabel('技能名称', { exact: false }).fill('个人定制技能');
    await skillForm.getByRole('button', { name: '保存', exact: true }).click(); await skillForm.waitFor({ state: 'hidden' });
    assert.equal((await copy(user, 'skills', skill)).name, '个人定制技能');
    assert.equal((await copy(other, 'skills', skill)).name, skill.name);

    await userPage.goto(base + '/knowledge', { waitUntil: 'networkidle' });
    await userPage.getByRole('button', { name: new RegExp(inheritedKnowledge.name) }).click();
    await userPage.getByRole('button', { name: '编辑知识库', exact: true }).click();
    const knowledgeForm = userPage.getByRole('dialog', { name: '编辑知识库', exact: true });
    await knowledgeForm.getByLabel('知识库名称', { exact: false }).fill('个人定制知识库');
    await knowledgeForm.getByRole('button', { name: '保存', exact: true }).click(); await knowledgeForm.waitFor({ state: 'hidden' });
    assert.equal((await copy(user, 'knowledge', knowledge)).name, '个人定制知识库');
    const files = userPage.locator('input[type="file"]'); assert.equal(await files.count(), 1);
    const uploaded = userPage.waitForResponse(response => response.url().endsWith(`/api/knowledge/${inheritedKnowledge.id}/documents`) && response.request().method() === 'POST');
    await files.setInputFiles({ name: 'personal-document.txt', mimeType: 'text/plain', buffer: Buffer.from('personal_doc_marker 仅属于当前用户的文档') }); assert((await uploaded).ok());
    assert((await api(user, 'GET', `/knowledge/${inheritedKnowledge.id}/documents`)).some(doc => doc.name === 'personal-document.txt'));
    await userPage.getByRole('button', { name: '删除知识库', exact: true }).click();
    const deletion = userPage.getByRole('dialog', { name: '删除知识库及文档？', exact: true });
    await deletion.getByRole('button', { name: '确认操作', exact: true }).click(); await deletion.waitFor({ state: 'hidden' });
    await api(admin, 'PATCH', '/admin/defaults/knowledge/' + knowledge.id, { description: '管理员再次同步' });
    assert(!(await all(user, 'knowledge')).some(item => item.id === inheritedKnowledge.id));
    assert((await all(other, 'knowledge')).some(item => item.default_template_id === knowledge.id));
    pass('三类默认本地资源可个人编辑，知识文档可上传，删除及模板再同步不复活且不影响其他账户');

    for (const viewport of [{ width: 1366, height: 960 }, { width: 390, height: 844 }]) {
      await userPage.setViewportSize(viewport); await userPage.goto(base + '/providers', { waitUntil: 'networkidle' });
      const providerCard = userPage.locator('.provider-card').filter({ hasText: '供应商间距验收' });
      const gap = await providerCard.evaluate(card => card.querySelector('.ea-resource-read-only').getBoundingClientRect().top - card.querySelector('.provider-card-heading').getBoundingClientRect().bottom);
      assert(gap >= 9, `provider badge gap=${gap}`); await widthCheck(userPage);
      await adminPage.setViewportSize(viewport); await adminPage.goto(base + '/admin/agents', { waitUntil: 'networkidle' });
      await adminPage.getByPlaceholder('搜索智能体名称、描述或地址…').fill('远程点击验收');
      await adminPage.locator('[data-admin-action="reorder-agents"]').click();
      const orderDialog = adminPage.locator('.ea-admin-agent-order');
      const templateOrder = await api(admin, 'GET', '/admin/defaults/agents');
      assert.equal(await orderDialog.locator('[data-agent-id]').count(), templateOrder.length);
      const first = templateOrder[0], second = templateOrder[1];
      await orderDialog.getByRole('button', { name: '下移 ' + first.name, exact: true }).click();
      await widthCheck(adminPage);
      await orderDialog.locator('[data-admin-action="reorder-save"]').click(); await orderDialog.waitFor({ state: 'hidden' });
      const savedOrder = await api(admin, 'GET', '/admin/defaults/agents'); assert.equal(savedOrder[0].id, second.id); assert.equal(savedOrder[1].id, first.id);
      await adminPage.reload({ waitUntil: 'networkidle' });
      await adminPage.getByPlaceholder('搜索智能体名称、描述或地址…').fill('远程点击验收');
      await adminPage.getByRole('button', { name: '编辑', exact: true }).click();
      const adminForm = adminPage.getByRole('dialog'); assert.equal(await adminForm.locator('input[name="sort_order"]').count(), 0);
      await adminForm.getByRole('button', { name: '取消', exact: true }).click();
    }
    pass('桌面及390px供应商徽标间距、管理员全量按钮排序持久化和无数字排序输入通过');
    await userPage.goto(base + '/knowledge', { waitUntil: 'networkidle' });
    await api(user, 'POST', '/knowledge/search', { query: 'CrashLoopBackOff' });
    assert.deepEqual((await api(admin, 'GET', '/admin/overview')).usage.totals, { agents: 7, knowledge: 2, skills: 2 });
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/personal-resources-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, totals: { agents: 7, knowledge: 2, skills: 2 }, pageErrors: errors, externalRequests: external, scope: 'isolated local fixture completion and intercepted same-origin remote target; no paid model, production infrastructure or NAS calls' }, null, 2) + '\n');
  } finally { await Promise.all(contexts.map(context => context.close())); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
