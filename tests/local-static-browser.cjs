const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const origin = new URL(base).origin;
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1366, height: 900 } });
  const blocked = [], pageErrors = [], failedAssets = [], requests = [], checks = [];
  const pass = text => { checks.push(text); console.log('PASS', text); };
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    requests.push({ url: url.href, type: route.request().resourceType() });
    if (url.origin !== origin) {
      blocked.push(url.href);
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  context.on('page', page => page.on('pageerror', error => pageErrors.push(error.message)));
  context.on('response', response => {
    if (response.status() >= 400 && response.request().resourceType() !== 'fetch' && response.request().resourceType() !== 'xhr') {
      failedAssets.push({ url: response.url(), status: response.status() });
    }
  });
  const page = await context.newPage();
  try {
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: '免费创建账户' }).click();
    await page.locator('input[name=name]').fill('离线静态资源验收');
    await page.locator('input[name=email]').fill('local-assets-' + Date.now() + '@earthai.local');
    await page.locator('input[name=password]').fill('Local-Assets-2026!');
    await page.getByRole('button', { name: '创建账户', exact: true }).click();
    await page.getByRole('navigation', { name: '主导航' }).waitFor();
    const routes = {
      '/chat': '今天想解决什么', '/overview': '让一切，尽在掌握', '/servers': '连接你的工作现场',
      '/providers': '为工作空间注入智能', '/agents': '让专业，有专属的伙伴', '/space': '一处收纳，随时取用',
      '/knowledge': '让知识，参与每一次决策', '/skills': '把经验，变成可复用的能力',
      '/projects': '以业务，组织你的世界', '/schedules': '把规律的事，放心交给时间',
      '/alerts': '重要的问题，不被错过', '/settings': '你的空间，你的节奏',
    };
    for (const [route, title] of Object.entries(routes)) {
      await page.goto(base + route, { waitUntil: 'networkidle' });
      await page.getByText(title, { exact: false }).first().waitFor();
      await page.evaluate(() => document.fonts.ready.then(() => true));
    }
    pass('阻断全部外部网络后，登录注册及12个管理路由正常加载');
    const fonts = await page.evaluate(async () => {
      const english = await document.fonts.load('550 16px "DM Sans"', 'EarthAI');
      const chinese = await document.fonts.load('650 16px "Noto Sans SC"', '智能运维服务器集群审计');
      return { english: english.length, chinese: chinese.length, loaded: [...english, ...chinese].every(font => font.status === 'loaded') };
    });
    assert(fonts.english > 0 && fonts.chinese > 0 && fonts.loaded);
    assert(requests.some(request => new URL(request.url).pathname.startsWith('/fonts/') && request.type === 'font'));
    pass('中英文字体及中间字重均从站内 WOFF2 实际加载');
    await page.goto(base + '/api/docs', { waitUntil: 'networkidle' });
    await page.locator('.swagger-ui .info .title').waitFor();
    await page.locator('.swagger-ui .opblock').first().waitFor();
    assert.match(await page.locator('.swagger-ui .info .title').innerText(), /EarthAI/);
    pass('Swagger 文档从本地脚本、样式和OpenAPI正常渲染，无外部验证器请求');
    await page.goto(base + '/redoc', { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: /EarthAI/ }).first().waitFor();
    await page.getByText('/api/health', { exact: false }).first().waitFor();
    pass('ReDoc 文档从本地脚本和OpenAPI正常渲染，不请求Google字体');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/chat', { waitUntil: 'networkidle' });
    await page.getByText('今天想解决什么', { exact: false }).first().waitFor();
    const dimensions = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    assert(dimensions.scrollWidth <= dimensions.width + 1);
    pass('390px移动端同样可加载且无横向溢出');
    assert.deepEqual(blocked, [], 'No external request should be attempted');
    assert.deepEqual(failedAssets, []);
    assert.deepEqual(pageErrors, []);
    const report = {
      ok: true, at: new Date().toISOString(), scope: 'isolated account; all non-origin requests blocked; no production data or model/SSH calls',
      checks, externalRequests: blocked, failedAssets, pageErrors,
      localFontFilesRequested: [...new Set(requests.filter(request => request.type === 'font').map(request => new URL(request.url).pathname))],
      docsScriptsRequested: [...new Set(requests.filter(request => new URL(request.url).pathname.startsWith('/vendor/docs/')).map(request => new URL(request.url).pathname))],
    };
    fs.writeFileSync(path.resolve(__dirname, '../docs/local-static-verification.json'), JSON.stringify(report, null, 2) + '\n');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
