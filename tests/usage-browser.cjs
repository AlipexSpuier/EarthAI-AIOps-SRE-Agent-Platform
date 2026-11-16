const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const adminContext = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 1000 } });
  const userContext = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 900 } });
  const errors = [], external = [], checks = [];
  const pass = text => { checks.push(text); console.log('PASS', text); };
  for (const context of [adminContext, userContext]) {
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== new URL(base).origin) { external.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
  }
  const adminPage = await adminContext.newPage();
  const userPage = await userContext.newPage();
  const api = async (context, method, endpoint, data) => {
    const response = await context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }) });
    assert(response.ok(), await response.text()); return response.json();
  };
  try {
    await api(adminContext, 'POST', '/auth/login', { email: 'admin', password: 'admin' });
    await api(adminContext, 'POST', '/auth/password', { current_password: 'admin', new_password: 'Usage-Admin-2026!' });
    const catalog = await api(adminContext, 'GET', '/admin/defaults/agents');
    const source = catalog.find(item => item.builtin_domain === 'pod-troubleshooting'); assert(source);
    const skillId = source.skill_ids[0], knowledgeId = source.knowledge_ids[0];
    await api(adminContext, 'POST', '/admin/defaults/providers', { name: '受控模型目录', base_url: 'http://127.0.0.1:9909/v1', api_key: 'local-fixture' });
    await api(userContext, 'POST', '/auth/register', { email: 'usage-browser@earthai.local', password: 'Usage-User-2026!', name: '统计验收用户' });
    const copies = await api(userContext, 'GET', '/agents');
    const agent = copies.find(item => item.default_template_id === source.id); assert(agent);
    const providers = await api(userContext, 'GET', '/providers'); assert(providers[0].default_model);
    const conversation = await api(userContext, 'POST', '/conversations', { agent_id: agent.id, provider_id: providers[0].id, model: providers[0].default_model, control_level: 'observe' });
    const run = await api(userContext, 'POST', `/conversations/${conversation.id}/messages`, { content: 'CrashLoopBackOff', agent_id: agent.id });
    await userPage.goto(base + '/chat/' + conversation.id, { waitUntil: 'networkidle' });
    await userPage.getByText('本地验收已收到角色指令和知识参考。本回复来自受控测试模型，不代表生产检查。', { exact: true }).waitFor();
    const complete = await api(userContext, 'GET', '/runs/' + run.id); assert.equal(complete.run.status, 'completed');
    const overview = await api(adminContext, 'GET', '/admin/overview');
    assert.deepEqual(overview.usage.totals, { agents: 1, knowledge: 1, skills: 1 });
    assert(overview.usage.started_at);
    pass('真实任务按选定智能体、注入技能、命中知识库各登记1次且有统计起点');
    for (const viewport of [{ width: 1366, height: 1000 }, { width: 390, height: 844 }]) {
      await adminPage.setViewportSize(viewport);
      await adminPage.goto(base + '/admin/overview', { waitUntil: 'networkidle' });
      await adminPage.locator('.ea-admin-usage-card[data-usage-kind="agents"] .ea-admin-usage-value').getByText('1 次', { exact: true }).waitFor();
      for (const kind of ['agents', 'knowledge', 'skills']) assert.equal(await adminPage.locator(`.ea-admin-usage-card[data-usage-kind="${kind}"] .ea-admin-usage-value`).innerText(), '1 次');
      for (const [kind, id] of [['agents', source.id], ['knowledge', knowledgeId], ['skills', skillId]]) {
        await adminPage.goto(base + '/admin/' + kind, { waitUntil: 'networkidle' });
        const resource = adminPage.locator(`.ea-admin-resource-card[data-resource-id="${id}"]`);
        await resource.waitFor();
        assert.equal(await resource.locator('.ea-admin-resource-usage-value').innerText(), '1 次');
        assert((await adminPage.locator('.ea-admin-resource-usage-value').filter({ hasText: /^0 次$/ }).count()) > 0);
        const width = await adminPage.evaluate(() => ({ viewport: innerWidth, full: document.documentElement.scrollWidth, scroll: document.querySelector('.route-content').scrollWidth, main: document.querySelector('.route-content').clientWidth }));
        assert(width.full <= width.viewport + 1 && width.scroll <= width.main + 1, JSON.stringify(width));
      }
    }
    pass('管理员三类单资源卡片与概览三块总次数在桌面和390px真实显示');
    await userPage.goto(base + '/knowledge', { waitUntil: 'networkidle' });
    await api(userContext, 'POST', '/knowledge/search', { query: 'CrashLoopBackOff' });
    await userPage.reload({ waitUntil: 'networkidle' });
    const after = await api(adminContext, 'GET', '/admin/overview');
    assert.deepEqual(after.usage.totals, overview.usage.totals);
    pass('页面打开、刷新与手动搜索不会增加任务调用次数');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/usage-browser-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, totals: after.usage.totals, started_at: after.usage.started_at, errors, externalRequests: external, scope: 'isolated data and local fixture completion; no production model or infrastructure calls' }, null, 2) + '\n');
  } finally { await adminContext.close(); await userContext.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
