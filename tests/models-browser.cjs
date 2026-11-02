const assert=require('node:assert/strict');
const express=require('express');
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const root=path.resolve(__dirname,'..'),prefix='/digital-human/dh/model-fixture';
let server,browser;
(async()=>{
 const app=express();app.use(express.json({limit:'4mb'}));
 let state={mode:'adc',config_id:'',items:[],protocols:[]},drafts=[],calls=[],hold=false,release;
 const ok=(res,data)=>res.json({code:0,data});
 app.get(prefix+'/api/environment',(_q,r)=>ok(r,{mode:'remote',revision:0,switchable:false}));
 app.get(prefix+'/api/ai-models',(_q,r)=>ok(r,state));
 app.post(prefix+'/api/ai-models/profiles',(q,r)=>{drafts.push(q.body);const item={...q.body,id:'a'.repeat(32),revision:Math.random().toString(16).slice(2),has_api_key:!!q.body.api_key};for(const key of ['api_key','headers','extra_body','body_template'])delete item[key];state.items=[item];ok(r,item);});
 app.post(prefix+'/api/ai-models/select',(q,r)=>{state={...state,...q.body};ok(r,state);});
 app.post(prefix+'/api/ai-models/test',(q,r)=>{drafts.push(q.body);ok(r,{text:'OK',protocol:q.body.protocol,ms:15});});
 app.post(prefix+'/api/ai-models/generate',(q,r)=>{calls.push(q.body);const finish=()=>ok(r,{text:JSON.stringify({type:'answer',text:'独立模型已回答'}),protocol:'openai',model:'fixture-model',ms:10,request_id:'fixture'});if(hold)release=finish;else finish();});
 app.get(prefix+'/api/air/documents',(_q,r)=>ok(r,[]));
 app.get(prefix+'/api/agent/capabilities',(_q,r)=>ok(r,{tools:[],sources:[]}));
 app.post(prefix+'/api/ops/tables/refresh',(_q,r)=>ok(r,{tables:[],health:{},total:0}));
 app.use(prefix,express.static(path.join(root,'static')));
 app.use((_q,r)=>ok(r,{}));
 server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});
 const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+prefix+'/');await page.waitForFunction(()=>window.AiReportApp?.state?.doc&&window.AiOpsModelSettings);
 // Plain HTTP is accepted; credentials are entered in a password field, never read back.
 await page.locator('[data-ai-model-settings]').click();let dialog=page.getByRole('dialog',{name:'AI 模型配置'});
 await dialog.locator('[name=name]').fill('内网兼容模型');await dialog.locator('[name=base_url]').fill('http://10.0.0.9:8000/v1');await dialog.locator('[name=model]').fill('fixture-model');await dialog.locator('[name=api_key]').fill('fixture-password');
 await dialog.getByRole('button',{name:'测试模型',exact:true}).click();await dialog.locator('[data-status]').filter({hasText:'测试成功'}).waitFor();assert.equal(state.items.length,0,'Testing does not save');
 await dialog.getByRole('button',{name:'保存并使用',exact:true}).click();await dialog.locator('[data-status]').filter({hasText:'已保存并启用'}).waitFor();assert.equal(state.mode,'model');assert.equal(await dialog.locator('[name=api_key]').inputValue(),'');assert.equal(drafts.at(-1).api_key,'fixture-password');
 // Modal stays inside all four viewport edges, including narrow screens and both themes.
 const screenshots=fs.mkdtempSync(path.join(os.tmpdir(),'aiops-model-ui-'));
 for(const width of [1440,390])for(const theme of ['light','dark']){
  await page.setViewportSize({width,height:850});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
  const bounds=await dialog.boundingBox();assert(bounds.x>=0&&bounds.y>=0&&bounds.x+bounds.width<=width&&bounds.y+bounds.height<=850);
  const colors=await dialog.evaluate(el=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));assert.notEqual(colors.bg,colors.color);
  await page.screenshot({path:path.join(screenshots,width+'-'+theme+'.png')});
 }
 await dialog.locator('[data-close]').click();await page.setViewportSize({width:1440,height:1000});
 // The report uses direct inference on a non-ADC host and never reads credentials.
 const id=await page.evaluate(()=>AiReportApp.state.doc.chapters[0].cells[0].id);
 await page.evaluate(id=>AiReportApp.converse(id,'请说明这个格子'),id);
 await page.waitForFunction(()=>!AiReportApp.state.busy.size);
 assert(calls.length>=1);assert(!JSON.stringify(calls).includes('fixture-password'));assert(calls[0].messages[0].content.includes('请说明这个格子'));
 assert(await page.evaluate(()=>DragonClaw.ready()));
 // Independent owners keep context separate; stopped work cannot append a late reply or call the model again.
 const before=calls.length;
 await page.evaluate(async()=>{
  await AiOpsModels.conversation('owner-one',true,async c=>{await c.ask('one');await c.ask('two');});
  await AiOpsModels.conversation('owner-two',true,c=>c.ask('other'));
 });
 assert.equal(calls[before].messages.length,1);assert.equal(calls[before+1].messages.length,3);assert.equal(calls[before+2].messages.length,1);
 hold=true;
 await page.evaluate(()=>{
  window.cancelFixture=new AbortController();window.modelLateResult='pending';
  window.modelPending=AiOpsModels.conversation('stopped',true,async c=>{await c.ask('stop me');window.modelLateResult='applied';await c.ask('must not send');},{signal:cancelFixture.signal}).catch(e=>window.modelLateResult=e.name);
 });
 await page.waitForFunction(()=>AiOpsModels.busy());await new Promise(r=>setTimeout(r,80));const count=calls.length;
 await page.evaluate(async()=>{cancelFixture.abort();await modelPending;});if(release)release();await new Promise(r=>setTimeout(r,100));
 assert.equal(await page.evaluate(()=>modelLateResult),'AbortError');assert.equal(calls.length,count);
 // English labels and developer tools entry are reachable.
 await page.evaluate(()=>{document.documentElement.lang='en';AiOpsModelSettings.show();});await page.getByRole('dialog',{name:'AI model settings'}).waitFor();await page.locator('.aim-dialog [data-close]').click();
 await page.goto(origin+prefix+'/dev.html');await page.getByText('AI 模型配置',{exact:true}).first().click();await page.getByRole('dialog',{name:'AI 模型配置'}).waitFor();
 assert.deepEqual(errors,[]);console.log('PASS: model settings, HTTP test/save/select, password masking, themes, mobile, direct report inference, isolated contexts, cancellation, English and developer menu. Screenshots: '+screenshots);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await new Promise(r=>server?server.close(r):r());});
