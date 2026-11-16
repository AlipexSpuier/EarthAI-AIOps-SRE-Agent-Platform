const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const userContext = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } });
  const adminContext = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } });
  const errors = [], external = [], checks = [], measurements = [];
  const pass = message => { checks.push(message); console.log('PASS', message); };
  for (const context of [userContext, adminContext]) {
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== new URL(base).origin) { external.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
  }
  const userPage = await userContext.newPage(), adminPage = await adminContext.newPage();
  const request = async (context, method, endpoint, data) => {
    const response = await context.request.fetch(base + '/api' + endpoint, { method, ...(data === undefined ? {} : { data }) });
    assert(response.ok(), `${method} ${endpoint}: ${await response.text()}`);
    return response.json();
  };
  const goto = (page, endpoint) => page.goto(base + endpoint, { waitUntil: 'networkidle' });
  const saveDialog = async page => {
    const modal = page.getByRole('dialog').last(), title = await modal.locator('h2').first().innerText();
    await page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).getByRole('button', { name: /保存章节|发布章节/, exact: true }).click();
    await page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).waitFor({ state: 'hidden' });
  };
  const independent = async (page, leftSelector, rightSelector, label) => {
    const left = page.locator(leftSelector), right = page.locator(rightSelector), route = page.locator('.route-content');
    await left.waitFor(); await right.waitFor();
    await page.evaluate(({ leftSelector, rightSelector }) => { document.querySelector(leftSelector).scrollTop = 0; document.querySelector(rightSelector).scrollTop = 0; document.querySelector('.route-content').scrollTop = 0; }, { leftSelector, rightSelector });
    const dimensions = await page.evaluate(({ leftSelector, rightSelector }) => {
      const left = document.querySelector(leftSelector), right = document.querySelector(rightSelector), route = document.querySelector('.route-content');
      return { viewport: innerHeight, route: route.clientHeight, routeScroll: route.scrollHeight, left: { client: left.clientHeight, scroll: left.scrollHeight, overflow: getComputedStyle(left).overflowY }, right: { client: right.clientHeight, scroll: right.scrollHeight, overflow: getComputedStyle(right).overflowY }, width: innerWidth, document: document.documentElement.scrollWidth };
    }, { leftSelector, rightSelector });
    assert(dimensions.left.client > 70 && dimensions.right.client > 70, JSON.stringify(dimensions));
    assert(dimensions.left.scroll > dimensions.left.client && dimensions.right.scroll > dimensions.right.client, JSON.stringify(dimensions));
    assert(['auto', 'scroll'].includes(dimensions.left.overflow) && ['auto', 'scroll'].includes(dimensions.right.overflow), JSON.stringify(dimensions));
    assert(dimensions.document <= dimensions.width + 1, JSON.stringify(dimensions));
    assert(dimensions.routeScroll <= dimensions.route + 1, label + ': resource count must not lengthen route');
    await left.evaluate(element => { element.scrollTop = 150; });
    assert((await left.evaluate(element => element.scrollTop)) > 0);
    assert.equal(await right.evaluate(element => element.scrollTop), 0, label + ': left cannot move right');
    assert.equal(await route.evaluate(element => element.scrollTop), 0, label + ': left cannot move page');
    const leftTop = await left.evaluate(element => element.scrollTop);
    await right.evaluate(element => { element.scrollTop = 160; });
    assert((await right.evaluate(element => element.scrollTop)) > 0);
    assert.equal(await left.evaluate(element => element.scrollTop), leftTop, label + ': right cannot move left');
    assert.equal(await route.evaluate(element => element.scrollTop), 0, label + ': right cannot move page');
    measurements.push({ label, ...dimensions });
  };
  try {
    const suffix = Date.now();
    await request(userContext, 'POST', '/auth/register', { email: 'libraries-' + suffix + '@earthai.local', password: 'Library-User-2026!', name: '目录与指南验收' });
    const longContent = Array.from({ length: 180 }, (_, index) => `${index + 1}. 检查证据和恢复条件，禁止未经批准的变更。`).join('\n');
    await request(userContext, 'POST', '/skills', { name: '独立滚动长技能', description: '长正文验收', content: longContent, enabled: true });
    const knowledge = await request(userContext, 'POST', '/knowledge', { name: '独立滚动知识库', description: 'catalog-filter-unique' });
    for (let index = 0; index < 35; index++) {
      const response = await userContext.request.post(base + `/api/knowledge/${knowledge.id}/documents`, { multipart: { file: { name: `手册-${index}.md`, mimeType: 'text/markdown', buffer: Buffer.from(`# 检查手册${index}\n\n目录验收正文 searchablecatalogtoken\n` + longContent.slice(0, 180)) } } });
      assert(response.ok(), await response.text());
    }
    await goto(userPage, '/skills');
    await userPage.locator('.skill-list button').filter({ hasText: '独立滚动长技能' }).click();
    await userPage.locator('.skill-document').getByText('独立滚动长技能', { exact: true }).waitFor();
    await independent(userPage, '.skill-list', '.skill-document', '1440px技能库');
    await goto(userPage, '/knowledge');
    const directorySearch = userPage.getByRole('textbox', { name: '查找知识库名称或描述…', exact: true });
    await directorySearch.fill('catalog-filter-unique');
    const sidebar = userPage.locator('.knowledge-sidebar');
    assert.equal(await sidebar.getByRole('button').count(), 1);
    await sidebar.getByRole('button').first().click();
    await userPage.locator('.knowledge-heading').getByRole('heading', { name: '独立滚动知识库', exact: true }).waitFor();
    await directorySearch.fill('');
    await independent(userPage, '.knowledge-sidebar', '.knowledge-main', '1440px知识库');
    const originalTitle = await userPage.locator('.knowledge-heading h2').innerText();
    await directorySearch.fill('没有匹配知识库xyz');
    assert.equal(await sidebar.locator(':scope > button').count(), 0);
    assert.equal(await userPage.locator('.knowledge-heading h2').innerText(), originalTitle);
    await directorySearch.fill('');
    await userPage.getByRole('textbox', { name: '知识库检索关键词', exact: true }).fill('searchablecatalogtoken');
    await userPage.getByRole('button', { name: /全文检索/ }).click();
    await userPage.locator('.search-result-card').first().waitFor();
    assert.equal(await sidebar.getByRole('button').count(), 51);
    await directorySearch.fill('catalog-filter-unique');
    assert.equal(await sidebar.getByRole('button').count(), 1);
    assert((await userPage.locator('.search-result-card').count()) > 0);
    await directorySearch.fill('');
    pass('目录按知识库名称/描述查找，保留当前阅读与库内全文结果，零命中可恢复');
    await goto(userPage, '/knowledge');
    await userPage.locator('.knowledge-sidebar button').filter({ hasText: '独立滚动知识库' }).click();
    for (const viewport of [{ width: 1024, height: 768 }, { width: 390, height: 844 }]) {
      await userPage.setViewportSize(viewport);
      await independent(userPage, '.knowledge-sidebar', '.knowledge-main', `${viewport.width}px知识库`);
      await goto(userPage, '/skills');
      await userPage.locator('.skill-list button').filter({ hasText: '独立滚动长技能' }).click();
      await independent(userPage, '.skill-list', '.skill-document', `${viewport.width}px技能库`);
      await goto(userPage, '/knowledge');
      await userPage.locator('.knowledge-sidebar button').filter({ hasText: '独立滚动知识库' }).click();
    }
    pass('50项目录和长正文/35份文档在桌面、平板及390px均左右或上下独立滚动，不撑成长页');
    assert.equal(await userPage.locator('.topbar-help-link span').innerText(), '使用指南');
    await request(adminContext, 'POST', '/auth/login', { email: 'admin', password: 'admin' });
    await request(adminContext, 'POST', '/auth/password', { current_password: 'admin', new_password: 'Library-Admin-2026!' });
    await goto(adminPage, '/help');
    await adminPage.getByRole('link', { name: '管理使用指南', exact: true }).click();
    await adminPage.waitForURL('**/admin/guides');
    assert.equal(await adminPage.locator('.topbar-help-link span').innerText(), '使用指南');
    pass('双角色顶栏问号旁可见使用指南文字，管理员从帮助页集中进入维护');
    const roles = ['admin', 'user'];
    for (const role of roles) {
      await adminPage.getByRole('tab', { name: role === 'admin' ? '管理员指南' : '普通用户指南', exact: true }).click();
      await adminPage.getByRole('button', { name: '新建章节', exact: true }).click();
      const modal = adminPage.getByRole('dialog').last();
      await modal.locator('input[name=id]').fill('browser-' + role);
      await modal.locator('input[name=title]').fill(role === 'admin' ? '管理员自定义指南' : '用户自定义指南');
      await modal.locator('textarea[name=summary]').fill('新增、阅读、编辑与删除验收');
      await modal.locator('textarea[name=content]').fill('## 自定义操作\n\n1. 明确目标。\n2. 验证证据。\n\n| 项目 | 状态 |\n| --- | --- |\n| 指南 | 可维护 |');
      await saveDialog(adminPage);
      const entries = await request(adminContext, 'GET', '/admin/guides?audience=' + role);
      assert(entries.some(item => item.id === 'browser-' + role));
      const row = adminPage.locator('[data-guide-id="browser-' + role + '"]');
      await row.getByRole('button', { name: /编辑/ }).click();
      await adminPage.getByRole('dialog').last().locator('textarea[name=content]').fill('## 修订指南\n\n本次修订已保存，可在独立页阅读。');
      await saveDialog(adminPage);
      const reader = role === 'admin' ? adminPage : userPage;
      await goto(reader, '/help/browser-' + role);
      await reader.getByText('本次修订已保存，可在独立页阅读。', { exact: true }).waitFor();
      assert.equal(await reader.locator('.ea-help-module').count(), 1);
      await reader.reload({ waitUntil: 'networkidle' });
      await reader.getByText('本次修订已保存，可在独立页阅读。', { exact: true }).waitFor();
      if (role === 'user') assert.equal(await reader.getByRole('link', { name: '管理使用指南', exact: true }).count(), 0);
      await goto(adminPage, '/admin/guides');
      await adminPage.setViewportSize({ width: 390, height: 844 });
      const managerWidth = await adminPage.evaluate(() => ({ width: innerWidth, full: document.documentElement.scrollWidth }));
      assert(managerWidth.full <= managerWidth.width + 1, JSON.stringify(managerWidth));
      await adminPage.setViewportSize({ width: 1440, height: 1000 });
      await adminPage.getByRole('tab', { name: role === 'admin' ? '管理员指南' : '普通用户指南', exact: true }).click();
      await adminPage.locator('[data-guide-id="browser-' + role + '"]').getByRole('button', { name: /删除/ }).click();
      await adminPage.getByRole('button', { name: '确认操作', exact: true }).click();
      await adminPage.locator('[data-guide-id="browser-' + role + '"]').waitFor({ state: 'detached' });
      assert(!(await request(adminContext, 'GET', '/admin/guides?audience=' + role)).some(item => item.id === 'browser-' + role));
    }
    pass('管理员真实新增/编辑/删除两套指南，对应角色刷新可读且普通用户无管理权限');
    assert.equal((await userContext.request.get(base + '/api/admin/guides?audience=user')).status(), 403);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/library-guides-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, measurements, errors, externalRequests: external, scope: 'isolated user/admin and local data; all external browser requests blocked; no model or infrastructure calls' }, null, 2) + '\n');
  } finally { await userContext.close(); await adminContext.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
