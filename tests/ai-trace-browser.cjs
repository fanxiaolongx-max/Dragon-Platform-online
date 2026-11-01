// Actual ADC client, hidden native composer, fetch capture and SSE parser against local fixtures only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),express=require('express');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),prefix='/digital-human/dh/fixture-app',stream='/adc-agent/web/rest/v1/deepagent/stream/OperationsDigitalHuman/OperationsDigitalHuman/agent_OperationsDigitalHuman';
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'aiops-adc-trace-')),calls=[],executions=[];
let page,browser,server,origin,release,hold=true,failTool=false,step=0;
const long='full-query-result-'.repeat(2500);
const fixture=`<!doctype html><html><body><button id="new" onclick="window.newCount=(window.newCount||0)+1;window.sid='session-'+window.newCount;">新建对话</button><form><textarea placeholder="请输入消息"></textarea><button type="submit">发送</button></form><script>
window.sid='session-0';document.querySelector('form').onsubmit=async event=>{event.preventDefault();const input=document.querySelector('textarea'),message=input.value;input.value='';const response=await fetch('${stream}',{method:'POST',headers:{'Content-Type':'application/json','x-adc-page-timestamp':'fixture-time','x-adc-page-token':'fixture-page-secret','x-gde-csrf-token':'fixture-csrf-secret'},body:JSON.stringify({message,session_id:window.sid,agent:'build',model:{provider_id:'fixture',model_id:'fixture'}})});await response.text();};</script></body></html>`;
(async()=>{
 const web=express();web.use(express.json({limit:'5mb'}));
 web.get('/adc-agent/static/deepagent-sandbox/index.html',(_req,res)=>res.type('html').send(fixture));
 web.post(stream,(req,res)=>{
  calls.push(req.body);res.set({'Content-Type':'text/event-stream','Cache-Control':'no-cache'});res.flushHeaders();
  const n=++step,sid=req.body.session_id;
  const emit=(type,properties)=>res.write('data: '+JSON.stringify({id:'e'+n+'-'+Math.random(),type,properties})+'\n\n');
  emit('message.updated',{session_id:sid,info:{id:'m'+n,role:'assistant'}});
  emit('message.part.updated',{session_id:sid,part:{id:'internal'+n,message_id:'m'+n,type:'tool',tool:'fixture_agent',state:{status:'completed',input:{query:'implicit-action',password:'fixture-inner-secret'},output:'implicit-output'}}});
  emit('session.status',{session_id:'child-session',status:{type:'busy'}});
  const finish=()=>{
   const text=n%4===1?JSON.stringify({tool:'list_tables',args:{keyword:'拦截'}}):n%4===2?JSON.stringify({tool:'describe_table',args:{table:'fixture_table'}}):n%4===3?JSON.stringify({tool:'query',args:{sql:"SELECT '{{month}}' AS period"}}):JSON.stringify({type:'answer',text:'已检查来源，任务完成。'});
   emit('message.part.updated',{session_id:sid,part:{id:'t'+n,message_id:'m'+n,type:'text',text}});
   emit('session.idle',{session_id:sid});res.end();
  };
  if(hold)release=finish;else setTimeout(finish,10);
 });
 web.get(prefix+'/api/environment',(_req,res)=>res.json({code:0,data:{mode:'remote',revision:1,switchable:false}}));
 web.get(prefix+'/api/air/documents',(_req,res)=>res.json({code:0,data:[]}));
 web.post(prefix+'/api/agent/execute',(req,res)=>{
  executions.push(req.body);res.set('x-request-id','application-tool-fixture');
  if(req.body.tool==='query'&&failTool)return res.json({code:500,message:'fixture query error token=fixture-data-secret',data:null});
  const result=req.body.tool==='list_tables'?{rows:[],total:0}:req.body.tool==='describe_table'?{table:'fixture_table',columns:[{name:'period',type:'text'}]}:{rows:[{period:'2026-10',detail:long,password:'fixture-data-secret'}],row_count:1};
  res.json({code:0,data:{result}});
 });
 web.get([prefix+'/',prefix+'/index.html'],(_req,res)=>{
  let html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');
  html=html.replace('const ENVIRONMENTS = Object.freeze({','const ENVIRONMENTS = Object.freeze({'+JSON.stringify(origin)+':"测试环境",').replace('const onSite = ADC_ORIGINS.includes(location.origin);','const onSite = true;');
  res.type('html').send(html);
 });
 web.use(prefix,express.static(path.join(root,'static')));web.use((_req,res)=>res.json({code:0,data:{tools:[],sources:[]}}));
 server=await new Promise(r=>{const s=web.listen(0,'127.0.0.1',()=>r(s));});origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});page=await browser.newPage({viewport:{width:1920,height:1080}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+prefix+'/');
 await page.waitForFunction(()=>window.AiReportApp?.state?.doc&&!document.body.classList.contains('air-booting'));
 const id=await page.evaluate(()=>AiReportApp.state.doc.chapters[0].cells[0].id);
 await page.evaluate(id=>{AiReportTrace.setEnabled(true);AiReportApp.converse(id,'请检查数据来源');},id);
 await page.waitForFunction(()=>document.querySelector('[data-live-progress]')?.textContent.includes('子会话'));
 assert.equal(await page.locator('[data-dev-export]').count(),1);
 assert.equal(calls.length,1,'one native submit, without duplicate requests');
 await page.screenshot({path:path.join(temp,'live-progress.png')});
 hold=false;release();await page.waitForFunction(()=>!AiReportApp.state.busy.size);
 const log=await page.evaluate(id=>AiReportTrace.list(id).at(-1),id);
 assert.equal(log.status,'success');
 for(const stage of ['queued','lane_acquired','frame_stealth','frame_ready','composer_fill','composer_submit','capture_hook','session_capture','stream_tool','stream_child','stream_done','frame_restore','lane_released'])assert(log.steps.some(s=>s.stage===stage),'missing stage '+stage);
 assert.equal(log.steps.filter(s=>s.kind==='tool').length,3);assert.equal(log.steps.filter(s=>s.kind==='http').length,3);
 assert.equal(log.steps.find(s=>s.kind==='tool'&&s.name==='query').result.rows[0].detail,long);
 assert.equal(log.steps.find(s=>s.kind==='tool'&&s.name==='query').modelTruncated,true);
 assert.equal(executions[2].args.sql,"SELECT '2026-10' AS period");
 assert.doesNotMatch(JSON.stringify(log),/fixture-page-secret|fixture-csrf-secret|fixture-inner-secret|fixture-data-secret/);
 await page.locator('.air-dev-entry > summary').last().click();await page.screenshot({path:path.join(temp,'call-log.png')});
 const download=page.waitForEvent('download');await page.locator('[data-dev-export]').click();const file=await download;const exported=JSON.parse(fs.readFileSync(await file.path(),'utf8'));
 assert.equal(exported.version,2);assert.equal(exported.environment.transport,'ADC embedded page');assert.equal(exported.environment.frame.sameOrigin,true);assert.equal(exported.entries.length,1);assert.equal(exported.entries[0].steps.filter(s=>s.kind==='tool').length,3);
 // A returned business error is visible with HTTP 200, and stays attributable to this cell.
 failTool=true;await page.evaluate(id=>{AiReportApp.converse(id,'再次查询');},id);await page.waitForFunction(()=>!AiReportApp.state.busy.size);
 const failed=await page.evaluate(id=>AiReportTrace.list(id).at(-1),id);
 assert(failed.steps.some(s=>s.kind==='http'&&s.status==='error'&&s.httpStatus===200&&s.businessCode===500&&s.requestId==='application-tool-fixture'));
 assert(failed.steps.some(s=>s.kind==='tool'&&s.name==='query'&&s.status==='error'));
 // Logging off retains progress, hides export and retains no additional request payloads.
 const count=await page.evaluate(id=>{AiReportTrace.setEnabled(false);return AiReportTrace.list(id).length;},id);
 hold=true;await page.evaluate(id=>{AiReportApp.converse(id,'再查一下');},id);await page.waitForFunction(()=>document.querySelector('[data-live-progress]')?.textContent.includes('子会话'));
 assert.equal(await page.locator('[data-dev-export]').count(),0);hold=false;release();await page.waitForFunction(()=>!AiReportApp.state.busy.size);
 assert.equal(await page.evaluate(id=>AiReportTrace.list(id).length,id),count);
 // Cancelling retains partial diagnostic events and never marks the response successful.
 await page.evaluate(()=>AiReportTrace.setEnabled(true));hold=true;await page.evaluate(id=>{AiReportApp.converse(id,'停止测试');},id);await page.waitForFunction(()=>document.querySelector('[data-live-progress]')?.textContent.includes('子会话'));
 await page.locator('#airStop').click();await page.waitForFunction(()=>!AiReportApp.state.busy.size&&AiReportTrace.list(AiReportApp.state.selected).at(-1)?.status==='cancelled');
 const cancelled=await page.evaluate(id=>AiReportTrace.list(id).at(-1),id);assert(cancelled.steps.some(s=>s.stage==='stopped'));hold=false;release();
 await page.setViewportSize({width:390,height:844});await page.locator('#airChat').scrollIntoViewIfNeeded();
 assert(await page.locator('[data-dev-export]').isVisible());assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:path.join(temp,'narrow.png')});assert.deepEqual(errors,[]);
 console.log('PASS: actual hidden ADC composer, single submit, captured HTTP/SSE, implicit tool/child-session events, SQL tools, empty and failed results, full payloads, redaction, export, logging-off progress, cancellation and narrow UI. Preview: '+temp);
})().catch(async e=>{console.error(e);if(page){console.error(await page.evaluate(()=>({progress:document.querySelector('[data-live-progress]')?.textContent,busy:window.AiReportApp?.state?.busy?.size,chat:document.getElementById('airChat')?.textContent?.slice(-3000),adc:window.ADCChat?.configured,steps:window.AiReportTrace?.list(window.AiReportApp?.state?.selected).at(-1)?.steps.map(s=>({stage:s.stage,error:s.error}))})));await page.screenshot({path:path.join(temp,'failure.png')});}console.error('Preview: '+temp);process.exitCode=1;}).finally(async()=>{await browser?.close();server?.close();});
