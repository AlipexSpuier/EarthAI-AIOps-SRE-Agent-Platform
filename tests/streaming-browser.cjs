const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
 const base=process.env.EARTHAI_E2E_URL||'http://127.0.0.1:8010';
 const out=path.resolve(__dirname,'../docs');
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1366,height:900},deviceScaleFactor:1,locale:'zh-CN'});
 const page=await context.newPage();const errors=[];const checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 const pass=label=>{checks.push(label);console.log('PASS',label)};
 async function choose(label,name){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name,exact:true}).click();}
 async function send(text){
   await page.getByRole('textbox',{name:'消息内容'}).fill(text);
   const pending=page.waitForResponse(response=>response.url().endsWith('/messages')&&response.request().method()==='POST');
   await page.getByRole('button',{name:'发送消息',exact:true}).click();
   const response=await pending;assert(response.ok(),await response.text());return response.json();
 }
 async function api(endpoint){const response=await context.request.get(`${base}/api/${endpoint}`);assert(response.ok());return response.json();}
 try{
   await page.goto(base);await page.getByRole('button',{name:'免费创建账户'}).click();
   await page.locator('input[name=name]').fill('流式验收');
   await page.locator('input[name=email]').fill(`stream-${Date.now()}@earthai.local`);
   await page.locator('input[name=password]').fill('Stream-UI-2026!');
   await page.getByRole('button',{name:'创建账户',exact:true}).click();
   await page.getByRole('navigation',{name:'主导航'}).waitFor();
   const created=await context.request.post(`${base}/api/providers`,{data:{name:'实时测试模型',base_url:'http://127.0.0.1:9909/v1',api_key:'test-only-stream-key',default_model:'earthai-e2e-tool-model',models:['earthai-e2e-tool-model','earthai-empty-once','earthai-tool-only','earthai-truncated']}});assert(created.ok());
   await page.goto(`${base}/chat`);
   await choose('选择供应商','实时测试模型');
   await choose('选择模型','earthai-e2e-tool-model');
   const run=await send('请通过真实工具检查个人空间并保存验收报告。');
   await page.getByText('正在进行端到端',{exact:false}).first().waitFor();
   const early=await api(`runs/${run.id}`);
   assert.equal(early.run.status,'running');
   assert(early.events.some(event=>event.type==='assistant_delta'));
   assert(!early.events.some(event=>event.type==='assistant'),'public tokens must arrive before final message');
   const partial=await page.locator('.run-card').innerText();
   assert(partial.includes('正在进行端到端'));
   await page.locator('.ea-plan li').filter({hasText:'读取个人文件列表'}).waitFor();
   await page.getByRole('navigation').getByRole('link',{name:'系统概览',exact:true}).click();
   await page.locator('.dock-empty').filter({hasText:'当前没有运行中的任务'}).waitFor({timeout:45000});
   const complete=await api(`runs/${run.id}`);assert.equal(complete.run.status,'completed');
   assert(complete.events.filter(e=>e.type==='assistant_delta').length>3);
   assert.equal(complete.events.filter(e=>e.type==='tool_execution').length,3);
   assert.equal(complete.events.filter(e=>e.type==='tool_result').length,3);
   pass('真实 SSE 正文在模型生成结束前已到达浏览器，逐步工具执行在切页后持续');
   await page.goto(`${base}/chat/${run.conversation_id}`);
   await page.getByText('端到端验收已完成：',{exact:false}).first().waitFor();
   assert.equal(await page.getByText('端到端验收已完成：',{exact:false}).count(),1,'stream final duplicated');
   await page.locator('.ea-step').filter({hasText:'list_files'}).first().waitFor();
   assert((await page.locator('.run-card').innerText()).includes('list_files'));
   assert((await page.locator('.run-card').innerText()).includes('write_report'));
   assert((await page.locator('.run-card').innerText()).includes('E2E验收报告.md'));
   assert.equal(await page.locator('.plan-number.done').count(),0,'plan intention marked completed without evidence');
   const step=page.locator('.ea-step').filter({hasText:'list_files'}).first();
   await step.scrollIntoViewIfNeeded();
   await page.screenshot({animations:'disabled',path:path.join(out,'earthai-live-trace.png')});
   await page.setViewportSize({width:360,height:740});
   await step.scrollIntoViewIfNeeded();
   const dimensions=await page.evaluate(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,route:document.querySelector('.route-content').scrollWidth,routeClient:document.querySelector('.route-content').clientWidth}));
   assert(dimensions.doc<=dimensions.width+1&&dimensions.route<=dimensions.routeClient+1,'mobile execution trace horizontally overflows');
   await page.screenshot({animations:'disabled',path:path.join(out,'earthai-live-trace-mobile.png')});
   await page.setViewportSize({width:1366,height:900});
   await page.reload();
   await page.getByText('端到端验收已完成：',{exact:false}).first().waitFor();
   assert.equal(await page.getByText('端到端验收已完成：',{exact:false}).count(),1);
   pass('刷新恢复无重复文字，按时间展示计划、实际参数、执行输出与报告');
   await page.goto(`${base}/chat`);await choose('选择供应商','实时测试模型');await choose('选择模型','earthai-empty-once');
   const retried=await send('空响应恢复测试 '+Date.now());
   await page.locator('.dock-empty').filter({hasText:'当前没有运行中的任务'}).waitFor({timeout:45000});
   const recovery=await api(`runs/${retried.id}`);assert.equal(recovery.run.status,'completed',JSON.stringify(recovery.run));
   assert(recovery.events.some(e=>e.type==='notice'));assert.equal(recovery.events.filter(e=>e.type==='tool_result').length,3);
   pass('空响应仅重试当前模型请求，恢复后没有重复执行工具');
   await page.goto(`${base}/chat`);await choose('选择供应商','实时测试模型');await choose('选择模型','earthai-tool-only');
   const toolonly=await send('仅工具调用而无正文测试');
   await page.locator('.dock-empty').filter({hasText:'当前没有运行中的任务'}).waitFor({timeout:45000});
   const tools=await api(`runs/${toolonly.id}`);assert.equal(tools.run.status,'completed');assert.equal(tools.events.filter(e=>e.type==='tool_result').length,3);
   pass('模型只发工具调用且 content=null 时仍能完成多步执行');
   await page.goto(`${base}/chat`);await choose('选择供应商','实时测试模型');await choose('选择模型','earthai-truncated');
   const truncated=await send('中断流安全测试');
   await page.locator('.dock-empty').filter({hasText:'当前没有运行中的任务'}).waitFor({timeout:45000});
   const failed=await api(`runs/${truncated.id}`);assert.equal(failed.run.status,'failed');assert(!failed.events.some(e=>e.type==='tool_execution'));
   pass('不完整工具参数或中断流不执行任何工具，并保留可诊断错误');
   assert.deepEqual(errors,[]);
   fs.writeFileSync(path.join(out,'streaming-verification.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks,errors,earlyEventCount:early.events.length,deltaCount:complete.events.filter(e=>e.type==='assistant_delta').length,environment:'isolated SQLite + real HTTP SSE fixture, no paid model or production server calls'},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
