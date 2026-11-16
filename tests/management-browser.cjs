const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const base=process.env.EARTHAI_E2E_URL||'http://127.0.0.1:8010';
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1366,height:900},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
 const page=await context.newPage();const errors=[];const checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 const pass=name=>{checks.push(name);console.log('PASS',name)};
 async function choose(label,name){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name,exact:true}).click();}
 async function get(endpoint){const response=await context.request.get(base+'/api/'+endpoint);assert(response.ok(),await response.text());return response.json();}
 try{
  await page.goto(base);await page.getByRole('button',{name:'免费创建账户'}).click();
  await page.locator('input[name=name]').fill('智能体管理验收');await page.locator('input[name=email]').fill('agents-'+Date.now()+'@earthai.local');await page.locator('input[name=password]').fill('Agent-Management-2026!');await page.getByRole('button',{name:'创建账户',exact:true}).click();await page.getByRole('navigation',{name:'主导航'}).waitFor();
  const original=await get('agents');
  await page.getByRole('link',{name:'智能体',exact:true}).click();await page.getByRole('button',{name:'创建智能体',exact:true}).click();
  const form=page.getByRole('dialog');await choose('智能体类型','远程智能体');
  await form.locator('input[name=name]').fill('外部远程助手');await form.locator('input[name=url]').fill('https://agent.example.test/workspace?team=earth#chat');
  assert.equal(await form.locator('textarea[name=system_prompt]').count(),0);
  assert.equal(await form.getByRole('combobox',{name:'模型供应商',exact:true}).count(),0);
  await form.getByRole('button',{name:'保存',exact:true}).click();await form.waitFor({state:'hidden'});
  let agents=await get('agents');const remote=agents.find(agent=>agent.name==='外部远程助手');assert(remote&&remote.kind==='remote');assert.equal(agents.at(-1).id,remote.id);
  const link=page.locator(`[data-agent-id="${remote.id}"]`).getByRole('link',{name:'打开远程智能体'});await link.waitFor();assert.equal(await link.getAttribute('href'),remote.url);assert.match(await link.getAttribute('rel'),/noopener/);assert.equal(await link.getAttribute('target'),'_blank');
  await context.route('https://agent.example.test/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<title>Remote Agent Test</title><h1>Remote endpoint</h1>'}));
  const popupPromise=page.waitForEvent('popup');await link.click();const popup=await popupPromise;await popup.waitForLoadState();assert.equal(popup.url(),remote.url);assert.equal(await popup.evaluate(()=>window.opener===null),true);await popup.close();
  assert.equal(new URL(page.url()).pathname,'/agents');
  pass('远程智能体只需URL，卡片安全新窗口跳转，不调用本地执行器');
  await page.getByRole('button',{name:'创建智能体',exact:true}).click();await form.locator('input[name=name]').fill('本地排序助手');await form.locator('textarea[name=system_prompt]').fill('只读分析，先收集实际证据。');await form.getByRole('button',{name:'保存',exact:true}).click();await form.waitFor({state:'hidden'});
  agents=await get('agents');const local=agents.find(agent=>agent.name==='本地排序助手');assert(local.kind==='local');assert.equal(agents.at(-1).id,local.id);assert.deepEqual(agents.slice(0,original.length).map(a=>a.id),original.map(a=>a.id));
  await page.getByRole('button',{name:'调整排序',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('button',{name:'下移 '+original[0].name,exact:true}).click();await dialog.getByRole('button',{name:'保存排序',exact:true}).click();await dialog.waitFor({state:'hidden'});
  agents=await get('agents');assert.equal(agents[0].id,original[1].id);assert.equal(agents[1].id,original[0].id);
  await page.reload();await page.locator('.agent-card').first().waitFor();assert.equal(await page.locator('.agent-card').first().getAttribute('data-agent-id'),original[1].id);
  await page.getByRole('button',{name:'调整排序',exact:true}).click();const rows=dialog.locator('li[data-agent-id]');const before=await rows.evaluateAll(nodes=>nodes.map(node=>node.dataset.agentId));await rows.last().dragTo(rows.first());const after=await rows.evaluateAll(nodes=>nodes.map(node=>node.dataset.agentId));assert.notDeepEqual(after,before);await dialog.getByRole('button',{name:'保存排序',exact:true}).click();await dialog.waitFor({state:'hidden'});assert.deepEqual((await get('agents')).map(a=>a.id),after);
  pass('智能体新增追加到末尾，上下移动和拖拽排序可保存，刷新仍保持');
  await page.getByRole('link',{name:'AI 对话',exact:true}).click();await page.getByRole('combobox',{name:'选择智能体',exact:true}).click();assert.equal(await page.getByRole('option',{name:'外部远程助手',exact:true}).count(),0);await page.keyboard.press('Escape');
  assert.equal((await context.request.post(base+'/api/conversations',{data:{agent_id:remote.id}})).status(),422);
  pass('远程智能体不能混入本地会话与执行配置');
  await page.getByRole('link',{name:'服务器',exact:true}).click();await page.getByRole('button',{name:'添加服务器',exact:true}).click();const serverForm=page.getByRole('dialog');assert.equal(await serverForm.getByLabel('首次连接自动信任并保存指纹').isChecked(),true);assert.equal(await serverForm.locator('input[name=fingerprint]').getAttribute('required'),null);await serverForm.getByRole('button',{name:'关闭对话框',exact:true}).click();pass('新增SSH默认首次自动信任，指纹不必手填且有安全说明');
  await context.request.post(base+'/api/alerts',{data:{title:'审计筛选验收',severity:'info'}});
  await page.getByRole('link',{name:'系统概览',exact:true}).click();const audit=page.getByRole('region',{name:'审计日志'});await audit.scrollIntoViewIfNeeded();await choose('审计日志时间范围','全部时间');await audit.getByText('alerts.create',{exact:true}).waitFor();
  await choose('审计日志时间范围','自定义');await audit.locator('input[name=start]').fill('2000-01-01T00:00');await audit.locator('input[name=end]').fill('2000-01-02T00:00');const queried=page.waitForResponse(response=>response.url().includes('/api/audit?')&&response.url().includes('1999-12-31T16'));await audit.getByRole('button',{name:'查询',exact:true}).click();await queried;await audit.getByText('所选时间范围内没有审计日志。',{exact:true}).waitFor();
  await audit.locator('input[name=start]').fill('2000-01-03T00:00');await audit.getByRole('button',{name:'查询',exact:true}).click();await audit.getByRole('alert').filter({hasText:'结束时间不能早于开始时间'}).waitFor();pass('审计日志按真实起止时间查询，自动转UTC，反向区间被明确拦截');
  await page.screenshot({animations:'disabled',path:path.resolve(__dirname,'../docs/earthai-audit-time.png')});
  await page.setViewportSize({width:390,height:844});await audit.scrollIntoViewIfNeeded();const width=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,route:document.querySelector('.route-content').scrollWidth,client:document.querySelector('.route-content').clientWidth}));assert(width.document<=width.viewport+1&&width.route<=width.client+1);
  const favicon=await context.request.get(base+'/favicon.ico');assert(favicon.ok());assert.match(favicon.headers()['content-type'],/image\//);assert.equal((await favicon.body()).readUInt16LE(2),1);for(const file of ['favicon-32.png','apple-touch-icon.png','icon-192.png','icon-512.png','site.webmanifest'])assert((await context.request.get(base+'/'+file)).ok());assert(await page.locator('link[rel=icon]').count());pass('favicon ICO/PNG与应用图标均可访问，手机审计筛选无横向溢出');
  await page.setViewportSize({width:1366,height:900});await page.goto(base+'/agents');await page.getByRole('button',{name:'创建智能体',exact:true}).waitFor();await page.screenshot({animations:'disabled',path:path.resolve(__dirname,'../docs/earthai-agent-types.png')});await page.getByRole('button',{name:'调整排序',exact:true}).click();await page.screenshot({animations:'disabled',path:path.resolve(__dirname,'../docs/earthai-agent-sorting.png')});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.resolve(__dirname,'../docs/management-verification.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks,errors,scope:'isolated account + real browser, remote endpoint mocked, no production credentials or model calls'},null,2));
 }finally{await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
