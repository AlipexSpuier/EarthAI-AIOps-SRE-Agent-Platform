const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const fixture = process.env.EARTHAI_CATALOG_URL || 'http://127.0.0.1:9909';
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 1000 } });
  const page = await context.newPage();
  const checks = [], errors = [], external = [], styles = [];
  const pass = value => { checks.push(value); console.log('PASS', value); };
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== new URL(base).origin) { external.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  const get = async endpoint => { const response = await context.request.get(base + '/api' + endpoint); assert(response.ok(), await response.text()); return response.json(); };
  const goto = async route => { await page.goto(base + route, { waitUntil: 'networkidle' }); };
  const switchTheme = async theme => { await context.request.patch(base + '/api/auth/me', { data: { theme } }); await page.reload({ waitUntil: 'networkidle' }); assert.equal(await page.locator('html').getAttribute('data-theme'), theme); };
  const style = async locator => locator.evaluate(async element => {
    getComputedStyle(element).borderColor;
    await Promise.all(element.getAnimations().filter(animation => Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation => animation.finished.catch(() => undefined)));
    const value = getComputedStyle(element);
    return { border: value.borderColor, width: value.borderWidth, outline: value.outlineStyle, shadow: value.boxShadow };
  });
  const checkInput = async (locator, label, outer) => {
    await page.mouse.move(0, 0); await locator.evaluate(element => element.blur());
    const start = await style(locator), outside = outer ? await style(outer) : null;
    await locator.focus(); await page.keyboard.type('a');
    const focused = await style(locator), surrounding = outer ? await style(outer) : null;
    assert.equal(focused.outline, 'none', label + ': no inner outline');
    assert.equal(focused.border, start.border, label + ': stable border');
    if (surrounding) {
      assert.equal(surrounding.border, outside.border, label + ': stable outer border');
      assert.notEqual(surrounding.shadow, 'none', label + ': outer shadow retained');
    } else assert.notEqual(focused.shadow, 'none', label + ': focus shadow retained');
    await locator.fill(''); styles.push({ label, theme: await page.locator('html').getAttribute('data-theme'), focused, surrounding });
  };
  const checkSelect = async (locator, label) => {
    await locator.evaluate(element => element.blur());
    const initial = await style(locator);
    await locator.focus();
    const focused = await style(locator);
    assert.equal(focused.outline, 'none', label + ': no outline');
    assert.equal(focused.border, initial.border, label + ': border unchanged');
    assert.notEqual(focused.shadow, 'none', label + ': shadow retained');
    styles.push({ label, theme: await page.locator('html').getAttribute('data-theme'), focused });
  };
  const saveDialog = async () => {
    const modal = page.getByRole('dialog').last(); const title = await modal.locator('h2').first().innerText();
    await modal.getByRole('button', { name: '保存并同步', exact: true }).click();
    await page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).waitFor({ state: 'hidden' });
  };
  const createProvider = async (administrator, name, mode) => {
    const endpoint = administrator ? '/admin/defaults/providers' : '/providers';
    await goto(administrator ? '/admin/providers' : '/providers');
    await page.getByRole('button', { name: administrator ? '新增默认供应商' : '添加供应商', exact: true }).click();
    const modal = page.getByRole('dialog').last();
    await modal.locator('input[name=name]').fill(name);
    await modal.locator('input[name=base_url]').fill(fixture + '/' + mode);
    await modal.locator('input[name=api_key]').fill('isolated-local-token');
    const defaultModel = administrator ? modal.getByRole('combobox', { name: '默认模型', exact: true }) : modal.locator('input[name=default_model]');
    assert.equal(await defaultModel.getAttribute('required'), null);
    const requestsBefore = (await context.request.get(fixture + '/checks')).ok(); assert(requestsBefore);
    const before = await (await context.request.get(fixture + '/checks')).json();
    if (administrator) await saveDialog();
    else { await modal.getByRole('button', { name: '保存', exact: true }).click(); await modal.waitFor({ state: 'hidden' }); }
    const provider = (await get(endpoint)).find(value => value.name === name); assert(provider);
    const after = await (await context.request.get(fixture + '/checks')).json();
    assert.equal((after[mode] || 0) - (before[mode] || 0), 1, 'one catalog call per creation');
    const card = page.locator(administrator ? '.ea-admin-resource-card' : '.provider-card').filter({ hasText: name });
    if (mode === 'v1') {
      assert.equal(provider.default_model, 'first-local-model');
      assert.deepEqual(provider.models, ['first-local-model', 'second-local-model']);
      assert.equal(provider.model_sync.status, 'ok');
      await card.getByText('first-local-model', { exact: true }).first().waitFor();
    } else {
      assert.equal(provider.model_sync.status, mode === 'failed' ? 'error' : 'empty');
      assert.equal(provider.default_model, '');
      await card.getByText(/模型同步失败|未返回可用模型/).first().waitFor();
      assert.equal(await card.getByRole('button', { name: '同步模型', exact: true }).count(), 1);
    }
    return provider;
  };
  async function checkHelp(administrator) {
    await page.getByRole('link', { name: '使用指南', exact: true }).click();
    const first = administrator ? 'overview' : 'chat';
    await page.waitForURL('**/help/' + first);
    const menu = page.getByRole('navigation', { name: administrator ? '管理员指南目录' : '用户指南目录' });
    await page.locator('.ea-help-module').waitFor();
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    assert.equal(await menu.getByRole('link').count(), administrator ? 11 : 12);
    const links = await menu.getByRole('link').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
    for (const href of links) {
      await menu.locator(`a[href="${href}"]`).click();
      assert.equal(new URL(page.url()).pathname, href);
      assert.equal(await page.locator('.ea-help-module').count(), 1);
    }
    await page.goto(base + '/help/providers', { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(new URL(page.url()).pathname, '/help/providers');
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    await menu.locator('a[href="/help/agents"]').click();
    await page.goBack({ waitUntil: 'networkidle' });
    assert.equal(new URL(page.url()).pathname, '/help/providers');
    await page.goForward({ waitUntil: 'networkidle' });
    assert.equal(new URL(page.url()).pathname, '/help/agents');
    const search = page.getByRole('textbox', { name: '搜索模块、字段、操作或常见失败…' });
    await search.fill('Favicon');
    if (administrator) { await menu.getByRole('link', { name: '界面与品牌', exact: true }).click(); assert.equal(new URL(page.url()).pathname, '/help/branding'); }
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    await search.fill('不存在的专有关键词XYZ');
    await page.getByRole('heading', { name: '没有匹配的指南模块' }).waitFor();
    assert.equal(await page.locator('.ea-help-module').count(), 1);
    await search.fill('');
    await page.setViewportSize({ width: 390, height: 844 });
    const width = await page.evaluate(() => ({ full: document.documentElement.scrollWidth, inner: innerWidth, main: document.querySelector('.route-content').clientWidth, scroll: document.querySelector('.route-content').scrollWidth }));
    assert(width.full <= width.inner + 1 && width.scroll <= width.main + 1, JSON.stringify(width));
    await page.setViewportSize({ width: 1366, height: 1000 });
    pass((administrator ? '管理员11' : '普通用户12') + '个帮助章节独立URL、单节DOM、刷新/历史/搜索/移动端通过');
  }
  try {
    await goto('/');
    for (const register of [false, true]) {
      if (register) await page.getByRole('button', { name: '免费创建账户', exact: true }).click();
      const input = page.locator('input[name=password]');
      await input.fill('Secret-Only-One-Eye!');
      assert.equal(await page.locator('.password-input button').count(), 1);
      assert.equal(await input.getAttribute('type'), 'password');
      await page.getByRole('button', { name: '显示密码', exact: true }).click();
      assert.equal(await input.getAttribute('type'), 'text');
      await page.getByRole('button', { name: '隐藏密码', exact: true }).click();
      assert.equal(await input.getAttribute('type'), 'password');
      for (const theme of ['light', 'dark']) {
        await page.locator('html').evaluate((element, value) => { element.dataset.theme = value; }, theme);
        await checkInput(page.locator('input[name=email]'), register ? '注册账号' : '登录账号');
        await checkInput(input, register ? '注册密码' : '登录密码', page.locator('.password-input'));
      }
    }
    pass('登录/注册保留单个可用密码按钮，输入框无彩色描边且原阴影保留');
    await page.getByRole('button', { name: '返回登录', exact: true }).click();
    await page.locator('input[name=email]').fill('admin'); await page.locator('input[name=password]').fill('admin');
    await page.getByRole('button', { name: '登录工作空间', exact: true }).click();
    await page.locator('input[name=current_password]').fill('admin'); await page.locator('input[name=new_password]').fill('UI-Admin-2026!'); await page.locator('input[name=confirm_password]').fill('UI-Admin-2026!');
    await page.getByRole('button', { name: '更新密码并继续', exact: true }).click();
    await page.getByRole('heading', { name: '全局视野，可靠治理' }).waitFor();
    await checkHelp(true);
    for (const theme of ['light', 'dark']) {
      await switchTheme(theme);
      await checkInput(page.getByRole('textbox', { name: '搜索模块、字段、操作或常见失败…' }), '管理员帮助搜索', page.locator('.search-input'));
      await goto('/admin/users');
      await checkInput(page.getByRole('textbox', { name: '搜索账户或姓名…' }), '管理员列表搜索', page.locator('.search-input'));
      await page.getByRole('button', { name: '创建账户', exact: true }).click();
      await checkInput(page.getByRole('dialog').locator('input[name=name]'), '管理员表单名称');
      await checkSelect(page.getByRole('dialog').getByRole('combobox', { name: '账户角色', exact: true }), '管理员角色选择器');
      await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
      await goto('/help/overview');
    }
    await createProvider(true, '管理员自动同步', 'v1');
    await createProvider(true, '管理员失败保留', 'failed');
    pass('管理员新增供应商无需模型，仅一次目录同步并默认首模型；失败配置保留可重试');
    await context.request.post(base + '/api/auth/logout');
    await goto('/');
    await page.getByRole('button', { name: '免费创建账户', exact: true }).click();
    await page.locator('input[name=email]').fill('ui-' + Date.now() + '@earthai.local');
    await page.locator('input[name=name]').fill('界面验收成员');
    await page.locator('input[name=password]').fill('UI-User-2026!');
    await page.getByRole('button', { name: '创建账户', exact: true }).click();
    await page.getByRole('heading', { name: '今天想解决什么？' }).waitFor();
    await checkHelp(false);
    for (const theme of ['light', 'dark']) {
      await switchTheme(theme);
      await checkInput(page.getByRole('textbox', { name: '搜索模块、字段、操作或常见失败…' }), '用户帮助搜索', page.locator('.search-input'));
      await goto('/providers');
      await checkInput(page.getByRole('textbox', { name: '搜索供应商…' }), '用户供应商搜索', page.locator('.search-input'));
      await page.getByRole('button', { name: '添加供应商', exact: true }).click();
      await checkInput(page.getByRole('dialog').locator('input[name=name]'), '用户供应商表单');
      await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
      await goto('/help/chat');
    }
    await createProvider(false, '用户自动同步', 'v1');
    await createProvider(false, '用户空目录保留', 'empty');
    pass('普通用户新增供应商无需默认模型，自动同步首模型与空目录提示通过');
    const cssLinks = await page.locator('link[rel="stylesheet"]').evaluateAll(nodes => nodes.map(node => node.href));
    const cssTexts = await Promise.all(cssLinks.filter(url => new URL(url).origin === new URL(base).origin).map(async url => (await context.request.get(url)).text()));
    assert(cssTexts.some(css => /::-ms-reveal/.test(css) && /display\s*:\s*none/.test(css)));
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.resolve(__dirname, '../docs/ui-refinements-verification.json'), JSON.stringify({ ok: true, at: new Date().toISOString(), checks, styles, pageErrors: errors, externalRequests: external, scope: 'isolated account and local catalog fixture; no paid model or SSH requests', passwordNativeRevealRule: true }, null, 2) + '\n');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
