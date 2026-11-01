(function(){
 'use strict';
 const root=document.getElementById('diagnosticsCard');if(!root)return;
 let english=document.documentElement.lang==='en',report=null,controller=null,running=false,stopped=false;
 const t=(zh,en)=>english?en:zh;
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const clean=x=>String(x||'').replace(/https?:\/\/[^\s"'<>]+/gi,'[URL]').replace(/\bBearer\s+\S+/gi,'Bearer [REDACTED]').replace(/(authorization|cookie|api[_-]?key|token|secret|password)["'\s:=]+[^\s,;}]+/gi,'$1=[REDACTED]').replace(/\b(?:[A-Fa-f0-9]{48,}|sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/g,'[REDACTED]').slice(0,1200);
 const api=()=>document.getElementById('apiBase').value.replace(/\/+$/,'')+'/diagnostics/database';
 const pick=(x,keys)=>Object.fromEntries(keys.filter(k=>['string','boolean','number'].includes(typeof x?.[k])||x?.[k]===null).map(k=>[k,typeof x[k]==='string'?clean(x[k]):x[k]]));
 const runtime=x=>pick(x,['bootId','pid','parentPid','startedAt','uptimeSeconds','listenPort','reloadEnabled','reloadRequested','managedRuntime','workerCount','codeFingerprint','pythonVersion','packageVersion']);
 const requestMeta=x=>({...pick(x,['requestId','bootId','method','endpointPath','scope','businessDatasourceName','sqlFingerprint','attempt','ms','networkErrorType']),payloadKeys:(x?.payloadKeys||[]).filter(k=>['datasourceId','schema','datasourceName','sql','limit'].includes(k))});
 function flags(x){const out=pick(x,['version','hosted','queryUrlConfigured','appSchemaConfigured','businessAssigned','appDatasourceConfigured','identityInjection','tlsVerification','httpTimeoutSeconds','businessDatasourceName']);if(x?.runtime)out.runtime=runtime(x.runtime);if(x?.businessValueShape)out.businessValueShape=pick(x.businessValueShape,['length','hasOuterWhitespace','hasControlCharacters']);if(x?.configurationOrigins){out.configurationOrigins={};for(const key of ['BASE_QUERY_URL','APP_DATASOURCE_ID','APP_SCHEMA','BUSINESS_DATASOURCE_NAME','PORT','WORKERS','RELOAD'])if(x.configurationOrigins[key])out.configurationOrigins[key]=pick(x.configurationOrigins[key],['source','environmentPresentAtLoad','dotenvContainsField','environmentChangedSinceLoad','environmentMatchesLoaded','dotenvMatchesLoaded']);}return out;}
 function safeResult(x){const out=pick(x,['id','table','source','sql','status','message','errorType','requestId','ms','at','rowCount']);if(x.configuration)out.configuration=flags(x.configuration);if(x.runtime)out.runtime=runtime(x.runtime);if(x.datasourceMatch)out.datasourceMatch=pick(x.datasourceMatch,['configuredBusinessName','configuredNameListed','catalogParsed','catalogItemCount','namesComparable','otherNamesExported']);if(Array.isArray(x.upstream))out.upstream=x.upstream.slice(0,4).map(r=>({...pick(r,['httpStatus','code','message','requestId']),...(r.request?{request:requestMeta(r.request)}:{})}));return out;}
 root.innerHTML=`<style>
 #diagnosticsCard{padding:18px;overflow:hidden}#diagnosticsCard .diag-head,#diagnosticsCard .diag-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}#diagnosticsCard h2{font-size:16px;margin:0;flex:1}#diagnosticsCard input[type=text]{flex:1;min-width:180px;border:1px solid var(--border);border-radius:8px;background:var(--bg-soft);color:var(--text-primary);padding:9px 12px;font-size:12px}#diagnosticsCard .diag-description{font-size:12px;color:var(--text-secondary);line-height:1.7;margin-bottom:14px}#diagnosticsCard .diag-scroll{overflow:auto;max-height:65vh}#diagnosticsCard table{width:100%;border-collapse:collapse;font-size:12px}#diagnosticsCard th,#diagnosticsCard td{text-align:left;padding:10px;border-bottom:1px solid var(--border);vertical-align:top}#diagnosticsCard td:last-child{min-width:200px;max-width:520px;overflow-wrap:anywhere}#diagnosticsCard pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0;color:var(--text-secondary);font-size:11px}#diagnosticsCard [data-status=fail]{color:var(--c-danger,#e05252)}#diagnosticsCard [data-status=pass]{color:var(--c-read,#10b981)}#diagnosticsCard [data-status=warning]{color:var(--c-write,#bd8000)}#diagnosticsCard button:disabled{opacity:.5;cursor:not-allowed}
 </style><div class="diag-head"><h2 data-title></h2><button type="button" class="btn btn-ghost" data-lang>EN</button></div>
 <p class="diag-description" data-description></p><div class="diag-controls"><input type="text" class="pathin" data-table aria-label="目标业务表 / Target business table" value="nc_op_sa_sr_problem_detail_all_bg_dwd" spellcheck="false"><label><input type="checkbox" data-full><span data-full-label></span></label></div>
 <div class="diag-controls"><button type="button" class="btn btn-primary" data-start></button><button type="button" class="btn btn-ghost" data-stop disabled></button><button type="button" class="btn btn-ghost" data-export disabled></button><button type="button" class="btn btn-ghost" data-retry disabled></button></div>
 <p class="diag-description" data-runtime></p><p role="status" aria-live="polite" data-progress></p><div class="diag-scroll"><table><thead><tr><th data-case></th><th data-state></th><th data-detail></th></tr></thead><tbody data-results></tbody></table></div>`;
 const q=s=>root.querySelector(s);
 function labels(){
  q('[data-title]').textContent=t('数据库测试一键套件','Database diagnostic suite');
  q('[data-description]').textContent=t('检查分配的应用库与业务库：配置、连接、应用表、元数据、SQL 引号、分页和只读守卫。仅返回诊断信息，不输出业务记录。可选全表扫描使用包内目录，耗时更长；未执行写入、建表或模型调用。','Checks the assigned app and business databases: configuration, connectivity, app tables, metadata, quoting, pagination and local read guards. No business records are exported. Optional full scanning uses the bundled catalog and takes longer. Writes, DDL and model calls are excluded.');
  q('[data-full-label]').textContent=t('扩展：扫描全部业务表字段','Extended: scan all catalog table columns');
  q('[data-start]').textContent=t('一键开始测试','Run all checks');q('[data-stop]').textContent=t('停止','Stop');q('[data-export]').textContent=t('导出诊断日志','Export diagnostic log');q('[data-retry]').textContent=t('重测失败项','Retry failed checks');q('[data-lang]').textContent=english?'中文':'EN';
  q('[data-case]').textContent=t('检查项','Check');q('[data-state]').textContent=t('状态 / 耗时','Status / duration');q('[data-detail]').textContent=t('结果与脱敏错误详情','Result and sanitized error details');
 }
 function draw(){
  labels();const rows=report?.results||[],counts={pass:0,warning:0,fail:0,stopped:0};rows.forEach(r=>counts[r.status]=(counts[r.status]||0)+1);
  const configuration=report?.results?.find(r=>r.id==='configuration')?.configuration||report?.configuration;
  const rt=configuration?.runtime,origin=configuration?.configurationOrigins?.BUSINESS_DATASOURCE_NAME?.source;
  q('[data-runtime]').textContent=configuration?t(`实际业务组：${configuration.businessDatasourceName||'未提供'}；配置来源：${origin||'未提供'}；PID：${rt?.pid??'未提供'}；启动标识：${rt?.bootId||'未提供'}；自动重载：${rt?.reloadEnabled===undefined?'未知':rt.reloadEnabled?'开启':'关闭'}`,`Loaded business group: ${configuration.businessDatasourceName||'unknown'}; origin: ${origin||'unknown'}; PID: ${rt?.pid??'unknown'}; boot: ${rt?.bootId||'unknown'}; reload: ${rt?.reloadEnabled??'unknown'}`):'';
  q('[data-progress]').textContent=report?t(`${running?'测试中':stopped?'已停止':'已完成'}：${rows.length}/${report.total}；通过 ${counts.pass}，警告 ${counts.warning}，失败 ${counts.fail}`,`${running?'Running':stopped?'Stopped':'Finished'}: ${rows.length}/${report.total}; passed ${counts.pass}, warnings ${counts.warning}, failed ${counts.fail}`):t('尚未开始测试','Ready');
  q('[data-results]').innerHTML=rows.map(r=>`<tr><td>${esc(r.label||r.id)}</td><td data-status="${esc(r.status)}">${esc(r.status)} · ${Number(r.ms)||0}ms</td><td>${esc(r.message||'')}<details><summary>${t('查看详情','Details')}</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details></td></tr>`).join('');
  q('[data-start]').disabled=running;q('[data-stop]').disabled=!running;q('[data-export]').disabled=!report;q('[data-retry]').disabled=running||!(report?.pending?.length||rows.some(r=>r.status==='fail'||r.status==='stopped'));q('[data-table]').disabled=running;q('[data-full]').disabled=running;
 }
 async function request(url,body){
  const timeout=setTimeout(()=>controller?.abort(),25000);
  try{
   const response=await fetch(url,{method:body?'POST':'GET',signal:controller.signal,cache:'no-store',...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
   let json;try{json=await response.json();}catch(_){throw Error(t('接口未返回 JSON，HTTP ','Non-JSON response, HTTP ')+response.status);}
   if(!response.ok||json.code!==0)throw Error(clean(json.message||json.error||('HTTP '+response.status)));
   return json.data;
  }finally{clearTimeout(timeout);}
 }
 async function run(retry=false){
  if(running)return;running=true;stopped=false;controller=new AbortController();
  let checks=[];
  try{
   const endpoint=api();
   if(retry){const failed=report.results.filter(r=>r.status==='fail'||r.status==='stopped');checks=[...failed.map(({id,label,table})=>({id,label,table})),...(report.pending||[])];(report.history||=[]).push(...failed);report.results=report.results.filter(r=>r.status!=='fail'&&r.status!=='stopped');report.attempts++;}
   else{
    report={schemaVersion:1,runId:crypto.randomUUID(),startedAt:new Date().toISOString(),results:[],total:0,attempts:1,coverage:{readOnly:true}};draw();
    const meta=await request(endpoint+'?table='+encodeURIComponent(q('[data-table]').value)+'&full='+q('[data-full]').checked);
    checks=meta.checks;report.configuration=flags(meta.configuration);report.coverage={readOnly:true,fullCatalog:!!meta.coverage?.fullCatalog,catalogIsStatic:true,excluded:['writes','DDL','model calls','other databases','business records']};report.total=checks.length;
   }
   report.pending=[...checks];draw();
   for(const check of checks){
    if(stopped)break;controller=new AbortController();const started=Date.now();
    try{const result=await request(endpoint,{id:check.id,table:check.table});if(stopped)break;report.results.push({...safeResult(result),label:check.label});}
    catch(error){report.results.push({...check,status:stopped?'stopped':'fail',message:clean(error.message),ms:Date.now()-started,layer:'browser-to-app'});}
    report.pending.shift();
    draw();
   }
  }catch(error){if(!stopped)report.results.push({id:'suite-api',status:'fail',message:clean(error.message),layer:'browser-to-app'});}
  finally{running=false;controller=null;report.finishedAt=new Date().toISOString();report.stopped=stopped;draw();}
 }
 q('[data-start]').onclick=()=>run();q('[data-retry]').onclick=()=>run(!!report?.configuration);
 q('[data-stop]').onclick=()=>{stopped=true;controller?.abort();q('[data-progress]').textContent=t('正在停止，不再发送后续测试…','Stopping; no further checks will be sent…');};
 q('[data-lang]').onclick=()=>{english=!english;draw();};
 q('[data-export]').onclick=()=>{
  const summary={};for(const r of report.results)summary[r.status]=(summary[r.status]||0)+1;
  const output={...report,summary,exportedAt:new Date().toISOString()};
  const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='AiOps-database-diagnostic-'+report.startedAt.replace(/[:.]/g,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 window.DatabaseDiagnostics={show:()=>{if(!report){const source=document.querySelector('#srcCb input');if(source?.value)q('[data-table]').value=source.value;}draw();}};
 draw();
})();
