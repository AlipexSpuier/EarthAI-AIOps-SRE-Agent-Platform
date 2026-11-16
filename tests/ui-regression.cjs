const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const out = path.resolve(__dirname, '../docs');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1, locale: 'zh-CN' });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  const measured = [];
  const pass = name => { checks.push(name); console.log('PASS', name); };
  page.on('pageerror', error => errors.push(error.message));
  async function api(endpoint, data) {
    const response = await context.request.post(`${base}/api/${endpoint}`, { data });
    assert(response.ok(), `${endpoint}: ${await response.text()}`);
    return response.json();
  }
  async function measure(label, requireNoScroll = false) {
    const data = await page.evaluate(() => {
      const root = document.documentElement;
      const route = document.querySelector('.route-content');
      const sidebar = document.querySelector('.sidebar');
      const scrolls = [...document.querySelectorAll('*')].filter(el => {
        const rect = el.getBoundingClientRect(); const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && rect.right > 0 && style.visibility !== 'hidden' &&
          ((/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2) || (/(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 2));
      }).map(el => ({ tag: el.tagName, class: el.className, x: el.scrollWidth > el.clientWidth + 2, y: el.scrollHeight > el.clientHeight + 2 }));
      return { viewport: [innerWidth, innerHeight], document: [root.scrollWidth, root.scrollHeight], routeOverflow: route.scrollWidth - route.clientWidth, scrolls, sidebarHeight: sidebar?.getBoundingClientRect().height };
    });
    assert(data.document[0] <= data.viewport[0] + 1, `${label} document horizontal overflow: ${JSON.stringify(data)}`);
    assert(data.document[1] <= data.viewport[1] + 1, `${label} document vertical overflow: ${JSON.stringify(data)}`);
    assert(data.routeOverflow <= 1, `${label} route horizontal overflow: ${JSON.stringify(data)}`);
    assert(!data.scrolls.some(item => item.x), `${label} horizontal scroll container: ${JSON.stringify(data)}`);
    if (requireNoScroll) assert.equal(data.scrolls.length, 0, `${label} unnecessary scroll: ${JSON.stringify(data)}`);
    measured.push({ label, ...data });
  }
  async function checkMenu(label, option, searchable = false) {
    const trigger = page.getByRole('combobox', { name: label, exact: true });
    const before = await page.locator('.composer').boundingBox();
    await trigger.click();
    const popup = page.locator('.ea-select-popup');
    await popup.waitFor();
    const bounds = await trigger.boundingBox();
    const menu = await popup.boundingBox();
    assert(menu.x >= 11 && menu.x + menu.width <= (await page.viewportSize()).width - 11, `${label}: popup outside viewport`);
    assert(menu.y >= 11 && menu.y + menu.height <= (await page.viewportSize()).height - 11, `${label}: popup outside viewport`);
    const gap = menu.y > bounds.y ? menu.y - bounds.y - bounds.height : bounds.y - menu.y - menu.height;
    assert(Math.abs(gap - 8) <= 2, `${label}: expected 8px anchor gap, got ${gap}`);
    if (searchable) await page.getByRole('searchbox').fill(option);
    await page.getByRole('option', { name: option, exact: true }).click();
    await popup.waitFor({ state: 'detached' });
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true, `${label}: return focus`);
    const after = await page.locator('.composer').boundingBox();
    assert(Math.abs(before.y - after.y) < 1, `${label}: changing choice moved composer`);
  }
  async function selectProviderForScreenshot() {
    await page.getByRole('combobox', { name: '选择供应商', exact: true }).click();
    await page.getByRole('option', { name: '备用模型服务', exact: true }).click();
  }
  try {
    await page.goto(base);
    await page.getByRole('button', { name: '免费创建账户' }).click();
    await page.locator('input[name="name"]').fill('EarthAI');
    await page.locator('input[name="email"]').fill(`ui-${Date.now()}@earthai.local`);
    await page.locator('input[name="password"]').fill('EarthAI-UI-2026!');
    await page.getByRole('button', { name: '创建账户', exact: true }).click();
    await page.getByRole('navigation', { name: '主导航' }).waitFor();
    const p1 = await api('providers', { name: '团队模型服务', base_url: 'http://127.0.0.1:9909/v1', api_key: 'ui-only-not-a-real-key', default_model: 'earthai-e2e-tool-model', models: ['earthai-e2e-tool-model', 'sre-reasoner', ...Array.from({ length: 22 }, (_, index) => `model-${index + 1}`)] });
    const p2 = await api('providers', { name: '备用模型服务', base_url: 'https://example.invalid/v1', api_key: 'ui-only-fake-key', default_model: 'backup-agent', models: ['backup-agent'] });
    const server = await api('servers', { name: '生产巡检节点', kind: 'ssh', host: '192.0.2.1', username: 'sre', password: 'ui-only-test-password' });
    const agent = await api('agents', { name: '集群诊断助手', description: '只读检查 Kubernetes 与业务工作负载', system_prompt: '只读诊断，先收集证据。', provider_id: p1.id, model: 'sre-reasoner', control_level: 'observe' });
    const project = await api('projects', { name: '核心业务', server_ids: [server.id], description: '生产环境上下文' });
    await page.goto(`${base}/chat`);
    await page.getByRole('combobox', { name: '选择智能体' }).waitFor();
    for (const [width, height] of [[1920,1080], [1440,900], [1366,768], [1280,720], [1024,768], [820,600], [390,844], [360,640]]) {
      await page.setViewportSize({ width, height });
      await measure(`${width}×${height} 新对话 / 100%`, true);
      const composer = await page.locator('.composer').boundingBox();
      assert(composer.y + composer.height < height, 'composer clipped');
    }
    pass('8 种视口 / 100% 缩放：新对话无多余滚动、输入框完整可见');
    await page.setViewportSize({ width: 1366, height: 768 });
    await checkMenu('选择智能体', '集群诊断助手', true);
    assert.match(await page.getByRole('combobox', { name: '控制等级' }).innerText(), /观察模式/);
    assert.match(await page.getByRole('combobox', { name: '选择模型' }).innerText(), /sre-reasoner/);
    await checkMenu('项目上下文', '核心业务', true);
    await checkMenu('选择服务器', '生产巡检节点', true);
    await checkMenu('控制等级', '审批模式');
    pass('智能体、项目、服务器与控制菜单紧贴按钮弹出，选后焦点恢复且输入框不跳动');
    const model = page.getByRole('combobox', { name: '选择模型' });
    await checkMenu('选择供应商', '备用模型服务', true);
    assert.match(await model.innerText(), /backup-agent/);
    await model.click();
    assert.equal(await page.getByRole('option', { name: 'sre-reasoner', exact: true }).count(), 0);
    const popup = page.locator('.ea-select-popup');
    await page.getByRole('searchbox').fill('backup-agent');
    await page.getByRole('option', { name: 'backup-agent', exact: true }).click();
    await popup.waitFor({ state: 'detached' });
    await model.click();
    await page.getByRole('searchbox').fill('custom-sre-model');
    await page.getByRole('option', { name: '使用“custom-sre-model”', exact: true }).click();
    assert.match(await model.innerText(), /custom-sre-model/);
    await checkMenu('选择供应商', '团队模型服务', true);
    await model.click();
    await page.getByRole('searchbox').fill('earthai-e2e-tool-model');
    await page.getByRole('option', { name: 'earthai-e2e-tool-model', exact: true }).click();
    await model.focus();
    await page.keyboard.press('ArrowDown');
    await page.getByRole('searchbox').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await model.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('select, datalist').count(), 0);
    pass('独立供应商选择、模型范围过滤、搜索、自定义模型、键盘与 Escape，无原生选项框');
    await page.getByRole('combobox', { name: '选择智能体' }).click();
    await page.locator('.ea-select-popup').waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.ea-select-popup')).opacity === '1');
    await page.screenshot({ animations: 'disabled', path: path.join(out, 'earthai-agent-menu.png') });
    await page.keyboard.press('Escape');
    await model.click();
    await page.locator('.ea-select-popup').waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.ea-select-popup')).opacity === '1');
    await page.screenshot({ animations: 'disabled', path: path.join(out, 'earthai-model-menu.png') });
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('a[href="/settings"]').count(), 1);
    assert.equal(await page.locator('a[href="/chat"]').count(), 1);
    assert.equal(await page.locator('.workspace-switch,.topbar-avatar a,a.user-info').count(), 0);
    pass('全局设置和新对话各一个入口，身份信息不再伪装为菜单');

    const routes = [['servers','添加服务器'],['providers','添加供应商'],['agents','创建智能体'],['projects','创建项目'],['knowledge','创建知识库'],['skills','创建技能'],['schedules','创建定时任务'],['alerts','记录告警']];
    for (const [route,label] of routes) {
      await page.goto(`${base}/${route}`);
      await page.getByRole('button',{name:label,exact:true}).waitFor();
      assert.equal(await page.getByRole('button',{name:label,exact:true}).count(),1, `${route}: repeated create`);
      await measure(`${route} 桌面`);
      await page.getByRole('button',{name:label,exact:true}).click();
      await page.getByRole('dialog').waitFor();
      assert.equal(await page.locator('select, datalist').count(),0, `${route} native options`);
      const select = page.getByRole('dialog').getByRole('combobox').first();
      if(await select.count()) {
        await select.scrollIntoViewIfNeeded();
        await select.click();
        await page.locator('.ea-select-popup').waitFor();
        await page.keyboard.press('Escape');
        assert.equal(await page.getByRole('dialog').count(),1, `${route} Escape closed parent modal`);
      }
      await page.getByRole('button',{name:'关闭对话框',exact:true}).click();
    }
    pass('8 个管理页创建入口唯一，表单选择统一，弹层 Escape 不误关父弹窗');

    const kb = await api('knowledge',{name:'运维手册'});
    await context.request.post(`${base}/api/knowledge/${kb.id}/documents`,{multipart:{file:{name:'guide.md',mimeType:'text/markdown',buffer:Buffer.from('EarthAI UI 测试知识库文档')}}});
    await context.request.post(`${base}/api/files`,{multipart:{file:{name:'生产环境非常长的配置备份文件名称及检查报告.yaml',mimeType:'application/vnd.earthai.long-custom-mime-type+yaml',buffer:Buffer.from('ui: true')}}});
    await page.goto(`${base}/space`);
    await page.getByText('生产环境非常长的配置备份文件名称及检查报告.yaml',{exact:true}).waitFor();
    await measure('个人空间长文件名 / 桌面',true);
    await page.setViewportSize({width:390,height:844});
    await measure('个人空间长文件名 / 手机');
    await page.goto(`${base}/knowledge`);
    await page.getByRole('heading',{level:2,name:'运维手册',exact:true}).waitFor();
    await measure('知识库工作台 / 手机');
    pass('长文件名、MIME 与移动端知识库目录均不横向滚动');
    await page.goto(`${base}/chat`);
    await page.getByRole('combobox',{name:'选择智能体'}).click();
    await page.locator('.ea-select-popup').waitFor();
    await measure('手机智能体菜单');
    await page.screenshot({animations:'disabled',path:path.join(out,'earthai-mobile-menu.png')});
    await page.keyboard.press('Escape');
    await page.getByRole('button',{name:'展开导航'}).click();
    await page.getByRole('link',{name:'偏好设置',exact:true}).click();
    await page.getByText('奶油白',{exact:true}).click();
    await page.getByRole('button',{name:'保存更改',exact:true}).click();
    await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
    await page.getByRole('button',{name:'展开导航'}).click();
    await page.getByRole('link',{name:'AI 对话',exact:true}).click();
    await page.setViewportSize({width:1366,height:768});
    await page.screenshot({animations:'disabled',path:path.join(out,'earthai-chat-polished.png')});
    await selectProviderForScreenshot();
    await page.getByRole('combobox',{name:'选择模型'}).click();
    await page.getByRole('searchbox').fill('backup-agent');
    await page.getByRole('option',{name:'backup-agent',exact:true}).click();
    await page.getByRole('combobox',{name:'选择模型'}).click();
    await page.locator('.ea-select-popup').waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.ea-select-popup')).opacity === '1');
    await page.screenshot({animations:'disabled',path:path.join(out,'earthai-model-menu-light.png')});
    await page.keyboard.press('Escape');
    await page.getByRole('link',{name:'系统概览',exact:true}).click();
    await page.screenshot({animations:'disabled',path:path.join(out,'earthai-overview-polished.png')});
    await measure('精简概览');
    assert.equal(errors.length,0,errors.join('\n'));
    pass('明暗主题、手机导航正常，浏览器零运行时异常');
    fs.writeFileSync(path.join(out,'ui-verification.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks,measured,errors,scope:'isolated database, headless Chromium at CSS zoom 100%, no user credentials or infrastructure commands'},null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
