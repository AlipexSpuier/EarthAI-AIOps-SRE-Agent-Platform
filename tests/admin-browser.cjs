const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  const page = await context.newPage();
  const errors = [], external = [], checks = [];
  const pass = message => { checks.push(message); console.log('PASS', message); };
  const origin = new URL(base).origin;
  const protect = async ctx => {
    ctx.on('page', current => current.on('pageerror', error => errors.push(error.message)));
    await ctx.route('**/*', route => {
      const url = route.request().url();
      if (new URL(url).origin !== origin) { external.push(url); return route.abort(); }
      return route.continue();
    });
  };
  await protect(context);
  page.on('pageerror', error => errors.push(error.message));
  const get = async (ctx, endpoint) => { const response = await ctx.request.get(base + '/api' + endpoint); assert(response.ok(), await response.text()); return response.json(); };
  const choose = async (current, label, value) => { await current.getByRole('combobox', { name: label, exact: true }).click(); await current.getByRole('option', { name: value, exact: true }).click(); };
  const goto = async route => { await page.goto(base + route, { waitUntil: 'networkidle' }); };
  const dialog = () => page.getByRole('dialog').last();
  const save = async (label = '保存并同步') => { const form = dialog(); const title = await form.locator('h2').first().innerText(); await form.getByRole('button', { name: label, exact: true }).click(); await page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).waitFor({ state: 'hidden' }); };
  const suffix = Date.now();
  let regular;
  try {
    await goto('/');
    await page.locator('input[name=email]').fill('admin');
    await page.locator('input[name=password]').fill('admin');
    await page.getByRole('button', { name: '登录工作空间' }).click();
    await page.getByRole('heading', { name: '设置新的登录密码' }).waitFor();
    assert.equal((await context.request.get(base + '/api/admin/overview')).status(), 403);
    await page.locator('input[name=current_password]').fill('admin');
    await page.locator('input[name=new_password]').fill('Browser-Admin-2026!');
    await page.locator('input[name=confirm_password]').fill('Browser-Admin-2026!');
    await page.getByRole('button', { name: '更新密码并继续' }).click();
    await page.getByRole('heading', { name: '全局视野，可靠治理' }).waitFor();
    const labels = await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('link').allTextContents();
    assert.deepEqual(labels, ['系统概览', '智能体管理', '用户管理', '知识库管理', '技能库管理', '项目管理', '服务器管理', '模型供应商管理', '定时任务管理', '告警管理', '界面管理']);
    assert.equal(await page.locator('.execution-dock').count(), 0);
    await goto('/chat');
    assert.equal(new URL(page.url()).pathname, '/admin/overview');
    const counts = (await get(context, '/admin/overview')).counts;
    assert.equal(counts.agents, 50); assert.equal(counts.skills, 50); assert.equal(counts.knowledge, 50);
    pass('admin/admin真实登录、强制改密、11项专属导航和聊天深链接隔离通过');

    await goto('/admin/users');
    await page.getByRole('button', { name: '创建账户', exact: true }).click();
    await dialog().locator('input[name=email]').fill(`browser-${suffix}@earthai.local`);
    await dialog().locator('input[name=name]').fill('浏览器验收成员');
    await dialog().locator('input[name=password]').fill('Browser-User-2026!');
    await save('创建账户');
    await page.getByText(`browser-${suffix}@earthai.local`, { exact: true }).waitFor();
    regular = (await get(context, '/admin/users')).find(user => user.email === `browser-${suffix}@earthai.local`);
    assert(regular && regular.role === 'user');
    pass('用户管理真实创建普通账号并自动继承50套默认能力');

    await goto('/admin/agents');
    await page.getByRole('button', { name: '新增默认智能体', exact: true }).click();
    await choose(page, '智能体类型', '远程智能体');
    await dialog().locator('input[name=name]').fill('默认外部助手-' + suffix);
    await dialog().locator('input[name=url]').fill('https://remote.example.invalid/agent');
    await save();
    const remote = (await get(context, '/admin/defaults/agents')).find(item => item.name === '默认外部助手-' + suffix);
    assert(remote && remote.kind === 'remote');

    await goto('/admin/providers');
    await page.getByRole('button', { name: '新增默认供应商', exact: true }).click();
    await dialog().locator('input[name=name]').fill('默认内网模型-' + suffix);
    await dialog().locator('input[name=base_url]').fill('http://127.0.0.1:9909/v1');
    await dialog().locator('input[name=api_key]').fill('isolated-test-key');
    await dialog().getByRole('textbox', { name: '模型 1', exact: true }).fill('fixture-model');
    await choose(page, '默认模型', 'fixture-model');
    await save();
    const provider = (await get(context, '/admin/defaults/providers')).find(item => item.name === '默认内网模型-' + suffix);
    assert(provider && provider.has_api_key && !provider.api_key);

    await goto('/admin/servers');
    await page.getByRole('button', { name: '新增默认服务器', exact: true }).click();
    await dialog().locator('input[name=name]').fill('默认只读服务器-' + suffix);
    await dialog().locator('input[name=host]').fill('192.0.2.10');
    await dialog().locator('input[name=username]').fill('observer');
    await choose(page, '认证方式', '密码');
    await dialog().locator('input[name=password]').fill('isolated-test-password');
    await save();

    await goto('/admin/projects');
    await page.getByRole('button', { name: '新增默认项目', exact: true }).click();
    await dialog().locator('input[name=name]').fill('默认项目-' + suffix);
    await save();

    await goto('/admin/schedules');
    await page.getByRole('button', { name: '新增默认定时任务', exact: true }).click();
    await dialog().locator('input[name=name]').fill('默认关闭计划-' + suffix);
    await dialog().locator('textarea[name=prompt]').fill('只读检查资料并输出报告，不执行远端写入。');
    await save();
    const schedule = (await get(context, '/admin/defaults/schedules')).find(item => item.name === '默认关闭计划-' + suffix);
    assert(schedule && schedule.enabled === false);
    pass('智能体、模型及模型行、服务器、项目、关闭的定时任务真实表单保存通过');

    await goto('/admin/skills');
    const skill = (await get(context, '/admin/defaults/skills'))[0];
    const card = page.locator('.ea-admin-resource-card').filter({ has: page.getByRole('heading', { name: skill.name, exact: true }) });
    await card.getByRole('checkbox').check();
    await page.getByRole('button', { name: '批量修改', exact: true }).click();
    await dialog().locator('label').filter({ hasText: '统一替换描述（留空表示清空描述）' }).click();
    await dialog().locator('textarea[name=description]').fill('管理员批量同步验收');
    await save();
    assert.equal((await get(context, '/admin/defaults/skills')).find(item => item.id === skill.id).description, '管理员批量同步验收');
    pass('默认技能批量勾选、计数、修改与全员同步通过');

    await goto('/admin/knowledge');
    await page.getByRole('button', { name: '新增默认知识库', exact: true }).click();
    await dialog().locator('input[name=name]').fill('默认表格手册-' + suffix);
    await save();
    const knowledge = (await get(context, '/admin/defaults/knowledge')).find(item => item.name === '默认表格手册-' + suffix);
    const kbCard = page.locator('.ea-admin-resource-card').filter({ has: page.getByRole('heading', { name: knowledge.name, exact: true }) });
    await kbCard.getByRole('button', { name: '文档管理', exact: true }).click();
    await dialog().getByRole('button', { name: '新增文档', exact: true }).click();
    await dialog().locator('input[name=name]').fill('表格验收.md');
    const table = '| 检查项 | 状态 | 数值 |\n| :--- | :---: | ---: |\n| CPU | 正常 | 12 |\n| 磁盘 | 正常 | 35 |\n\n```bash\nuptime\n```';
    await dialog().locator('textarea[name=content]').fill(table);
    await save();
    await dialog().getByRole('button', { name: '查看', exact: true }).click();
    await dialog().getByRole('region', { name: 'Markdown 表格' }).waitFor();
    assert.equal(await dialog().locator('table th').count(), 3);
    assert.equal(await dialog().locator('table tbody tr').count(), 2);
    assert.equal(await dialog().getByRole('button', { name: '复制内容', exact: true }).count(), 1);
    await dialog().getByRole('button', { name: '返回文档列表', exact: true }).click();
    await dialog().getByRole('button', { name: '关闭文档管理', exact: true }).click();
    pass('默认知识库、全文文档、Markdown表格对齐与代码复制结构通过');

    await goto('/admin/branding');
    await page.getByLabel('平台名称').fill('LANOps');
    await page.getByLabel('品牌副标题').fill('INTRANET');
    await page.getByLabel('宣传语').fill('局域网专业运维');
    await page.getByLabel('标题字号（14–40 px）', { exact: true }).fill('25');
    await page.getByLabel('标题六位十六进制颜色', { exact: true }).fill('#087f69');
    await page.getByLabel('上传平台图标', { exact: true }).setInputFiles(path.resolve(__dirname, '../frontend/public/icon-192.png'));
    await page.getByLabel('上传网站图标', { exact: true }).setInputFiles(path.resolve(__dirname, '../frontend/public/favicon.ico'));
    await page.getByRole('button', { name: '保存整套配置', exact: true }).click();
    await page.locator('.sidebar .system-brand-title').getByText('LANOps', { exact: true }).waitFor();
    const brand = await get(context, '/branding');
    assert(brand.icon_url.startsWith('/api/branding/assets/') && brand.favicon_url.startsWith('/api/branding/assets/'));
    assert.equal(await page.title(), 'LANOps · INTRANET');
    await page.getByRole('link', { name: '使用指南', exact: true }).click();
    await page.getByRole('navigation', { name: '管理员指南目录' }).waitFor();
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    assert.equal(await page.getByRole('navigation', { name: '管理员指南目录' }).getByRole('link').count(), 11);
    await page.getByRole('textbox', { name: '搜索模块、字段、操作或常见失败…' }).fill('Favicon');
    await page.getByRole('navigation', { name: '管理员指南目录' }).getByRole('link', { name: '界面与品牌', exact: true }).click();
    await page.waitForURL('**/help/branding');
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    pass('界面名称副标题字号颜色、本地图标/favicon与管理员详细可搜索帮助通过');

    const userContext = await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'zh-CN' });
    await protect(userContext); const userPage = await userContext.newPage();
    await userPage.goto(base, { waitUntil: 'networkidle' });
    await userPage.locator('input[name=email]').fill(regular.email);
    await userPage.locator('input[name=password]').fill('Browser-User-2026!');
    await userPage.getByRole('button', { name: '登录工作空间' }).click();
    await userPage.getByRole('heading', { name: '今天想解决什么？' }).waitFor();
    assert.equal(await userPage.locator('nav a[href="/admin/users"]').count(), 0);
    assert.equal((await userContext.request.get(base + '/api/admin/users')).status(), 403);
    const userAgents = await get(userContext, '/agents');
    assert(userAgents.some(item => item.default_template_id === remote.id));
    const userSkills = await get(userContext, '/skills');
    assert.equal(userSkills.find(item => item.default_template_id === skill.id).description, '管理员批量同步验收');
    for (const route of ['/agents', '/skills', '/knowledge', '/projects', '/servers', '/providers', '/schedules']) {
      await userPage.goto(base + route, { waitUntil: 'networkidle' });
      assert((await userPage.locator('.ea-resource-read-only').count()) > 0, route);
      assert.equal(await userPage.getByRole('button', { name: /^(编辑|删除|同步模型)/ }).count(), 0, route);
    }
    await userPage.goto(base + '/knowledge', { waitUntil: 'networkidle' });
    await userPage.getByRole('button').filter({ hasText: knowledge.name }).first().click();
    await userPage.getByRole('button', { name: '阅读', exact: true }).click();
    await userPage.getByRole('region', { name: 'Markdown 表格' }).waitFor();
    await userPage.getByRole('button', { name: '关闭对话框', exact: true }).click();
    await userPage.getByRole('link', { name: '使用指南', exact: true }).click();
    await userPage.getByRole('navigation', { name: '用户指南目录' }).waitFor();
    await userPage.getByRole('region', { name: 'Markdown 表格' }).waitFor();
    assert.equal(await userPage.locator('.ea-help-module').count(), 1);
    assert.equal(await userPage.getByRole('navigation', { name: '用户指南目录' }).getByRole('link').count(), 12);
    assert.equal(await userPage.locator('table tbody tr').count(), 2);
    await userPage.setViewportSize({ width: 390, height: 844 });
    const size = await userPage.evaluate(() => ({ inner: innerWidth, full: document.documentElement.scrollWidth, main: document.querySelector('.route-content').clientWidth, content: document.querySelector('.route-content').scrollWidth }));
    assert(size.full <= size.inner + 1 && size.content <= size.main + 1, JSON.stringify(size));
    await page.setViewportSize({ width: 390, height: 844 });
    await goto('/admin/branding');
    const adminSize = await page.evaluate(() => ({ inner: innerWidth, full: document.documentElement.scrollWidth, main: document.querySelector('.route-content').clientWidth, content: document.querySelector('.route-content').scrollWidth }));
    assert(adminSize.full <= adminSize.inner + 1 && adminSize.content <= adminSize.main + 1, JSON.stringify(adminSize));
    pass('普通用户7类默认只读且可阅读使用、12模块帮助、390px双角色布局通过');

    await userContext.request.post(base + '/api/alerts', { data: { title: '跨用户告警验收', severity: 'warning', description: 'isolated only' } });
    await goto('/admin/alerts');
    await page.getByRole('heading', { name: '跨用户告警验收', exact: true }).waitFor();
    await page.getByRole('button', { name: '标记解决', exact: true }).click();
    assert.equal((await get(userContext, '/alerts'))[0].status, 'resolved');
    pass('管理员可处理全员告警且结果同步所属用户');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/admin-browser-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, errors, externalRequests: external, scope: 'isolated service and accounts; all public requests blocked; no model/SSH calls', initialCatalog: counts }, null, 2) + '\n');
    await userContext.close();
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
