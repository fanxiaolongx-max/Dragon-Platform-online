/* Server-side model calls; the browser only receives public configuration and model text. */
(function(){
'use strict';
const base=()=>{const field=document.getElementById('apiBase');if(field?.value)return field.value.replace(/\/+$/,'');const p=location.pathname;return p.slice(0,p.lastIndexOf('/')+1)+'api';};
let snapshot=null,loading=null,lane=Promise.resolve(),busy=0,lastMode='';
const threads=new Map();
const scope=()=>new URL(base(),document.baseURI).pathname;
let channel;try{channel=new BroadcastChannel('aiops-model-'+scope());channel.onmessage=()=>refresh().catch(()=>{});}catch(_){}
function notify(){
 const message={type:'aiops-model-refresh',scope:scope()};
 try{channel?.postMessage(message);}catch(_){}
 if(parent!==window)parent.postMessage(message,'*');
 for(const frame of document.querySelectorAll('iframe'))frame.contentWindow?.postMessage(message,'*');
}
addEventListener('message',event=>{
 const related=event.source===parent&&parent!==window||[...document.querySelectorAll('iframe')].some(frame=>frame.contentWindow===event.source);
 if(related&&event.data?.type==='aiops-model-refresh'&&event.data.scope===scope())refresh().catch(()=>{});
});
async function request(path,body,signal,method){
 signal?.throwIfAborted();
 const response=await fetch(base()+'/ai-models'+path,{method:method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal,cache:'no-store'});
 let json;try{json=await response.json();}catch(_){throw new Error('模型配置接口未返回 JSON，请检查应用版本与代理');}
 signal?.throwIfAborted();
 if(!response.ok||json.code!==0)throw Object.assign(new Error(json.message||'模型接口失败'),{status:json.code||response.status,modelDiagnostic:json.data?.kind==='model_transport'?json.data:undefined});
 if((body||method==='DELETE')&&!['/generate','/test'].includes(path))notify();
 return json.data;
}
async function refresh(){
 if(loading)return loading;
 loading=request('').then(data=>{snapshot=data;window.dispatchEvent(new CustomEvent('aiops-model-change',{detail:{mode:data.mode,config_id:data.config_id}}));return data;}).finally(()=>loading=null);
 return loading;
}
function reset(owner){if(owner)threads.delete(owner);else threads.clear();}
function conversation(owner,fresh,fn,{signal,onState,onDiagnostic}={}){
 onState?.('queued');
 const run=async()=>{
  signal?.throwIfAborted();
  const state=await refresh();signal?.throwIfAborted();
  if(state.mode!=='model'){const force=fresh||lastMode==='model';lastMode='adc';reset(owner);return window.DragonClaw.adcConversation(owner,force,fn,{signal,onState,onDiagnostic});}
  if(lastMode==='adc')reset(owner);lastMode='model';
  const selected=state.items.find(x=>x.id===state.config_id);
  if(!selected||selected.locked)throw new Error('当前模型配置不可用或无法解密，请打开「AI 模型配置」检查');
  const identity=selected.id+':'+selected.revision;
  let thread=threads.get(owner),isNew=fresh||!thread||thread.identity!==identity;
  if(isNew){thread={identity,messages:[]};threads.set(owner,thread);}
  busy++;onState?.('running');
  const clear=()=>{thread.messages=[];isNew=true;};
  const ask=async(prompt,onUpdate,options={})=>{
   signal?.throwIfAborted();
   const messages=[...thread.messages,{role:'user',content:String(prompt)}];
   onDiagnostic?.({kind:'model',stage:'model_request',protocol:selected.protocol,model:selected.model,requestedMaxOutputTokens:options.maxOutputTokens??selected.max_tokens});
   const started=Date.now(),who=owner==='air'?'AI 月报':owner==='panel'?'助理浮窗':owner;
   // 交互日志：和 ADC 对话一样记下提问、回答、耗时和失败原因，模型 API 的问题也能回溯
   const log=(status,title,extra)=>window.OpsLog?.report({kind:'model',status,title,ms:extra.ms??Date.now()-started,detail:{owner,protocol:selected.protocol,model:selected.model,profile:selected.name||undefined,
    turns:messages.length,promptChars:String(prompt).length,prompt:String(prompt),historyChars:messages.reduce((n,item)=>n+String(item.content||'').length,0),...extra.detail}});
   try{
    const result=await request('/generate',{config_id:selected.id,revision:selected.revision,messages,max_tokens:options.maxOutputTokens,temperature:options.temperature},signal);
    signal?.throwIfAborted();
    thread.messages=[...messages,{role:'assistant',content:result.text}];
    onUpdate?.(result.text);
    const performance=result.performance;
    const tps=performance?.generatedEndToEndTps??performance?.answerEndToEndTps;
    options.onPerformance?.(performance,result.request_id);
    log('ok','模型 API 对话 · '+who+' · '+(result.model||selected.model),{ms:result.ms,detail:{requestId:result.request_id,answerChars:String(result.text||'').length,answer:String(result.text||''),performance,tps}});
    onDiagnostic?.({kind:'model',stage:'model_response',status:'success',protocol:result.protocol,model:result.model,ms:result.ms,tps,requestId:result.request_id,performance});
    return result.text;
   }catch(error){
    const stopped=error.name==='AbortError';
    error.retryRecipe=false;
    onDiagnostic?.({kind:'model',stage:'model_response',status:stopped?'cancelled':'error',protocol:selected.protocol,model:selected.model,ms:Date.now()-started,error:stopped?undefined:String(error.message||error),httpStatus:error.status,diagnostic:error.modelDiagnostic});
    log(stopped?'ok':'error','模型 API 对话 · '+who+' · '+selected.model+(stopped?' · 已停止':' · 失败'),{detail:{error:stopped?undefined:String(error.message||error),httpStatus:error.status||undefined,diagnostic:error.modelDiagnostic}});
    clear();throw error;
   }
  };
  try{signal?.throwIfAborted();return await fn({ask,reset:async()=>clear(),isNew,transport:'model',profile:selected});}
  finally{busy--;if(signal?.aborted)clear();}
 };
 const next=lane.then(run,run);lane=next.catch(()=>{});return next;
}
window.AiOpsModels={request,refresh,conversation,reset,state:()=>snapshot,busy:()=>busy>0,ready:()=>snapshot?.mode==='model'&&snapshot.items.some(x=>x.id===snapshot.config_id&&!x.locked)};
refresh().catch(()=>{});
})();
