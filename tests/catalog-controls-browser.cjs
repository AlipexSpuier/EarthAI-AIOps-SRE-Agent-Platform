const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const origin = new URL(base).origin;
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const admin = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 960 } });
  const user = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 960 } });
  const errors = [], external = [], checks = [];
  const pass = text => { checks.push(text); console.log('PASS', text); };
  for (const context of [admin, user]) {
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== origin) { external.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
  }
  const adminPage = await admin.newPage(), userPage = await user.newPage();
  const request = (context, method, endpoint, data) => context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }) });
  const api = async (context, method, endpoint, data) => {
    const response = await request(context, method, endpoint, data); assert(response.ok(), `${method} ${endpoint}: ${await response.text()}`); return response.json();
  };
  const widthCheck = async page => {
    const value = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth, route: document.querySelector('.route-content').scrollWidth, routeWidth: document.querySelector('.route-content').clientWidth }));
    assert(value.document <= value.width + 1 && value.route <= value.routeWidth + 1, JSON.stringify(value));
  };
  const selectAll = async (dialog, field, expected) => {
    const group = dialog.locator(`[data-multi-select="${field}"]`);
    await group.waitFor();
    await group.locator(`input[name="${field}"]`).first().waitFor();
    assert.equal(await group.locator(`input[name="${field}"]`).count(), expected);
    await group.locator('.multi-select-all').click();
    assert.equal(await group.locator(`input[name="${field}"]:checked:not(:disabled)`).count(), expected);
  };
  try {
    await api(admin, 'POST', '/auth/login', { email: 'admin', password: 'admin' });
    await api(admin, 'POST', '/auth/password', { current_password: 'admin', new_password: 'Catalog-Admin-2026!' });
    const skills = await api(admin, 'GET', '/admin/defaults/skills');
    const libraries = await api(admin, 'GET', '/admin/defaults/knowledge');
    assert.equal(skills.length, 100); assert.equal(libraries.length, 50);
    const docCounts = libraries.map(library => library.document_count);
    assert(docCounts.every(count => count >= 3 && count <= 12));
    const addedSkills = skills.filter(skill => skill.builtin_key?.startsWith('earthai.skills.supplement-v1.'));
    assert.equal(addedSkills.length, 50); assert(addedSkills.every(skill => skill.content.length > 500));
    const selectedLibrary = libraries.find(library => library.builtin_domain === 'pod-troubleshooting'); assert(selectedLibrary);
    const documents = await api(admin, 'GET', `/admin/defaults/knowledge/${selectedLibrary.id}/documents`);
    assert(documents.some(doc => doc.name.includes('专题参考')));
    pass('默认技能增至100，50库保留原文并各追加1–10篇有正文的专题文档');

    const higher = await api(admin, 'POST', '/admin/defaults/agents', { name: '审批授权灰显验收', kind: 'local', system_prompt: '仅解释资料，遵守授权。', control_level: 'approve' });
    const higherSchedule = await api(admin, 'POST', '/admin/defaults/schedules', { name: '审批调度灰显验收', prompt: '解释资料', control_level: 'approve', agent_id: higher.id, cron: '0 9 * * *', enabled: false });
    await api(admin, 'POST', '/admin/defaults/providers', { name: '受控目录模型', base_url: 'http://127.0.0.1:9909/v1', api_key: 'local-catalog' });
    await adminPage.goto(base + '/admin/users', { waitUntil: 'networkidle' });
    await adminPage.getByRole('button', { name: '创建账户', exact: true }).click();
    const userForm = adminPage.getByRole('dialog');
    const grants = userForm.locator('.ea-admin-control-levels input[name="allowed_control_levels"]');
    assert.equal(await grants.count(), 3);
    assert.equal(await userForm.locator('input[name="allowed_control_levels"][value="observe"]').isChecked(), true);
    assert.equal(await userForm.locator('input[name="allowed_control_levels"][value="approve"]').isChecked(), false);
    assert.equal(await userForm.locator('input[name="allowed_control_levels"][value="autonomous"]').isChecked(), false);
    await userForm.locator('input[name="name"]').fill('观察授权验收用户');
    await userForm.locator('input[name="email"]').fill('catalog-observer@earthai.local');
    await userForm.locator('input[name="password"]').fill('Catalog-User-2026!');
    await userForm.getByRole('button', { name: '创建账户', exact: true }).click();
    await userForm.waitFor({ state: 'hidden' });
    const account = (await api(admin, 'GET', '/admin/users')).find(item => item.email === 'catalog-observer@earthai.local'); assert(account);
    assert.deepEqual(account.allowed_control_levels, ['observe']);
    const logged = await api(user, 'POST', '/auth/login', { email: account.email, password: 'Catalog-User-2026!' });
    assert.deepEqual(logged.allowed_control_levels, ['observe']);
    const highCopy = (await api(user, 'GET', '/agents')).find(item => item.default_template_id === higher.id); assert(highCopy);
    const scheduleCopy = (await api(user, 'GET', '/schedules')).find(item => item.default_template_id === higherSchedule.id); assert(scheduleCopy);
    assert.equal((await request(user, 'POST', '/conversations', { agent_id: highCopy.id, control_level: 'observe' })).status(), 403);
    assert.equal((await request(user, 'POST', `/schedules/${scheduleCopy.id}/run`)).status(), 403);
    assert.equal((await request(user, 'POST', '/agents/import', { items: [{ name: '不能越权导入', control_level: 'autonomous' }] })).status(), 403);
    pass('管理端新用户默认仅观察；外层观察关联高权限智能体、手动调度和JSON越权均被接口拒绝');

    for (const viewport of [{ width: 1366, height: 960 }, { width: 390, height: 844 }]) {
      await userPage.setViewportSize(viewport);
      await userPage.goto(base + '/agents', { waitUntil: 'networkidle' });
      const blockedAgent = userPage.locator(`[data-agent-id="${highCopy.id}"]`);
      assert.equal(await blockedAgent.getAttribute('data-control-blocked'), 'true');
      assert.equal(await blockedAgent.getByRole('button', { name: '与它对话' }).isDisabled(), true);
      await widthCheck(userPage);
      await userPage.goto(base + '/schedules', { waitUntil: 'networkidle' });
      assert.equal(await userPage.locator(`[data-schedule-id="${scheduleCopy.id}"]`).getByRole('button', { name: '立即运行', exact: true }).isDisabled(), true);
      await userPage.goto(base + '/settings', { waitUntil: 'networkidle' });
      assert.equal(await userPage.locator('input[name="level"]').nth(0).isDisabled(), false);
      assert.equal(await userPage.locator('input[name="level"]').nth(1).isDisabled(), true);
      assert.equal(await userPage.locator('input[name="level"]').nth(2).isDisabled(), true);
      await userPage.goto(base + '/chat', { waitUntil: 'networkidle' });
      await userPage.getByRole('combobox', { name: '控制等级', exact: true }).click();
      const denied = userPage.getByRole('option', { name: '审批模式', exact: true });
      assert.equal(await denied.getAttribute('aria-disabled'), 'true');
      await userPage.keyboard.press('Escape');
      await widthCheck(userPage);
    }
    pass('桌面和390px中未授模式、关联智能体与调度入口灰显，观察配置可用且无横向溢出');

    for (const [context, page, prefix] of [[user, userPage, ''], [admin, adminPage, '/admin']]) {
      await page.setViewportSize({ width: 1366, height: 960 });
      await page.goto(base + prefix + '/agents', { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: prefix ? '新增默认智能体' : '创建智能体', exact: true }).click();
      let dialog = page.getByRole('dialog');
      await selectAll(dialog, 'skill_ids', 100); await selectAll(dialog, 'knowledge_ids', 50);
      await dialog.locator('[data-multi-select="skill_ids"] .multi-select-clear').click();
      assert.equal(await dialog.locator('input[name="skill_ids"]:checked').count(), 0);
      assert.equal(await dialog.locator('input[name="knowledge_ids"]:checked').count(), 50);
      await dialog.getByRole('button', { name: '取消', exact: true }).click();
      await page.goto(base + prefix + '/projects', { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: prefix ? '新增默认项目' : '创建项目', exact: true }).click();
      dialog = page.getByRole('dialog');
      await selectAll(dialog, 'skill_ids', 100); await selectAll(dialog, 'knowledge_ids', 50);
      await dialog.locator('input[name="name"]').fill(prefix ? '管理员全选项目' : '用户全选项目');
      await dialog.getByRole('button', { name: prefix ? '保存并同步' : '保存', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      const values = await api(context, 'GET', prefix ? '/admin/defaults/projects' : '/projects');
      const created = values.find(item => item.name === (prefix ? '管理员全选项目' : '用户全选项目'));
      assert(created); assert.equal(created.skill_ids.length, 100); assert.equal(created.knowledge_ids.length, 50);
    }
    pass('管理员和用户的智能体/项目关联均支持全选和独立清空，项目技能和知识关联真实保存');

    const routes = { agents: '/agents', skills: '/skills', knowledge: '/knowledge', projects: '/projects', servers: '/servers', providers: '/providers', schedules: '/schedules', alerts: '/alerts' };
    for (const [kind, route] of Object.entries(routes)) {
      await userPage.goto(base + route, { waitUntil: 'networkidle' });
      await userPage.locator(`[data-user-import-trigger="${kind}"]`).click();
      await userPage.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    }
    await userPage.goto(base + '/skills', { waitUntil: 'networkidle' });
    await userPage.locator('[data-user-import-trigger="skills"]').click();
    const importForm = userPage.getByRole('dialog');
    await importForm.getByLabel('JSON 内容', { exact: true }).fill(JSON.stringify([{ name: '观察用户导入一', content: '先确认目标，只读收集证据。' }, { name: '观察用户导入二', content: '复核证据并输出待办。' }]));
    await importForm.getByRole('button', { name: '确认导入', exact: true }).click();
    await importForm.waitFor({ state: 'hidden' });
    assert((await api(user, 'GET', '/skills')).some(item => item.name === '观察用户导入二'));
    pass('八类用户JSON入口可用，观察用户可原子导入自己有权创建的资源');

    await adminPage.goto(base + '/admin/users', { waitUntil: 'networkidle' });
    const accountCard = adminPage.locator('.ea-admin-user-row').filter({ hasText: account.email });
    await accountCard.getByRole('button', { name: '编辑', exact: true }).click();
    const edit = adminPage.getByRole('dialog');
    await edit.locator('input[name="allowed_control_levels"][value="approve"]').check();
    await edit.getByRole('button', { name: '保存账户', exact: true }).click(); await edit.waitFor({ state: 'hidden' });
    assert.deepEqual((await api(user, 'GET', '/auth/me')).allowed_control_levels, ['observe', 'approve']);
    await userPage.goto(base + '/chat', { waitUntil: 'networkidle' });
    const refreshed = userPage.waitForResponse(response => response.url().endsWith('/api/auth/me'));
    await userPage.evaluate(() => window.dispatchEvent(new Event('focus')));
    await refreshed;
    await userPage.getByRole('combobox', { name: '控制等级', exact: true }).click();
    assert.notEqual(await userPage.getByRole('option', { name: '审批模式', exact: true }).getAttribute('aria-disabled'), 'true');
    await userPage.keyboard.press('Escape');
    pass('管理员编辑授权后，用户焦点刷新可选择新授权模式，不需要修改资源或伪造权限');
    const secondAccount = await api(admin, 'POST', '/admin/users', { email: 'catalog-second@earthai.local', name: '批量授权对照用户', password: 'Catalog-Second-2026!' });
    await adminPage.goto(base + '/admin/users', { waitUntil: 'networkidle' });
    await adminPage.getByRole('checkbox', { name: '选择账户 ' + account.email, exact: true }).check();
    await adminPage.getByRole('checkbox', { name: '选择账户 ' + secondAccount.email, exact: true }).check();
    await adminPage.getByRole('button', { name: '批量角色 / 启停 / 授权', exact: true }).click();
    const batch = adminPage.getByRole('dialog');
    assert.equal(await batch.locator('input[name="allowed_control_levels"][value="observe"]').isDisabled(), true);
    await batch.getByText('统一修改授权控制模式', { exact: true }).click();
    await batch.locator('input[name="allowed_control_levels"][value="approve"]').check();
    await batch.getByRole('button', { name: '保存账户变更', exact: true }).click(); await batch.waitFor({ state: 'hidden' });
    const batchResult = await api(admin, 'GET', '/admin/users');
    for (const id of [account.id, secondAccount.id]) assert.deepEqual(batchResult.find(item => item.id === id).allowed_control_levels, ['observe', 'approve']);
    pass('批量修改授权开关默认保持不变，启用后能一次替换多个账户的执行模式授权');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/catalog-control-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, initialInventory: { skills: 100, knowledge: 50, knowledgeDocuments: docCounts.reduce((sum, count) => sum + count, 0), perLibraryDocuments: docCounts }, pageErrors: errors, externalRequests: external, scope: 'isolated data, local catalog/completion fixtures; no paid models, NAS or infrastructure calls' }, null, 2) + '\n');
  } finally { await Promise.all([admin.close(), user.close()]); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
