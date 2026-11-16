const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const base=process.env.EARTHAI_E2E_URL||'http://127.0.0.1:8010';
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 let context=await browser.newContext({viewport:{width:1366,height:900}});
 let page=await context.newPage();
 const email=`durable-${Date.now()}@earthai.local`,password='Durable-Test-2026!';
 const checks=[];const pass=label=>{checks.push(label);console.log('PASS',label)};
 async function choose(label,name){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name,exact:true}).click();}
 async function login(){await page.locator('input[name=email]').fill(email);await page.locator('input[name=password]').fill(password);await page.getByRole('button',{name:'登录工作空间',exact:true}).click();await page.getByRole('navigation',{name:'主导航'}).waitFor();}
 async function setup(endpoint,data){const r=await context.request.post(`${base}/api/${endpoint}`,{data});assert(r.ok(),await r.text());return r.json();}
 try{
  await page.goto(base);await page.getByRole('button',{name:'免费创建账户'}).click();await page.locator('input[name=name]').fill('持久化验收');await page.locator('input[name=email]').fill(email);await page.locator('input[name=password]').fill(password);await page.getByRole('button',{name:'创建账户',exact:true}).click();await page.getByRole('navigation',{name:'主导航'}).waitFor();
  const provider=await setup('providers',{name:'持久配置模型',base_url:'http://127.0.0.1:9909/v1',api_key:'local-test-only',default_model:'earthai-e2e-tool-model',models:['earthai-e2e-tool-model','earthai-tool-only']});
  const server=await setup('servers',{name:'偏好服务器',host:'192.0.2.1',password:'fixture-only-password'});
  const agent=await setup('agents',{name:'偏好智能体',system_prompt:'只使用个人空间工具',control_level:'observe'});
  const project=await setup('projects',{name:'偏好项目',server_ids:[server.id]});
  await page.goto(`${base}/chat`);
  await choose('选择智能体','偏好智能体');await choose('项目上下文','偏好项目');await choose('选择服务器','偏好服务器');await choose('选择供应商','持久配置模型');await choose('选择模型','earthai-tool-only');await choose('控制等级','观察模式');
  const expected={server_id:server.id,provider_id:provider.id,model:'earthai-tool-only',agent_id:agent.id,project_id:project.id,control_level:'observe'};
  await page.getByRole('navigation').getByRole('link',{name:'系统概览',exact:true}).click();await page.getByRole('navigation').getByRole('link',{name:'AI 对话',exact:true}).click();
  await page.getByRole('combobox',{name:'选择模型',exact:true}).filter({hasText:'earthai-tool-only'}).waitFor();
  assert.deepEqual(await(await context.request.get(`${base}/api/preferences/chat`)).json(),expected);
  await page.reload();await page.getByRole('combobox',{name:'选择服务器',exact:true}).filter({hasText:'偏好服务器'}).waitFor();
  pass('六项聊天配置立即保存到服务端，新会话与刷新完整恢复');
  const settings={...expected,server_id:null,agent_id:null,project_id:null,model:'earthai-e2e-tool-model'};
  const patched=await context.request.patch(`${base}/api/preferences/chat`,{data:settings});assert(patched.ok());
  await page.goto(`${base}/chat`);await page.getByRole('combobox',{name:'选择模型',exact:true}).filter({hasText:'earthai-e2e-tool-model'}).waitFor();
  await page.getByRole('textbox',{name:'消息内容'}).fill('请用个人空间工具生成报告，测试退出后继续。');
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.getByRole('button',{name:'发送消息',exact:true}).click();const run=await(await responsePromise).json();
  await page.locator('.ea-generation-status').waitFor();
  await page.getByRole('link',{name:'偏好设置',exact:true}).click();await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('button',{name:'确认操作',exact:true}).click();await page.getByRole('button',{name:'登录工作空间',exact:true}).waitFor();
  assert.equal((await context.request.get(`${base}/api/runs/${run.id}`)).status(),401);
  await context.close();
  context=await browser.newContext({viewport:{width:1366,height:900}});page=await context.newPage();await page.goto(base);await login();
  await page.getByRole('combobox',{name:'选择模型',exact:true}).filter({hasText:'earthai-e2e-tool-model'}).waitFor();
  const detail=await(await context.request.get(`${base}/api/runs/${run.id}`)).json();assert(!['cancelled','interrupted'].includes(detail.run.status));
  assert.deepEqual(await(await context.request.get(`${base}/api/preferences/chat`)).json(),settings);
  await page.goto(`${base}/chat/${run.conversation_id}`);
  await page.getByText('端到端验收已完成：',{exact:false}).first().waitFor({timeout:45000});
  const completed=await(await context.request.get(`${base}/api/runs/${run.id}`)).json();assert.equal(completed.run.status,'completed');assert.equal(completed.events.filter(e=>e.type==='tool_result').length,3);
  pass('退出账号并关闭浏览器上下文后任务未取消，重新登录可恢复进度及执行结果');
  await page.getByRole('navigation').getByRole('link',{name:'AI 对话',exact:true}).click();await page.getByRole('textbox',{name:'消息内容'}).fill('再生成一份报告，测试关闭浏览器不断任务。');const request=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.getByRole('button',{name:'发送消息',exact:true}).click();const run2=await(await request).json();await page.locator('.ea-generation-status').waitFor();
  const storage=await context.storageState();await context.close();
  context=await browser.newContext({storageState:storage,viewport:{width:1366,height:900}});page=await context.newPage();await page.goto(`${base}/chat/${run2.conversation_id}`);await page.getByText('端到端验收已完成：',{exact:false}).first().waitFor({timeout:45000});
  const completed2=await(await context.request.get(`${base}/api/runs/${run2.id}`)).json();assert.equal(completed2.run.status,'completed');
  pass('关闭并重建浏览器会话后可自动订阅原任务，三个工具结果完整恢复');
  fs.writeFileSync(path.resolve(__dirname,'../docs/persistence-verification.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks,scope:'isolated account/SQLite/local model fixture; no production infrastructure'},null,2));
 }finally{await context.close().catch(()=>{});await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
