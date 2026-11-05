// Run with Playwright available on NODE_PATH; all application/ADC responses are local fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const requests = [], errors = [];
const prefix = '/digital-human/dh/fixture-app/';
let failSave=false, failList=false;
const saves=[];
let environmentMode='local',environmentRevision=0,nativeEnvironment=false;
let monthMode=false;const monthDocs=new Map();
let executionFailure=null, htmlFallback=false;
let diagnosticSlow=false;const diagnosticCalls=[];
// 真实 ADC（v1.4）模拟：有 version；接口 newSession 不允许被调用，提问必须经内嵌原页面（viaPage）。
let realAdcMode=false;
// 交互日志：前端上报的条目、业务表清单刷新与源表直查失败标签
let opsMode=false;const opsReports=[],opsQueries=[];
const opsTables={tables:[{t:'brand_new_tbl',cn:'新出现的表'},{t:'risk_task_new',cn:'风险任务'},{t:'failing_tbl',cn:'失败的表'},{t:'empty_tbl',cn:'空表'}],
  added:[{t:'brand_new_tbl',cn:'新出现的表'}],removed:[{t:'gone_tbl',cn:'下线的表'}],at:'2026-11-02 09:00:00',total:4,
  health:{failing_tbl:{fails:2,lastFail:'2026-11-02 08:59:00',lastError:'HTTP 500'}}};
const opsCatalog={tables:[{t:'risk_task_new',cn:'风险任务',mod:'风险',cate:'风险'},{t:'failing_tbl',cn:'失败的表',mod:'风险',cate:'风险'},
  {t:'empty_tbl',cn:'空表',cate:'其他',empty:true},{t:'gone_tbl',cn:'下线的表',cate:'其他'},{t:'other_tbl',cn:'目录里的表',cate:'其他'}]};
const realAdc = `window.__adcAsks=[];window.__adcNewSession=0;window.ADCChat={version:'1.4',configured:true,busy:false,environment:'Fixture ADC',
  newSession:async()=>{window.__adcNewSession++;throw new Error('newSession must not be used on the real ADC');},stop(){},
  ask:async(q,o={})=>{const doc=document.getElementById('aiBarFrame').contentDocument,box=doc&&doc.querySelector('textarea');
    window.__adcAsks.push({viaPage:!!o.viaPage,composer:!!box,newChats:(doc&&doc.defaultView.__newChats)||0,fresh:q.includes('全新的独立任务')});
    const text='{"gists":{"c1":"要点"}}';o.onUpdate&&o.onUpdate(text);return text;}};`;
const adc = `window.ADCChat={configured:true,busy:false,environment:'Fixture',newSession:async()=> 'fixture',stop(){},ask:async(_q,o)=>o.onUpdate('验证回答。\\n\\n\`\`\`js\\nconst answer = 2;\\n\`\`\`')};`;
const server = http.createServer((req, res) => {
  requests.push(req.url);
  let url = new URL(req.url, 'http://fixture').pathname;
  const nested = url.startsWith(prefix);
  if (nested) url = '/' + url.slice(prefix.length);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers','content-type,x-aiops-environment-revision,x-ops-page');
  res.setHeader('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS');
  if(req.method==='OPTIONS'){res.end();return;}
  if(url==='/api/diagnostics/database'){
    const send=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data}));};
    if(req.method==='GET'){send({configuration:{version:'test',queryUrlConfigured:true,businessDatasourceName:'assigned-business',runtime:{bootId:'fixture-boot',pid:123,reloadEnabled:false,password:'do-not-export'},configurationOrigins:{BUSINESS_DATASOURCE_NAME:{source:'process-environment',environmentPresentAtLoad:true,token:'do-not-export'}},apiKey:'do-not-export'},coverage:{readOnly:true},checks:[{id:'configuration',label:'配置',table:'fixture'},{id:'business-basic',label:'业务库',table:'fixture'},{id:'table-plain',label:'表查询',table:'fixture'}]});return;}
    let body='';req.on('data',c=>body+=c);req.on('end',()=>{const item=JSON.parse(body);diagnosticCalls.push(item);setTimeout(()=>send({...item,status:item.id==='business-basic'?'fail':'pass',ms:12,message:item.id==='business-basic'?'SQL rejected token=fixture-secret':'ok',datasourceMatch:{configuredBusinessName:'assigned-business',configuredNameListed:false,otherNamesExported:false,secret:'do-not-export'},upstream:[{httpStatus:item.id==='business-basic'?400:200,requestId:'00000000-0000-4000-8000-000000000000',message:'password=fixture-password',request:{requestId:'base-request-fixture',scope:'business',method:'POST',businessDatasourceName:'assigned-business',payloadKeys:['datasourceName','sql','Authorization'],Authorization:'do-not-export'}}],rows:[{private:'private-record'}]}),diagnosticSlow?500:0);});return;
  }
  if(url.startsWith('/api/ops/')){
    const send=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data}));};
    if(url==='/api/ops/logs'&&req.method==='POST'){let body='';req.on('data',c=>body+=c);req.on('end',()=>{const b=JSON.parse(body);opsReports.push(...b.entries.map(e=>({...e,header:req.headers['x-ops-page']})));send({accepted:b.entries.length});});return;}
    if(url==='/api/ops/logs'){opsQueries.push(req.url);send({retainDays:30,logs:opsMode?[
      {id:3,at:'2026-11-02 09:00:00',kind:'tables',status:'ok',page:'dev',title:'业务表清单刷新：共 4 张（上次 4 张），新增 1 张，减少 1 张',ms:80,detail:{total:4,previousTotal:4,added:opsTables.added,removed:opsTables.removed}},
      {id:2,at:'2026-11-02 08:59:00',kind:'db',status:'error',page:'dev',route:'/api/data/table-map/data',title:'业务库查询 · failing_tbl 失败',ms:30,detail:{scope:'business',sql:'SELECT * FROM failing_tbl LIMIT 100',tables:['failing_tbl'],httpStatus:500,requestId:'req-1',error:'基座 API 请求失败'}},
      {id:1,at:'2026-11-02 08:58:00',kind:'adc',status:'ok',page:'air',title:'ADC 对话 · AI 月报',ms:1500,detail:{owner:'air',viaPage:true,prompt:'问题',answer:'回答'}},
      {id:0,at:'2026-11-02 08:57:00',kind:'ai',status:'ok',page:'air',title:'AI 月报 · 格子对话：ADC 往返 2 轮，工具 3 次（缓存命中 1 次），用时 40.0 秒',ms:40000,detail:{operation:'/cell/chat',transport:'adc',rounds:2,modelMs:39000,toolCalls:3,toolMs:300,cacheHits:1,prefetched:true,replyType:'ready',perRound:[{ms:30000,tools:['find_value','query'],promptChars:5000,answerChars:200},{ms:9000,tools:[],promptChars:800,answerChars:90}],tools:[{name:'suggest_tables',ms:120,prefetch:true},{name:'find_value',ms:150},{name:'query',ms:0,cached:true}]}},
      {id:-1,at:'2026-11-02 08:56:00',kind:'model',status:'error',page:'air',title:'模型 API 对话 · AI 月报 · glm-52 · 失败',ms:75000,detail:{owner:'air',model:'glm-52',protocol:'openai',turns:3,prompt:'模型提问',error:'模型接口失败'}},
      {id:4,at:'2026-11-02 09:01:00',kind:'model',status:'ok',page:'air',title:'[MODEL-INVOKE] gemini-fixture',ms:8282,detail:{model:'gemini-fixture',protocol:'gemini',requestId:'fixture-performance-1',tps:37.43,performance:{tokenSource:'provider',transport:'http',inputTokens:90,answerTokens:110,thinkingTokens:200,generatedTokens:310,elapsedMs:8282,answerEndToEndTps:13.28,generatedEndToEndTps:37.43,thinkingRequest:{mode:'on',controls:{thinkingBudget:512}},thinkingEvidence:'detected',providerGenerationMs:null,providerGenerationTps:null}}}]:[]});return;}
    if(url==='/api/ops/tables/refresh'){opsQueries.push(req.url+' '+req.headers['x-ops-page']);send(opsMode?opsTables:{tables:[],added:[],removed:[],health:{}});return;}
    if(url==='/api/ops/tables'){send({snapshot:opsMode?opsTables:null,health:opsMode?opsTables.health:{}});return;}
  }
  if(opsMode&&url==='/api/data/table-map'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data:{modules:[]}}));return;}
  if(opsMode&&url==='/api/data/table-map/all-tables'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data:opsCatalog}));return;}
  if(url==='/api/environment'){
    const reply=()=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data:{mode:nativeEnvironment?'remote':environmentMode,revision:environmentRevision,switchable:!nativeEnvironment,remoteReady:true}}));};
    if(req.method==='POST'){let body='';req.on('data',c=>body+=c);req.on('end',()=>{environmentMode=JSON.parse(body).mode;environmentRevision++;reply();});}else reply();return;
  }
  if(url.endsWith('/api/agent/execute') && executionFailure){
    if(executionFailure.network){ req.socket.destroy(); return; }
    res.statusCode=executionFailure.status;
    res.setHeader('x-request-id','fixture-error-123');
    res.setHeader('Content-Type',executionFailure.raw?'text/html':'application/json');
    res.end(executionFailure.raw||JSON.stringify(executionFailure.json)); return;
  }
  if(monthMode && url.startsWith('/api/air/documents')){
    const send=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:0,data}));};
    if(req.method==='POST'){
      let body='';req.on('data',c=>body+=c);req.on('end',()=>{
        const doc=JSON.parse(body);saves.push(doc);doc.id=doc.id||String(200+monthDocs.size);doc.reportKind=doc.saveAs?'copy':doc.reportKind||'primary';monthDocs.set(doc.id,doc);send(doc);
      });return;
    }
    if(url==='/api/air/documents')send([...monthDocs.values()].map(d=>({id:d.id,name:d.name,reportMonth:d.reportMonth,reportKind:d.reportKind,isDefault:d.reportKind==='primary'})));
    else send(monthDocs.get(url.split('/').pop()));return;
  }
  if (url === '/api/air/documents' && req.method === 'POST') {
    let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
      const doc=JSON.parse(body);saves.push(doc);
      setTimeout(()=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(failSave?{code:429,message:'fixture rate limited'}:{code:0,data:{...doc,id:'101',updatedAt:'2026-10-31T18:00:00Z'}}));},200);
    });return;
  }
  if (url === '/api/air/documents' && failList) {
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:500,message:'fixture list failed'}));return;
  }
  if (url.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    let data = [];
    if (url.includes('health')) data = { status: 'healthy' };
    if (url.includes('table-map')) data = { groups: [], tables: [] };
    if (url.includes('capabilities')) data = { tools: [], prompt: 'fixture', sources: [] };
    res.end(JSON.stringify({ code: 0, data })); return;
  }
  if (url === '/__platform/adc/client.js') { res.setHeader('Content-Type', 'text/javascript'); res.end(realAdcMode ? realAdc : adc); return; }
  if (url.startsWith('/adc-agent/')) { res.setHeader('Content-Type', 'text/html'); res.end(realAdcMode ? '<!doctype html><html class="dark"><head><style>body{margin:0;height:100vh;background:#fff;color:#111}html.dark body{background:#111;color:#eee}</style></head><body><button type="button" onclick="window.__newChats=(window.__newChats||0)+1"><i>+</i> 新建对话</button><textarea placeholder="发送消息"></textarea></body></html>' : '<textarea></textarea>'); return; }
  // Simulate a base that routes /dev (or all HTML paths when htmlFallback is active) back to the report.
  const file = url === '/' || url === '/dev' || (htmlFallback && url.endsWith('.html')) ? 'static/index.html'
    : url.startsWith('/static/') ? url.slice(1) : 'static' + url;
  const target = path.resolve(root, file);
  if (!target.startsWith(root + path.sep) || !fs.existsSync(target) || fs.statSync(target).isDirectory()) { res.statusCode = 404; res.end(); return; }
  const ext = path.extname(target);
  res.setHeader('Content-Type', { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' }[ext] || 'application/json');
  let content = fs.readFileSync(target);
  if (ext === '.html') {
    content = content.toString().replace(/<script>\s*\/\*\s*\n \* ADCChat v1\.4[\s\S]*?<\/script>/,
      `<script src="${nested ? prefix : '/'}__platform/adc/client.js"></script>`)
      .replace('const onSite = ADC_ORIGINS.includes(location.origin);', 'const onSite = true;');
    if (req.url.includes('sandbox=1')) res.setHeader('Content-Security-Policy', 'sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads');
  }
  res.end(content);
});
async function saveFlow(page,origin){
  await page.goto(origin+'/');
  await page.locator('#airReport .kit-nav-item').first().waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  const save=page.locator('[data-air="save"]');
  failSave=true;
  await save.click();
  await page.keyboard.press('Control+s');await page.keyboard.press('Control+s');
  await page.locator('#airStatus').filter({hasText:'保存失败'}).waitFor();
  assert.equal(saves.length,1,'Double save shortcuts must share the pending save');
  assert(await save.isEnabled(),'Failed save remains retryable');
  failSave=false;
  await save.click();
  const title=page.locator('#airReport [data-edit="title"]');
  await title.fill('保存期间修改标题');await title.press('Tab');
  await page.locator('#airStatus').filter({hasText:'后续修改尚未保存'}).waitFor();
  assert.equal(saves[0].saveKey,saves[1].saveKey,'Retry reuses stable first-save key');
  assert.equal(saves[1].template.title.zh,'埃及代表处交付与服务维护月报');
  assert.equal(await title.textContent(),'保存期间修改标题','Response must not overwrite edits made during save');
  assert(await save.isEnabled(),'Edits made during save must remain dirty');
  failList=true;
  await save.click();
  await page.locator('#airStatus').filter({hasText:'月报已保存，列表刷新失败'}).waitFor();
  assert.equal(saves.length,3);
  assert.equal(saves[2].id,'101');
  assert.equal(saves[2].template.title.zh,'保存期间修改标题');
  assert(await save.isDisabled(),'List refresh failure does not undo successful save');
  failList=false;
  console.log('PASS: duplicate-save guard, stable retry key, edits during save, and successful save with failed list refresh.');
}
async function monthFlow(page,origin){
  monthMode=true;
  const base=JSON.parse(fs.readFileSync(path.join(root,'static/air/default-template.json'),'utf8'));
  monthDocs.set('101',{...base,id:'101',reportMonth:'2026-10',reportKind:'primary'});
  monthDocs.set('102',{...base,id:'102',reportMonth:'2026-10',reportKind:'history'});
  await page.goto(origin+'/');
  await page.locator('#airReport h1').waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  await page.evaluate(()=>document.querySelector('[data-air="new"]').click());
  await page.locator('#airStatus').filter({hasText:'已打开该月份已有的月报'}).waitFor();
  assert.equal(monthDocs.size,2,'New in same month must open existing report');
  assert.equal(await page.locator('#airReportList > button').count(),1);
  assert.equal(await page.locator('#airReportList details button').count(),1,'Legacy duplicate stays accessible as history');
  await page.locator('#airMonth').fill('2026-11');await page.locator('#airMonth').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('#airMonth').value==='2026-11'&&document.querySelector('[data-air="save"]').disabled===false);
  await page.locator('[data-air="save"]').click();
  await page.locator('#airStatus').filter({hasText:'已保存到服务器'}).waitFor();
  assert.equal(monthDocs.size,3);
  assert.equal(monthDocs.get('101').reportMonth,'2026-10','Changing month cannot overwrite October');
  await page.locator('#airMonth').fill('2026-10');await page.locator('#airMonth').dispatchEvent('change');
  await page.locator('#airStatus').filter({hasText:'已打开该月份已有的月报'}).waitFor();
  await page.evaluate(()=>document.querySelector('[data-air="copy"]').click());
  await page.locator('.air-dlg input').waitFor();
  await page.locator('.air-dlg button[data-v="yes"]').click();
  await page.locator('#airStatus').filter({hasText:'已保存到服务器'}).waitFor();
  assert.equal(monthDocs.size,4,'Explicit save as adds a copy');
  assert.equal([...monthDocs.values()].filter(d=>d.reportKind==='copy').length,1);
  assert.match(await page.locator('#airReportName').textContent(),/副本/);
  console.log('PASS: one default per month, existing-month navigation, preserved October, explicit save-as copy, accessible legacy history.');
}
async function realAdcFlow(page,origin){
  realAdcMode=true;
  try{
    await page.goto(origin+'/');await page.locator('#airReport h1').waitFor();
    const gist=()=>page.evaluate(()=>window.API.post('/api/ai-report/cell/gist',{month:'2026-10',items:[{id:'c1',title:'t',prompt:'p',result:{n:1}}]}));
    for(let i=0;i<2;i++){
      const {_rounds,...payload}=await gist();
      assert.deepEqual(payload,{gists:{c1:'要点'}});
      assert.equal(_rounds.length,1,'Each ADC action returns its own model-round statistics');
      const round=_rounds[0];
      assert.equal(round.index,1);assert.equal(round.model,'ADC');assert.equal(round.estimated,true);
      assert(round.inputTokens>0&&round.outputTokens>0);
      assert(Number.isFinite(round.ms)&&round.ms>=0);
      assert(Number.isFinite(round.generationMs)&&round.generationMs>=1);
      assert(Number.isFinite(round.tps)&&round.tps>0);
      assert.equal(round.ttftMs,null);assert(Number.isFinite(Date.parse(round.at)));
    }
    const asks=await page.evaluate(()=>window.__adcAsks),calls=await page.evaluate(()=>window.__adcNewSession);
    assert.equal(calls,0,'Real ADC sessions are never created through the newSession API');
    assert.equal(asks.length,2);
    assert(asks.every(a=>a.viaPage&&a.composer),'AI report requests are typed into the embedded ADC page');
    assert.deepEqual(asks.map(a=>a.newChats),[1,2],'Each AI report action opens one chat with the page\'s own 新建对话 button');
    assert(asks.every(a=>!a.fresh),'A page-created chat needs no fresh-task note');
    await page.evaluate(()=>window.OpsLog.flush());
    await page.waitForFunction(()=>true);
    const pageAsks=()=>opsReports.filter(e=>e.kind==='adc'&&e.detail.viaPage===true);
    for(let i=0;i<20&&pageAsks().length<2;i++)await page.waitForTimeout(100);
    const adcLogs=pageAsks();
    assert(opsReports.some(e=>e.kind==='adc'&&e.detail.owner==='panel'),'Assistant panel conversations are logged too');
    assert.equal(adcLogs.length,2,'Every ADC request is reported to the interaction log');
    assert(adcLogs.every(e=>e.status==='ok'&&e.detail.owner==='air'&&e.detail.viaPage===true&&e.detail.newChat===true&&e.detail.prompt&&e.detail.answer&&e.header==='air'));
    await page.evaluate(()=>window.DragonClaw.open());
    if(!(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open'))))await page.locator('#aiBarFrameToggle').click();
    const look=()=>page.evaluate(()=>{const f=document.getElementById('aiBarFrame'),d=f.contentDocument;return {dark:d.documentElement.classList.contains('dark'),bg:getComputedStyle(d.body).backgroundColor,filter:f.style.filter};});
    await page.waitForFunction(()=>!document.getElementById('aiBarFrame').contentDocument.documentElement.classList.contains('dark'));
    assert.deepEqual(await look(),{dark:false,bg:'rgb(255, 255, 255)',filter:''},'The page\'s own light theme is used when it has one');
    await page.evaluate(()=>{document.getElementById('aiBarFrame').contentDocument.body.style.background='#000';});
    await page.waitForFunction(()=>document.getElementById('aiBarFrame').style.filter.includes('invert'));
    assert.equal(await page.evaluate(()=>!!document.getElementById('aiBarFrame').contentDocument.getElementById('dc-invert-fix')),true,'Images are inverted back');
    const btn=()=>page.locator('#aiBarFrameTheme').textContent();
    assert.equal(await btn(),'原色');
    await page.evaluate(()=>document.getElementById('aiBarFrameTheme').click());
    assert.equal((await look()).filter,'','Clicking 原色 removes the inversion even though the page still looks dark');
    assert.equal(await btn(),'反色');
    await page.evaluate(()=>{document.getElementById('aiBarFrame').contentDocument.body.style.color='#eee';});
    await new Promise(r=>setTimeout(r,400));
    assert.equal((await look()).filter,'','A manual choice is not overridden by auto detection');
    await page.evaluate(()=>document.getElementById('aiBarFrameTheme').click());
    assert(( await look()).filter.includes('invert'),'Clicking 反色 always inverts');
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('api_test_aibar')).frameInvert),true,'The choice is remembered');
    await page.evaluate(()=>{const s=JSON.parse(localStorage.getItem('api_test_aibar'));delete s.frameInvert;localStorage.setItem('api_test_aibar',JSON.stringify(s));});
    console.log('PASS: real ADC requests go through the embedded page and its own 新建对话, never the newSession API; embedded page is light by default (native theme or inversion) and the 反色/原色 toggle always takes effect.');
  }finally{realAdcMode=false;}
}
async function opsFlow(page,origin){
  opsMode=true;opsQueries.length=0;
  try{
    await page.goto(origin+'/dev.html');
    await page.locator('#srcCb input').waitFor();
    await page.waitForFunction(()=>window.OpsLog&&window.SRC_TBL_ID&&window.SRC_TBL_ID.brand_new_tbl);
    if(await page.locator('#aiBar').isVisible()) await page.locator('#aiBarClose').click();
    assert(opsQueries.includes('/api/ops/tables/refresh dev'),'Opening the developer page refreshes the business table list once');
    await page.locator('#srcCb input').click();
    const items=await page.locator('#srcCb li').evaluateAll(list=>list.map(li=>({v:li.dataset.v,text:li.textContent,dim:li.classList.contains('dim')})));
    assert.deepEqual(items.map(i=>i.v),['risk_task_new','brand_new_tbl','gone_tbl','other_tbl','failing_tbl','empty_tbl'],
      'Latest list first, tables missing from it next, failed and empty tables last (catalog order within each group)');
    const item=v=>items.find(i=>i.v===v);
    assert(item('failing_tbl').text.includes('失败 2')&&item('failing_tbl').dim,'Failed tables carry a failure count tag and are dimmed');
    assert(item('brand_new_tbl').text.includes('新增')&&item('brand_new_tbl').text.includes('新出现的表'),'New tables from the latest list are tagged');
    assert(item('gone_tbl').text.includes('清单外'),'Tables missing from the latest list are tagged');
    assert(!item('risk_task_new').text.includes('失败'));
    await page.keyboard.press('Escape');
    await page.locator('#menuSearch').fill('交互日志');
    await page.locator('#leftPanel .ep').filter({hasText:'交互日志'}).click();
    await page.locator('#logCard').waitFor({state:'visible'});
    await page.locator('#logList .log-it').first().waitFor();
    assert.equal(await page.locator('#logList .log-it').count(),6);
    const op=page.locator('#logList .log-it.k-ai');
    await op.locator(':scope > summary').click();
    assert.deepEqual(await op.locator('.log-rounds tbody tr').evaluateAll(rows=>rows.map(r=>r.cells[2].textContent)),['find_value、query','（给出回复）'],'Each model round lists the tools it asked for');
    assert.match(await op.locator('.log-tools').textContent(),/suggest_tables（预取）.*query 缓存/);
    const model=page.locator('#logList .log-it.k-model.s-error');
    await model.locator(':scope > summary').click();
    assert.match(await model.locator('.log-body').textContent(),/模型接口失败[\s\S]*glm-52[\s\S]*模型提问/);
    const perf=page.locator('#logList .log-it.k-model.s-ok');
    await perf.locator(':scope > summary').click();
    assert.match(await perf.locator('.log-body').textContent(),/明确启用[\s\S]*检测到思考[\s\S]*正文 token110[\s\S]*思考 token200[\s\S]*37.43 tok\/s/);
    await page.locator('#logKw').fill('MODEL-INVOKE');
    const logDownload=page.waitForEvent('download');
    await page.locator('#logExport').click();
    const download=await logDownload;
    const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
    assert.equal(exported.query.q,'MODEL-INVOKE');
    assert.equal(exported.logs.find(x=>x.title.includes('MODEL-INVOKE')).detail.performance.thinkingTokens,200);
    await page.locator('#logKw').clear();
    const tables=page.locator('#logList .log-it.k-tables');
    assert.equal(await tables.evaluate(el=>el.open),true,'The latest table refresh is expanded and highlighted');
    assert.match(await tables.locator('.log-diff .add summary').textContent(),/新增 1 张表/);
    assert.match(await tables.locator('.log-diff .del summary').textContent(),/减少 1 张表/);
    assert.match(await tables.locator('.log-diff .add .log-tbl').textContent(),/brand_new_tbl.*新增/);
    const failed=page.locator('#logList .log-it.k-db.s-error');
    assert.match(await failed.locator(':scope > summary').textContent(),/失败/);
    await failed.locator(':scope > summary').click();
    assert.match(await failed.locator('pre').first().textContent(),/SELECT \* FROM failing_tbl/);
    assert.match(await failed.locator('.log-body').textContent(),/失败 2/,'Tables in a log entry show their failure tag');
    await page.locator('#logKind').selectOption('adc');
    await page.waitForFunction(()=>true);
    await page.locator('#logRange').selectOption('d:7');
    await page.waitForTimeout(200);
    assert(opsQueries.some(q=>q.includes('kind=adc')&&q.includes('days=7')&&q.includes('limit=1000')),'Filters are sent to the log API');
    console.log('PASS: business table refresh on open, latest-list ordering with failure/new/missing tags, interaction log tool with highlighted table diff and filters.');
  }finally{opsMode=false;}
}
async function environmentFlow(page,origin){
  monthMode=false;
  await page.goto(origin+'/');await page.locator('#airReport h1').waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  await page.locator('#airDeveloperOpen').click();
  const frame=page.frameLocator('#airDeveloper iframe');
  const select=frame.locator('select[aria-label="数据环境"]');
  await select.waitFor();await page.waitForTimeout(100);
  assert.equal(await select.inputValue(),'local');
  const contrast=async locator=>locator.evaluate(el=>{
    const css=getComputedStyle(el),rgb=text=>text.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;});
    const luminance=text=>rgb(text).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
    const a=luminance(css.color),b=luminance(css.backgroundColor);return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
  });
  assert(await contrast(select)>=4.5,'Environment control text must contrast with its background');
  assert(await contrast(select.locator('option[value="remote"]'))>=4.5,'Expanded options remain readable');
  assert(await frame.locator('#apiBase').evaluate(el=>el.readOnly));
  page.on('dialog',d=>d.accept());
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),select.selectOption('remote')]);
  assert.equal(environmentMode,'remote');assert.equal(environmentRevision,1);
  await page.locator('#airReport h1').waitFor();
  nativeEnvironment=true;
  await page.goto(origin+'/');await page.locator('#airReport h1').waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  await page.locator('#airDeveloperOpen').click();
  const lock=frame.locator('.data-environment-lock');
  await lock.waitFor();await page.waitForTimeout(100);
  assert.equal(await select.inputValue(),'remote');assert(await select.isDisabled());assert(!(await select.isVisible()),'Locked native select is replaced by a read-only badge');
  assert.match(await lock.textContent(),/远端数字人基座 · 已锁定/);
  assert(await contrast(lock)>=4.5,'Locked environment badge remains readable');
  const screenshotDir=process.env.UI_SCREENSHOTS;if(screenshotDir){fs.mkdirSync(screenshotDir,{recursive:true});await frame.locator('.topbar').screenshot({path:path.join(screenshotDir,'environment-selector.png')});}
  const originalViewport=page.viewportSize();
  for(const width of [1280,768,390]){
    await page.setViewportSize({width,height:850});
    const bounds=await lock.evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth};});
    assert(bounds.left>=0&&bounds.right<=bounds.width,'Environment control stays visible at width '+width);
  }
  await page.setViewportSize(originalViewport);
  console.log('PASS: developer environment selector, shared profile switch and reload, native-base switch lock.');
}
async function stopFlow(page,origin){
  nativeEnvironment=false;monthMode=false;
  await page.goto(origin+'/');await page.locator('#airReport .kit-nav-item').first().waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  await page.evaluate(()=>{
    window.__modelCalls=0;window.__stopCalls=0;window.__late=[];
    ADCChat.ask=async(_prompt,options)=>{window.__modelCalls++;await new Promise(resolve=>window.__late.push(()=>{options.onUpdate('{"type":"answer","text":"LATE RESPONSE MUST NOT APPEAR"}');resolve();}));};
    ADCChat.stop=()=>window.__stopCalls++;
  });
  const pending=page.locator('#airReport .air-chapter').nth(2).locator('.air-pending');
  await pending.nth(0).click();await page.locator('#airChat [data-try]').click();
  await page.waitForFunction(()=>window.__modelCalls===1);
  await pending.nth(1).click();await page.locator('#airChat [data-try]').click();
  await page.locator('#airStop').click();
  await page.waitForFunction(()=>document.querySelector('#airStop').hidden);
  assert.equal(await page.evaluate(()=>window.__stopCalls),1,'Only active ADC conversation receives stop');
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(()=>window.__modelCalls),1,'Queued cells and correction loops must never call the model after stop');
  assert.equal(await page.locator('#airReport').textContent().then(t=>t.includes('LATE RESPONSE')),false);
  assert.equal(await page.locator('#airChat').textContent().then(t=>t.includes('LATE RESPONSE')),false);
  await pending.nth(0).click();await page.locator('#airChat [data-try]').click();
  await page.waitForFunction(()=>window.__modelCalls===2);
  await page.evaluate(()=>window.__late.shift()());
  await page.waitForTimeout(100);
  assert(await page.locator('#airStop').isVisible(),'Old late response cannot clear the fresh generation');
  assert.equal(await page.locator('#airChat').textContent().then(t=>t.includes('LATE RESPONSE')),false);
  await page.locator('#airChat [data-stop-generation]').click();
  await page.evaluate(()=>window.__late.splice(0).forEach(resolve=>resolve()));
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>window.__modelCalls),2,'A fresh generation works after cancellation');
  assert(await page.locator('#airStop').isHidden());
  const sandbox=await page.evaluate(async()=>{
    const controller=new AbortController();
    const promise=AiReportSandbox.run({input:{},compute:'function compute(){while(true){}}',render:'function render(){return "";}'},{signal:controller.signal});
    setTimeout(()=>controller.abort(),30);
    try{await promise;return false;}catch(e){return e.name==='AbortError'&&!document.querySelector('iframe[aria-hidden="true"]');}
  });
  assert(sandbox,'Stopping computation must remove its sandbox and reject the result');
  console.log('PASS: active and queued cell cancellation, ADC stop, ignored late responses, no retries, and fresh generation after stop.');
}
async function concurrencyFlow(page,origin){
  nativeEnvironment=false;monthMode=false;
  await page.goto(origin+'/');await page.locator('#airReport .kit-nav-item').first().waitFor();
  if(await page.locator('#aiBar').isVisible())await page.locator('#aiBarClose').click();
  const ids=await page.evaluate(()=>{
    const cells=AiReportApp.state.doc.chapters.flatMap(c=>c.cells).filter(c=>c.prompt&&!c.recipe),ids=cells.slice(0,8).map(c=>c.id);
    window.__requests=0;window.__active=0;window.__maxActive=0;window.__release=[];
    ADCChat.ask=async(prompt,options)=>{
      if(options.protocol!=='application-json-v1')throw new Error('Cell generation must own its JSON tool protocol');
      const marker=prompt.match(/TEST_CELL_\d+/)?.[0];window.__requests++;window.__active++;window.__maxActive=Math.max(window.__maxActive,window.__active);
      await new Promise(resolve=>window.__release.push(()=>{window.__active--;options.onUpdate(JSON.stringify({type:'recipe',reply:'ok',recipe:{summary:{zh:'测试'},sources:[],compute:'function compute(){return {marker:'+JSON.stringify(marker)+'};}',render:'function render(result,kit){return kit.text(result.marker);}',narrative:null}}));resolve();}));
    };
    ids.forEach((id,i)=>{const c=AiReportApp.find(id).cell;c.prompt='只显示标记 TEST_CELL_'+i+'，不需要标题';c.chat=[{role:'ai',kind:'prompt',text:c.prompt}];});
    AiReportApp.render();window.__jobs=ids.map(id=>AiReportApp.tryPrompt(id));
    return [...ids,cells[8].id];
  });
  await page.waitForFunction(()=>window.__requests===1);
  await page.locator('.air-cell-tools [data-cell-chat="'+ids[8]+'"]').click();
  await page.locator('#airChat .air-composer textarea').fill('未发送的消息草稿');
  await page.locator('#airChat [data-edit-prompt]').click();
  await page.locator('#airChat [data-prompt-draft]').fill('尚未保存的提示词编辑');
  for(let i=0;i<8;i++){
    await page.waitForFunction(n=>window.__requests===n,i+1);
    await page.evaluate(()=>window.__release.shift()());
  }
  await page.evaluate(()=>Promise.all(window.__jobs));
  const result=await page.evaluate(ids=>({requests:window.__requests,max:window.__maxActive,values:ids.slice(0,8).map(id=>AiReportApp.find(id).cell.output?.result?.marker),selected:AiReportApp.state.selected}),ids);
  assert.equal(result.requests,8);assert.equal(result.max,1,'One ADC lane serializes eight independent jobs');
  assert.deepEqual(result.values,Array.from({length:8},(_,i)=>'TEST_CELL_'+i));
  assert.equal(result.selected,ids[8],'Another cell completion cannot change selection');
  await page.locator('.air-cell-tools [data-cell-chat="'+ids[0]+'"]').click();
  await page.locator('.air-cell-tools [data-cell-chat="'+ids[8]+'"]').click();
  assert.equal(await page.locator('#airChat .air-composer textarea').inputValue(),'未发送的消息草稿');
  assert.equal(await page.locator('#airChat [data-prompt-draft]').textContent(),'尚未保存的提示词编辑');
  await page.evaluate(()=>{AiReportApp.state.saveKey='different-report';AiReportApp.render();});
  assert.equal(await page.locator('#airChat .air-composer textarea').inputValue(),'','Drafts cannot cross report boundaries');
  assert.equal(await page.locator('#airChat [data-prompt-draft]').count(),0);
  console.log('PASS: eight cell jobs serialize and retain separate results; switching away/back preserves selection, message draft and prompt edits.');
}
let browser;
async function contained(page, selector = '#aiBar') {
  await page.waitForFunction(selector => {
    const r = document.querySelector(selector).getBoundingClientRect(), v = visualViewport;
    return r.width > 0 && r.x >= v.offsetLeft - 1 && r.y >= v.offsetTop - 1 && r.right <= v.offsetLeft + v.width + 1 && r.bottom <= v.offsetTop + v.height + 1;
  }, selector, { timeout: 2000 });
  const box = await page.locator(selector).boundingBox();
  const view = await page.evaluate(() => {
    const v = visualViewport;
    return { x: v.offsetLeft, y: v.offsetTop, width: v.width, height: v.height };
  });
  assert(box, selector + ' visible');
  if(selector === '#aiBar') assert.equal(await page.locator(selector).evaluate(el => el.scrollLeft),0,'Outer panel must not scroll sideways');
  assert(box.x >= view.x - 1 && box.y >= view.y - 1 && box.x + box.width <= view.x + view.width + 1 && box.y + box.height <= view.y + view.height + 1,
    `Bounds ${selector}: ${JSON.stringify({ box, view })}`);
}
async function drag(page, selector, dx, dy, within = { x: 30, y: 20 }) {
  const r = await page.locator(selector).boundingBox();
  const x = r.x + within.x, y = r.y + within.y;
  await page.mouse.move(x, y); await page.mouse.down();
  for (let i = 1; i <= 4; i++) {
    await page.mouse.move(x + dx * i / 4, y + dy * i / 4);
    await contained(page);
  }
  await page.mouse.up();
}
async function workspace(page, origin, pathname, sandbox = false) {
  await page.goto(origin + pathname + (sandbox ? '?sandbox=1' : ''));
  await page.waitForFunction(() => !!window.DragonClaw && !document.body.classList.contains('air-booting'));
  console.log('Workspace:', pathname, sandbox ? 'sandbox' : 'normal');
  if(await page.locator('#aiBar').isVisible()) await page.locator('#aiBarClose').click();
  await page.locator('#airReport .kit-nav-item').first().waitFor();
  assert.equal(await page.locator('#airReport .air-chapter').count(),10);
  assert.equal(await page.locator('#airReport .air-cell').count(),18);
  assert.equal(await page.locator('#airReport .kit-nav-item').count(),8);
  assert.equal(await page.locator('#airReport h1').textContent().then(text=>text.replace(/✦/g,'').trim()),'埃及代表处交付与服务维护月报');
  assert.equal(await page.locator('#airReport .air-logo').getAttribute('src'),'air/default-logo.png');
  await page.locator('#airReport .kit-nav-item').last().click();
  await page.locator('#airReport .is-jump-target').waitFor();

  if(await page.locator('#aiBar').isVisible()) await page.locator('#aiBarClose').click();
  const url = page.url();
  // Open with a mouse click: opening must leave report DOM and dirty content intact.
  await page.locator('#airReport').evaluate(el => el.dataset.unsavedFixture = 'preserve');
  await page.locator('#airDeveloperOpen').click();
  await page.locator('#airDeveloper iframe:not([hidden])').waitFor();
  console.log('Developer iframe loaded');
  await contained(page, '#airDeveloper');
  if(!sandbox){
    const zoom=await page.context().newCDPSession(page);
    await zoom.send('Emulation.setPageScaleFactor',{pageScaleFactor:1.5});
    await contained(page,'#airDeveloper');
    await zoom.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});
    await contained(page,'#airDeveloper');
    await zoom.detach();
  }
  const frame = page.frameLocator('#airDeveloper iframe');
  await frame.locator('#menuSearch').waitFor();
  await frame.locator('#leftPanel .grp').first().waitFor();
  console.log('Developer endpoints rendered');
  await frame.locator('#menuSearch').fill('数据库测试');
  await frame.locator('#leftPanel .ep').filter({hasText:'数据库测试一键套件'}).click();
  await frame.locator('#diagnosticsCard').waitFor({state:'visible'});
  await frame.locator('[data-start]').click();
  await frame.locator('[data-progress]').filter({hasText:'已完成：3/3'}).waitFor();
  assert.equal(await frame.locator('[data-results] tr').count(),3);
  assert.equal(await frame.locator('[data-results] td[data-status=fail]').count(),1);
  if(process.env.UI_SCREENSHOTS && pathname==='/'&&!sandbox)await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS,'database-diagnostics.png')});
  const downloadEvent=page.waitForEvent('download');await frame.locator('[data-export]').click();
  const download=await downloadEvent;const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.equal(exported.configuration.runtime.pid,123);assert.equal(exported.configuration.configurationOrigins.BUSINESS_DATASOURCE_NAME.source,'process-environment');assert.equal(exported.results[1].upstream[0].request.requestId,'base-request-fixture');assert.deepEqual(exported.results[1].upstream[0].request.payloadKeys,['datasourceName','sql']);assert.equal(exported.results[1].datasourceMatch.configuredNameListed,false);
  assert.equal(exported.summary.fail,1);assert.equal(exported.results[1].upstream[0].httpStatus,400);
  assert.equal(exported.results[1].upstream[0].requestId,'00000000-0000-4000-8000-000000000000');
  for(const value of ['fixture-secret','fixture-password','private-record','do-not-export'])assert(!JSON.stringify(exported).includes(value));
  await frame.locator('[data-lang]').click();assert.equal(await frame.locator('[data-start]').innerText(),'Run all checks');
  await frame.locator('[data-lang]').click();
  diagnosticSlow=true;const before=diagnosticCalls.length;
  await frame.locator('[data-start]').click();await page.waitForFunction(()=>true);
  await frame.locator('[data-stop]').click();await frame.locator('[data-progress]').filter({hasText:'已停止'}).waitFor();
  await page.waitForTimeout(600);assert(diagnosticCalls.length-before<=1,'Stopped suite must not send later probes');diagnosticSlow=false;
  await frame.locator('[data-retry]').click();await frame.locator('[data-progress]').filter({hasText:'已完成：3/3'}).waitFor();
  console.log('PASS: diagnostic menu, scoped sequential suite, partial stop/resume, bilingual labels and sanitized JSON export.');
  if(process.env.UI_SCREENSHOTS && pathname === '/' && !sandbox) await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS,'developer-modal.png')});
  assert.equal(await frame.locator('#apiBase').inputValue(), pathname + 'api');
  assert.equal(await frame.locator('#aiBar').count(), 0);
  assert.equal(page.url(), url);
  await frame.locator('#menuSearch').fill('health');
  await frame.locator('#menuSearch').press('Escape');
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open);
  assert.equal(await page.locator('#airReport').getAttribute('data-unsaved-fixture'), 'preserve');
  await page.locator('#airDeveloperOpen').click();
  assert.equal(await frame.locator('#menuSearch').inputValue(), 'health');
  // The return control closes the modal rather than navigating the iframe or report.
  await frame.locator('a.topbar-ai[href="./"]').click();
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open);
  await page.locator('#airDeveloperOpen').click();
  await frame.locator('.topbar button.topbar-ai').click();
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open && !document.querySelector('#aiBar').classList.contains('collapsed'));
  await contained(page);
  assert.equal(await page.locator('#aiBarQ').evaluate(el => el === document.activeElement),true,'Opening the shared assistant should focus its input');
  assert.equal(page.url(), url);
  await page.locator('#aiBarClose').click();
  await page.locator('#airDeveloperOpen').click();
  await page.locator('.air-developer-close').click();
  await page.waitForFunction(() => document.querySelector('#airDeveloperOpen').getAttribute('aria-expanded') === 'false');
  assert.equal(await page.locator('#airDeveloperOpen').evaluate(el => el === document.activeElement), true);
  if (!sandbox) {
    await page.setViewportSize({ width: 390, height: 640 });
    // Toolbar can scroll off at this size; invoke the already-tested button handler.
    await page.locator('#airDeveloperOpen').evaluate(el => el.click());
    await contained(page, '#airDeveloper');
    await page.locator('.air-developer-close').click();
    await page.setViewportSize({ width: 1280, height: 800 });
  }
}
async function assistantFeedback(page){
  const zOrder=await page.evaluate(()=>({
    toggle:Number(getComputedStyle(document.querySelector('.air-chrome-toggle')).zIndex)||0,
    bar:Number(getComputedStyle(document.getElementById('aiBar')).zIndex)||0,
  }));
  assert(zOrder.toggle<zOrder.bar,`Top bar collapse toggle z-index (${zOrder.toggle}) must stay below #aiBar (${zOrder.bar})`);
  // Cell chat must be able to establish the first session even while #aiBar is collapsed.
  await page.locator('#aiBarClose').click();
  const cellFirstReply=await page.evaluate(async()=>{
    window.ADCChat.configured=false;
    window.ADCChat.ask=async(_q,options)=>{window.ADCChat.configured=true;options.onUpdate('格子首问成功');};
    return window.DragonClaw.conversation('air',true,({ask})=>ask('月报格子首问'));
  });
  assert.equal(cellFirstReply,'格子首问成功');
  await page.evaluate(()=>window.DragonClaw.open());
  await page.evaluate(()=>{
    document.getElementById('aiBarAgent').checked=false;
    window.ADCChat.configured=false;
    window.ADCChat.ask=(_q,options)=>new Promise(resolve=>{
      window.__finishFirst=()=>{window.ADCChat.configured=true;options.onUpdate('首次对话完成');resolve();};
    });
    void window.DragonClaw.send('首次连接测试');
  });
  await page.waitForFunction(()=>!!window.__finishFirst);
  const toggle=page.locator('#aiBarFrameToggle');
  assert.equal(await toggle.getAttribute('aria-disabled'),'true');
  assert.equal(await toggle.evaluate(el=>el.disabled),false,'Waiting control must remain clickable to explain the restriction');
  await toggle.click({force:true});
  assert.match(await page.locator('#aiBarFrameHint').innerText(),/首次对话.*暂不能展开/);
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),false);
  await page.evaluate(()=>window.__finishFirst());
  await page.waitForFunction(()=>document.getElementById('aiBarFrameToggle').getAttribute('aria-disabled')==='false');
  await toggle.click();
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),true);
  await toggle.click();
  // After initial connection, normal in-flight replies allow the original page to be shown.
  await page.evaluate(()=>{delete window.__finishFirst;void window.DragonClaw.send('普通对话测试');});
  await page.waitForFunction(()=>!!window.__finishFirst);
  await toggle.click();
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),true);
  await page.evaluate(()=>window.__finishFirst());
  await page.waitForFunction(()=>!document.getElementById('aiBarSend').classList.contains('busy'));
  await toggle.click();

  const cases=[
    {status:200,json:{code:500,message:'数据源不存在: fixture-readonly; token="fixture-secret-value" <img src=x onerror=alert(1)>'}},
    {status:503,json:{code:-1,message:'基座 API 暂时不可用'}},
    {status:422,json:{detail:[{loc:['body','table'],msg:'Field required',input:'do-not-copy-validation-input'}]}},
    {status:502,raw:'<html>gateway error token=do-not-copy-html</html>'},
    {network:true},
  ];
  for(const fixture of cases){
    executionFailure=fixture;
    await page.evaluate(async()=>{
      document.getElementById('aiBarAgent').checked=true;
      window.__errorPrompts=[];
      let step=0;
      window.ADCChat.ask=async(prompt,options)=>{
        window.__errorPrompts.push(prompt);
        options.onUpdate(step++===0?'```dragon-action\n'+JSON.stringify({tool:'describe_table',args:{source:'netcare',table:'fixture_table',password:'do-not-copy-write-values'},reason:'查看表结构测试'})+'\n```':'查询失败，请核对环境与数据源。');
      };
      await window.DragonClaw.send('查看表结构');
    });
    const card=page.locator('.dct').last(), header=card.locator('.dct-h');
    assert.match(await card.locator('.dct-st').innerText(),/失败.*查看详情/);
    assert.equal(await header.getAttribute('aria-expanded'),'false');
    await card.locator('.dct-st').click();
    assert.equal(await header.getAttribute('aria-expanded'),'true');
    const diagnostic=JSON.parse(await card.locator('pre code').innerText());
    assert.equal(diagnostic.httpStatus,fixture.network?null:fixture.status);
    assert.equal(diagnostic.code,fixture.json?.code??null);
    assert.equal(diagnostic.tool,'describe_table');
    assert.deepEqual(diagnostic.args,{source:'netcare',table:'fixture_table'});
    assert.equal(diagnostic.requestId,fixture.network?'':'fixture-error-123');
    if(fixture.status===200) assert.match(diagnostic.message,/数据源不存在: fixture-readonly/);
    if(fixture.status===422) assert.match(diagnostic.message,/body.*table.*Field required/);
    if(fixture.status===502) assert.match(diagnostic.message,/有效 JSON/);
    if(fixture.network) assert.match(diagnostic.message,/网络请求未完成/);
    const exposed=(await card.innerHTML())+await page.evaluate(()=>window.__errorPrompts.join('\n'));
    for(const secret of ['fixture-secret-value','do-not-copy-html','do-not-copy-write-values','do-not-copy-validation-input']) assert(!exposed.includes(secret),'Diagnostic leaked '+secret);
    assert.equal(await card.locator('img').count(),0,'Error text must not execute HTML');
    await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copiedDiagnostic=text;}}}));
    await card.locator('.dcm-copy').click();
    assert.deepEqual(JSON.parse(await page.evaluate(()=>window.__copiedDiagnostic)),diagnostic);
    await header.focus(); await page.keyboard.press('Enter');
    assert.equal(await header.getAttribute('aria-expanded'),'false');
    await page.keyboard.press('Space');
    assert.equal(await header.getAttribute('aria-expanded'),'true');
  }
  executionFailure=null;
  console.log('PASS: first-session wait explanation, normal in-flight expansion, clickable/copyable error details, business/HTTP/validation/non-JSON/network failures and diagnostic redaction.');
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(8000);
  page.on('pageerror', e => {errors.push(e.message);console.error('PAGE:', e.message);});
  await page.addInitScript(() => { try { localStorage.setItem('api_test_aibar', JSON.stringify({ open: true, x: 5000, y: -400, w: 2000, h: 2000 })); } catch {} });
  await page.goto(origin + '/');
  await page.waitForFunction(() => !!window.DragonClaw);
  await contained(page);
  for (const [dx, dy] of [[-6000, -6000], [6000, 6000], [-6000, 6000], [6000, -6000]]) await drag(page, '.aibar-h', dx, dy);
  for (const [dx, dy] of [[-6000, -6000], [6000, 6000]]) await drag(page, '#aiBarBr', dx, dy, { x: 6, y: 6 });
  for (const dx of [-6000, 6000]) await drag(page, '#aiBarRz', dx, 0, { x: 3, y: 120 });
  await page.locator('#aiBarAgent').uncheck({ force: true });
  await page.evaluate(() => window.DragonClaw.send('1+1'));
  await page.locator('.dcm-copy').waitFor();
  for (const selector of ['#aiBarClose', '#aiBarNewSess', '.dcm-actions button', '.dcm-copy', '#aiBarFrameToggle']) {
    const color = await page.locator(selector).first().evaluate(el => getComputedStyle(el).backgroundColor);
    const rgb = color.match(/[\d.]+/g).map(Number);
    assert(rgb.slice(0, 3).every(channel => channel < 100), `${selector}: unexpected bright background ${color}`);
  }
  for (const zoom of ['50', '70', '100']) { await page.locator('#aiBarFrameZoom').selectOption(zoom); await contained(page); }
  await page.locator('#aiBarFrameToggle').click(); await contained(page); await page.locator('#aiBarFrameToggle').click();
  for (const size of [{ width: 1024, height: 600 }, { width: 640, height: 400 }, { width: 320, height: 280 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size); await contained(page);
    await page.locator('#aiBarClose').click(); await page.evaluate(() => window.DragonClaw.open()); await contained(page);
  }
  // Browser zoom/pinch changes the visual viewport without requiring window.resize.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1.75 });
  await page.waitForTimeout(80); await contained(page);
  await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
  await page.waitForTimeout(80); await contained(page);
  if (process.env.UI_SCREENSHOTS) {
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#aiBar').evaluate(el => el.scrollLeft), 0, 'Viewport changes must not scroll outer panel content sideways');
    fs.mkdirSync(process.env.UI_SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: path.join(process.env.UI_SCREENSHOTS, 'dragon-claw-dark.png') });
  }
  await assistantFeedback(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  console.log('Geometry and dark buttons passed.');
  await workspace(page, origin, '/');
  await workspace(page, origin, prefix);
  htmlFallback = true;
  await workspace(page, origin, prefix, true);
  htmlFallback = false;
  assert(!requests.some(url => /\/dev(?:\?|$)/.test(url)), 'Developer mode must not navigate to /dev');
  await saveFlow(page,origin);
  await monthFlow(page,origin);
  await environmentFlow(page,origin);
  await stopFlow(page,origin);
  await concurrencyFlow(page,origin);
  await realAdcFlow(page,origin);
  await opsFlow(page,origin);
  assert.deepEqual(errors, []);
  console.log('PASS: restored geometry, four-edge dragging, both resize handles, dark buttons, iframe zoom, viewport resizing, visual viewport zoom, modal state/focus, root and prefixed API paths, sandboxed embedding.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => { await browser?.close(); server.close(); });
