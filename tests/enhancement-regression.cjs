const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EARTHAI_E2E_URL || 'http://127.0.0.1:8010';
  const output = path.resolve(__dirname, '../docs');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1, locale: 'zh-CN' });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  const measurements = [];
  page.on('pageerror', error => errors.push(error.message));
  const sizes = [[1920,1080],[1440,900],[1366,768],[1280,720],[1024,768],[820,600],[390,844],[360,640]];
  const pass = value => { checks.push(value); console.log('PASS',value); };
  const rect = locator => locator.evaluate(el=>el.getBoundingClientRect().toJSON());
  const readMeasure = () => page.evaluate(() => ({
    viewport:[innerWidth,innerHeight], document:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],
    scrolls:[...document.querySelectorAll('*')].filter(el=>{
      const box=el.getBoundingClientRect(), style=getComputedStyle(el);
      return box.width>0&&box.height>0&&box.right>0&&style.visibility!=='hidden'&&((/(auto|scroll)/.test(style.overflowY)&&el.scrollHeight>el.clientHeight+2)||(/(auto|scroll)/.test(style.overflowX)&&el.scrollWidth>el.clientWidth+2));
    }).map(el=>el.className),
  }));
  async function noScroll(label){
    const result=await readMeasure();
    assert(result.document[0]<=result.viewport[0]+1&&result.document[1]<=result.viewport[1]+1,`${label}: document overflow ${JSON.stringify(result)}`);
    assert.deepEqual(result.scrolls,[],`${label}: extra scroll ${JSON.stringify(result)}`);
    measurements.push({label,...result});
  }
  async function select(label, value){
    await page.getByRole('combobox',{name:label,exact:true}).click();
    await page.getByRole('option',{name:value,exact:true}).click();
  }
  async function api(endpoint,data){
    const response=await context.request.post(`${base}/api/${endpoint}`,{data});
    assert(response.ok(),await response.text()); return response.json();
  }
  try {
    await page.goto(base);
    for(const [width,height] of sizes){
      await page.setViewportSize({width,height});
      for(const register of [false,true]){
        if(register) await page.getByRole('button',{name:'免费创建账户'}).click();
        else if(await page.getByRole('button',{name:'返回登录'}).count()) await page.getByRole('button',{name:'返回登录'}).click();
        await noScroll(`${width}×${height} ${register?'注册':'登录'} / 100%`);
        for(const selector of ['input[name=email]','input[name=password]',...(register?['input[name=name]']:[])]){
          const bounds=await rect(page.locator(selector));
          assert(bounds.top>=0&&bounds.bottom<=height,`${selector} clipped`);
        }
        const submit=await rect(page.locator('button[type=submit]'));
        assert(submit.bottom<=height&&submit.top>=0,'auth submit clipped');
        await page.locator('input[name=password]').click();
        await noScroll(`${width}×${height} ${register?'注册':'登录'} focus`);
      }
    }
    pass('登录与注册在八种视口、100%缩放下无滚动，输入聚焦不跳动且所有表单元素可见');
    await page.setViewportSize({width:1366,height:768});
    await page.screenshot({animations:'disabled',path:path.join(output,'earthai-register-fit.png')});
    const email=`enhanced-${Date.now()}@earthai.local`;
    await page.locator('input[name=name]').fill('EarthAI');
    await page.locator('input[name=email]').fill(email);
    await page.locator('input[name=password]').fill('EarthAI-Enhancement-2026!');
    await page.getByRole('button',{name:'创建账户',exact:true}).click();
    await page.getByRole('navigation',{name:'主导航'}).waitFor();
    const resources={};
    for(const kind of ['agents','knowledge','skills']){
      const response=await context.request.get(`${base}/api/${kind}`);
      assert(response.ok()); resources[kind]=await response.json();
      assert(resources[kind].length>=10,`expected at least 10 ${kind}, got ${resources[kind].length}`);
    }
    let documents=0;
    for(const kb of resources.knowledge.filter(item=>item.builtin_key)){
      const response=await context.request.get(`${base}/api/knowledge/${kb.id}/documents`);
      const docs=await response.json();assert(docs.length>=2,`${kb.name} missing runbooks`);documents+=docs.length;
      assert(kb.chunk_count>0,'no indexed chunks');
    }
    assert(documents>=20,'expected at least 20 indexed docs');
    const retrieval=await api('knowledge/search',{query:'CrashLoopBackOff'});
    assert(retrieval.results.length>0,'preset knowledge not searchable');
    for(const agent of resources.agents.filter(item=>item.builtin_key)){
      assert(agent.skill_ids.length>0&&agent.knowledge_ids.length>0,'agent has no actual resource bindings');
    }
    pass(`新账号拥有 ${resources.agents.length} 个智能体、${resources.knowledge.length} 个知识库、${resources.skills.length} 项技能与 ${documents} 份可检索文档`);
    const first=await api('providers',{name:'主模型供应商',base_url:'http://127.0.0.1:9909/v1',api_key:'enhancement-only-test-key',default_model:'earthai-e2e-tool-model',models:['earthai-e2e-tool-model','primary-reasoner']});
    const second=await api('providers',{name:'备用模型供应商',base_url:'https://invalid.example/v1',api_key:'enhancement-only-fake-key',default_model:'backup-agent',models:['backup-agent','backup-fast']});
    await api('providers',{name:'已停用服务',base_url:'https://invalid.example/v1',api_key:'fake-key',enabled:false,default_model:'disabled-model'});
    await api('agents',{name:'联动测试助手',system_prompt:'只读诊断',provider_id:first.id,model:'primary-reasoner',control_level:'observe'});
    await page.goto(`${base}/chat`);
    await page.getByRole('combobox',{name:'选择供应商'}).waitFor();
    for(const [width,height] of sizes){
      await page.setViewportSize({width,height});
      await page.getByRole('textbox',{name:'消息内容'}).click();
      await noScroll(`${width}×${height} 聊天聚焦`);
      let bounds=await page.evaluate(()=>({
        context:document.querySelector('.composer-context-row').getBoundingClientRect().toJSON(),
        input:document.querySelector('.composer textarea').getBoundingClientRect().toJSON(),
        toolbar:document.querySelector('.composer-toolbar').getBoundingClientRect().toJSON(),
        outline:getComputedStyle(document.querySelector('.composer textarea')).outlineStyle,
      }));
      assert(bounds.input.top-bounds.context.bottom>=7,`context overlap: ${JSON.stringify(bounds)}`);
      assert(bounds.toolbar.top-bounds.input.bottom>=7,`toolbar overlap: ${JSON.stringify(bounds)}`);
      assert(bounds.outline==='none','textarea focus ring bleeds into pills');
      for(const name of ['选择智能体','项目上下文','选择服务器','选择供应商','选择模型','控制等级']){
        const box=await rect(page.getByRole('combobox',{name,exact:true}));
        assert(box.left>=0&&box.right<=width+1&&box.top>=0&&box.bottom<=height,`${name} clipped ${width} ${JSON.stringify(box)}`);
      }
    }
    pass('输入框聚焦后与智能体/项目选择器至少保留7px间隔，供应商与模型控件在八种尺寸下完整可见');
    await page.getByRole('textbox',{name:'消息内容'}).fill(Array.from({length:12},(_,index)=>`第 ${index+1} 行输入内容`).join('\n'));
    const multiline=await page.evaluate(()=>({context:document.querySelector('.composer-context-row').getBoundingClientRect().toJSON(),input:document.querySelector('.composer textarea').getBoundingClientRect().toJSON(),toolbar:document.querySelector('.composer-toolbar').getBoundingClientRect().toJSON()}));
    assert(multiline.input.top-multiline.context.bottom>=7&&multiline.toolbar.top-multiline.input.bottom>=7,'multiline input overlaps controls');
    assert(multiline.input.height<=145,'input must stop growing at 144px');
    await page.getByRole('textbox',{name:'消息内容'}).fill('');
    pass('输入框聚焦及多行输入与上下选择器保持间隔，自动增高不超过144px');
    await page.setViewportSize({width:1366,height:768});
    await select('选择供应商','主模型供应商');
    assert.match(await page.getByRole('combobox',{name:'选择模型',exact:true}).innerText(),/earthai-e2e-tool-model/);
    await page.getByRole('combobox',{name:'选择模型',exact:true}).click();
    assert.equal(await page.getByRole('option',{name:'backup-agent',exact:true}).count(),0);
    await page.getByRole('option',{name:'primary-reasoner',exact:true}).click();
    await select('选择供应商','备用模型供应商');
    assert.match(await page.getByRole('combobox',{name:'选择模型',exact:true}).innerText(),/backup-agent/);
    await page.getByRole('combobox',{name:'选择模型',exact:true}).click();
    assert.equal(await page.getByRole('option',{name:'primary-reasoner',exact:true}).count(),0);
    await page.getByRole('searchbox').fill('custom-backup');
    await page.getByRole('option',{name:'使用“custom-backup”',exact:true}).click();
    assert.match(await page.getByRole('combobox',{name:'选择供应商'}).innerText(),/备用模型供应商/);
    await select('选择智能体','联动测试助手');
    assert.match(await page.getByRole('combobox',{name:'选择供应商'}).innerText(),/主模型供应商/);
    assert.match(await page.getByRole('combobox',{name:'选择模型',exact:true}).innerText(),/primary-reasoner/);
    await page.getByRole('combobox',{name:'选择供应商'}).click();
    const disabled=page.getByRole('option',{name:'已停用服务',exact:true});
    assert.equal(await disabled.count(),0,'disabled supplier should not be offered for selection');
    await page.screenshot({animations:'disabled',path:path.join(output,'earthai-provider-picker.png')});
    await page.keyboard.press('Escape');
    await page.getByRole('textbox',{name:'消息内容'}).click();
    await page.screenshot({animations:'disabled',path:path.join(output,'earthai-composer-focused.png')});
    pass('独立供应商选择、模型按供应商过滤、切换重置默认模型、自定义模型与智能体偏好联动正确');
    for(const [route,label] of [['agents','创建智能体'],['knowledge','创建知识库'],['skills','创建技能']]){
      await page.goto(`${base}/${route}`);
      await page.getByRole('button',{name:label,exact:true}).waitFor();
      assert.equal(await page.getByRole('button',{name:label,exact:true}).count(),1);
      const measure=await readMeasure();
      assert(measure.document[0]<=measure.viewport[0]+1&&measure.document[1]<=measure.viewport[1]+1,'preset pages overflow shell');
    }
    await page.screenshot({animations:'disabled',path:path.join(output,'earthai-preset-skills.png')});
    pass('预置资源在真实管理页面可见且仍保持单一创建入口');
    await page.goto(`${base}/chat`);
    await select('选择供应商','主模型供应商');
    await select('选择模型','earthai-e2e-tool-model');
    await page.getByRole('textbox',{name:'消息内容'}).fill('验证供应商与模型独立选择，并生成报告。');
    const responsePromise=page.waitForResponse(response=>response.url().endsWith('/messages')&&response.request().method()==='POST');
    await page.getByRole('button',{name:'发送消息',exact:true}).click();
    const response=await responsePromise;
    const payload=response.request().postDataJSON();
    assert.equal(payload.provider_id,first.id);assert.equal(payload.model,'earthai-e2e-tool-model');
    const run=await response.json();
    await page.getByRole('navigation').getByRole('link',{name:'系统概览',exact:true}).click();
    await page.locator('.dock-empty').filter({hasText:'当前没有运行中的任务'}).waitFor({timeout:45000});
    const complete=await (await context.request.get(`${base}/api/runs/${run.id}`)).json();
    assert.equal(complete.run.status,'completed',JSON.stringify(complete.run));
    pass('真实消息提交携带选定供应商和模型，切页后多步任务仍完成');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'enhancement-verification.json'),JSON.stringify({ok:true,at:new Date().toISOString(),checks,measurements,counts:{agents:resources.agents.length,knowledge:resources.knowledge.length,skills:resources.skills.length,documents},errors},null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
