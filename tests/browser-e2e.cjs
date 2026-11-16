const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const output = process.env.EARTHAI_E2E_OUTPUT || path.resolve(__dirname, '../docs');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = label => { checks.push(label); console.log('PASS', label); };
  async function noOverflow(label) {
    const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
    assert(dimensions.scroll <= dimensions.width + 2, `${label}: ${JSON.stringify(dimensions)}`);
    check(label);
  }
  try {
    await page.goto(base);
    await page.getByRole('button', { name: '免费创建账户' }).click();
    await page.getByLabel('怎么称呼你').fill('EarthAI 验收');
    await page.getByLabel('电子邮箱', { exact: false }).fill(`browser-${Date.now()}@earthai.local`);
    await page.locator('input[name="password"]').fill('Browser-Test-2026!');
    await page.getByRole('button', { name: '创建账户', exact: true }).click();
    await page.getByRole('navigation', { name: '主导航' }).waitFor();
    check('真实浏览器注册登录与工作空间加载');
    await noOverflow('1440px 桌面无水平溢出');
    await page.screenshot({ path: path.join(output, 'earthai-chat-dark.png'), fullPage: true });

    await page.getByRole('navigation').getByRole('link', { name: '模型供应商', exact: true }).click();
    await page.getByRole('button', { name: '添加供应商', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('供应商名称').fill('本地端到端测试模型');
    await dialog.getByLabel('API Base URL').fill('http://127.0.0.1:9909/v1');
    await dialog.getByLabel('API Key').fill('e2e-only-not-real-secret');
    await dialog.getByLabel('默认模型').fill('earthai-e2e-tool-model');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    await page.getByRole('heading', { name: '本地端到端测试模型' }).waitFor();
    await page.getByRole('button', { name: '测试连接', exact: true }).click();
    await page.getByRole('heading', { name: '真实连接测试通过' }).waitFor();
    await page.getByRole('button', { name: '我知道了' }).click();
    check('供应商 URL/API Key 表单保存与真实 HTTP 连接测试');

    await page.getByRole('navigation').getByRole('link', { name: 'AI 对话', exact: true }).click();
    await page.getByRole('combobox', { name: '选择供应商', exact: true }).click();
    await page.getByRole('option', { name: '本地端到端测试模型', exact: true }).click();
    await page.getByRole('combobox', { name: '选择模型' }).click();
    await page.getByRole('option', { name: 'earthai-e2e-tool-model', exact: true }).click();
    await page.getByRole('textbox', { name: '消息内容' }).fill('检查个人文件空间并生成一份端到端验收报告。');
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await page.waitForURL(/\/chat\/[^/?]+$/);
    const conversationUrl = page.url();
    const conversationId = new URL(conversationUrl).pathname.split('/').pop();
    await page.locator('.dock-live').waitFor();
    await page.getByRole('navigation').getByRole('link', { name: '系统概览', exact: true }).click();
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.locator('.dock-empty').filter({ hasText: '当前没有运行中的任务' }).waitFor({ timeout: 45000 });
    const detail = await (await context.request.get(`${base}/api/conversations/${conversationId}`)).json();
    const completedId = detail.runs?.[0]?.id;
    assert(completedId);
    const run = await (await context.request.get(`${base}/api/runs/${completedId}`)).json();
    assert.equal(run.run.status, 'completed');
    assert.equal(run.events.filter(event => event.type === 'tool_result').length, 3);
    check('真实后台四轮 Agent + 三次工具调用，切换概览页面不断连');
    await page.screenshot({ path: path.join(output, 'earthai-overview-dark.png'), fullPage: true });
    await page.goto(conversationUrl);
    await page.getByText('端到端验收已完成：', { exact: false }).first().waitFor();
    check('浏览器刷新后恢复会话与持久化执行记录');

    await page.getByRole('navigation').getByRole('link', { name: '个人空间', exact: true }).click();
    await page.getByText('E2E验收报告.md', { exact: true }).waitFor();
    const files = await (await context.request.get(`${base}/api/files`)).json();
    const file = files.find(item => item.name === 'E2E验收报告.md');
    assert(file);
    const content = await (await context.request.get(`${base}/api/files/${file.id}/download`)).text();
    assert(content.includes('后台真实工具已生成此文件'));
    check('Agent 生成真实 Markdown 文件，可鉴权下载');

    for (const [label, route] of [['智能体','agents'],['知识库','knowledge'],['技能库','skills'],['项目','projects'],['服务器','servers'],['定时任务','schedules'],['告警中心','alerts']]) {
      await page.getByRole('navigation').getByRole('link', { name: label, exact: true }).click();
      await page.waitForURL(`**/${route}`);
      await page.getByRole('heading', { level: 1 }).waitFor();
      assert(!(await page.getByText('暂时无法获取数据', { exact: true }).count()));
    }
    check('全部管理路由连接真实后端且无运行时错误');

    await page.getByRole('link', { name: '偏好设置', exact: true }).click();
    await page.getByLabel('自定义头像文字').fill('EA');
    await page.getByText('奶油白', { exact: true }).click();
    await page.getByRole('button', { name: '保存更改', exact: true }).click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    const profile = await (await context.request.get(`${base}/api/auth/me`)).json();
    assert.equal(profile.avatar, 'EA');
    assert.equal(profile.theme, 'light');
    check('头像标识与主题真实持久化');
    await page.getByRole('navigation').getByRole('link', { name: 'AI 对话', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'earthai-chat-light.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await noOverflow('390px 移动端无水平溢出');
    await page.getByRole('button', { name: '展开导航' }).click();
    await page.getByRole('navigation').getByRole('link', { name: '系统概览', exact: true }).click();
    await page.waitForURL('**/overview');
    await noOverflow('移动端侧栏导航与概览排版');
    assert.equal(errors.length, 0, errors.join('\n'));
    check('浏览器零 JavaScript 运行时异常');
    fs.writeFileSync(path.join(output, 'browser-verification.json'), JSON.stringify({ ok: true, checked_at: new Date().toISOString(), checks, errors, environment: 'Headless Chromium, isolated SQLite, real HTTP local provider fixture; no production credentials' }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
