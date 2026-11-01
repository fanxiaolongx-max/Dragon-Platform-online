/* One server-side profile controls the report, tools, assistant and developer workspace together. */
(function(){
 'use strict';
 const base=document.getElementById('apiBase');if(!base)return;
 const field=base.closest('.basefield');base.readOnly=true;
 base.closest('.topbar')?.classList.add('has-data-environment');
 const style=document.createElement('style');
 style.textContent=`
 .topbar.has-data-environment .basefield{flex:0 1 360px;min-width:140px}
 .topbar .data-environment-select{
   flex:0 0 auto;
   max-width:172px;
   min-height:34px;
   height:34px;
   padding:0 28px 0 10px;
   border:1px solid #64748b;
   border-radius:6px;
   background:#17263d url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23cbd5e1' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 10px center;
   color:#f8fafc;
   color-scheme:dark;
   -webkit-appearance:none;
   appearance:none;
   font:500 12px/34px var(--font,sans-serif);
   cursor:pointer;
   outline:none;
   transition:all 0.15s ease;
 }
 .topbar .data-environment-select option{
   background:#0f172a;
   color:#f8fafc;
   padding:6px 10px;
 }
 .topbar .data-environment-select:hover:not(:disabled){
   background-color:#223750;
   border-color:#5eead4;
 }
 .topbar .data-environment-select:focus-visible{
   outline:2px solid #5eead4;
   outline-offset:2px;
 }
 /* 禁用状态：灰色背景、清晰深色字体，彻底解决暗色顶栏下白底或浅色文字看不清的问题 */
 .topbar .data-environment-select:disabled{
   background-color:#cbd5e1 !important;
   color:#0f172a !important;
   -webkit-text-fill-color:#0f172a !important;
   border:1px solid #94a3b8 !important;
   opacity:1 !important;
   font-weight:600 !important;
   cursor:not-allowed !important;
   background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%230f172a' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") !important;
   background-repeat:no-repeat !important;
   background-position:right 10px center !important;
 }
 /* 真实基座部署锁定徽章：与禁用按钮风格统一，深色字+灰色背景 */
 .topbar .data-environment-lock{
   flex:0 0 auto;
   display:inline-flex;
   align-items:center;
   gap:6px;
   min-height:34px;
   height:34px;
   padding:0 12px;
   border:1px solid #94a3b8 !important;
   border-radius:6px;
   background-color:#cbd5e1 !important;
   color:#0f172a !important;
   font:600 12px/1 var(--font,sans-serif) !important;
   white-space:nowrap;
   cursor:default;
 }
 .topbar .data-environment-lock svg{
   flex:none;
   color:#0f172a !important;
 }
 .topbar .data-environment-lock[hidden],.topbar .data-environment-select[hidden]{display:none !important}
 .topbar .data-environment-status{
   font-size:11.5px;
   color:#cbd5e1;
   max-width:240px;
   overflow:hidden;
   text-overflow:ellipsis;
   white-space:nowrap;
   display:inline-flex;
   align-items:center;
   gap:4px;
   transition:color 0.15s ease;
 }
 .topbar .data-environment-status.is-warning{
   color:#fde047;
   cursor:pointer;
   text-decoration:underline dotted;
 }
 .topbar .data-environment-status.is-warning:hover{
   color:#fef08a;
 }
 @media(max-width:1440px){.topbar .data-environment-status{max-width:180px}}
 @media(max-width:1200px){.topbar .data-environment-status{display:none}}
 @media(max-width:768px){.topbar.has-data-environment{flex-wrap:wrap;height:auto;min-height:62px;padding:10px 12px}.topbar.has-data-environment .topbar-spacer{display:none}}
 @media(forced-colors:active){.topbar .data-environment-select{background:Canvas;color:CanvasText;border-color:ButtonText}.topbar .data-environment-select:disabled{color:GrayText;-webkit-text-fill-color:GrayText}.topbar .data-environment-select option{background:Canvas;color:CanvasText}}`;
 document.head.appendChild(style);
 const select=document.createElement('select');select.className='data-environment-select';select.setAttribute('aria-label','数据环境');
 select.innerHTML='<option value="local">本地模拟基座</option><option value="remote">远端数字人基座</option>';
 field.after(select);
 const lock=document.createElement('span');lock.className='data-environment-lock';lock.hidden=true;lock.setAttribute('role','status');
 select.after(lock);
 base.style.width='180px';
 const status=document.createElement('span');status.className='data-environment-status';status.setAttribute('role','status');lock.after(status);
 const api=()=>base.value.replace(/\/+$/,'')+'/environment';
 let mode='local',remoteReady=false,remoteReason='';
 function showNotice(title,message){
  if(typeof window.dlgAlert==='function')window.dlgAlert({title,message});
  else if(window.parent&&typeof window.parent.dlgAlert==='function')window.parent.dlgAlert({title,message});
  else alert(title+'\n\n'+message);
 }
 status.onclick=()=>{
  if(!remoteReady&&status.classList.contains('is-warning')){
   showNotice('未对接数字人基座',remoteReason||'当前系统尚未对接或启用数字人基座。\n\n如需使用“远端数字人基座”，请由管理员在平台「全局设置 › 频道对接 › 数字人」中完成配置并启用。');
  }
 };
 async function load(){
  select.disabled=true;
  try{
   const r=await fetch(api(),{cache:'no-store'}),b=await r.json();if(b.code!==0)throw Error(b.message||'状态读取失败');
   mode=b.data.mode||'local';remoteReady=Boolean(b.data.remoteReady);remoteReason=b.data.remoteReason||'';
   select.value=mode;select.disabled=!b.data.switchable;
   select.hidden=!b.data.switchable;lock.hidden=b.data.switchable;
   if(!b.data.switchable){
    lock.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
    lock.append(document.createTextNode((select.selectedOptions[0]?.textContent||'远端数字人基座')+' · 已锁定'));
    lock.title='真实基座部署：应用库与业务库由基座分配，不能在页面切换';
    status.textContent='真实基座部署：环境已由基座锁定';
    status.title='';status.classList.remove('is-warning');
    return;
   }
   const remoteOpt=select.querySelector('option[value="remote"]');
   if(!remoteReady){
    if(remoteOpt)remoteOpt.textContent='远端数字人基座（未对接）';
    status.textContent='未对接数字人基座';
    status.title='未对接数字人基座：请在全局设置完成数字人对接，点击查看详情';
    status.classList.add('is-warning');
   }else{
    if(remoteOpt)remoteOpt.textContent='远端数字人基座';
    status.textContent='应用库与业务库统一使用所选环境';
    status.title='';status.classList.remove('is-warning');
   }
  }catch(e){
   status.textContent='未对接数字人基座';
   status.title=e.message||'环境接口无法连通';
   status.classList.add('is-warning');
   remoteReason=e.message||'';
   select.disabled=true;
  }
 }
 select.onchange=async()=>{
  const next=select.value;select.value=mode;let dirty=false;
  if(next==='remote'&&!remoteReady){
   showNotice('未对接数字人基座',remoteReason||'当前系统尚未对接或启用数字人基座。\n\n如需使用“远端数字人基座”，请先由管理员在「全局设置 › 频道对接 › 数字人」中完成配置并启用。');
   return;
  }
  if(window.parent!==window){
   const allowed=await new Promise(resolve=>{const id=String(Math.random());const fn=e=>{if(e.source===parent&&e.data?.type==='aiops-environment-preflight-result'&&e.data.id===id){removeEventListener('message',fn);dirty=e.data.dirty;resolve(e.data.allowed);}};addEventListener('message',fn);parent.postMessage({type:'aiops-environment-preflight',id},'*');setTimeout(()=>{removeEventListener('message',fn);resolve(false);},30000);});
   if(!allowed){status.textContent='请等待当前保存或生成结束后再切换';return;}
  }
  if(!confirm((dirty?'当前月报有未保存修改，继续切换会丢弃这些修改。\n':'')+'切换后应用库和业务库都将使用所选环境。两个环境的数据相互独立，不自动迁移。请先保存当前月报。是否继续？'))return;
  select.disabled=true;status.textContent='正在验证两个数据库并切换…';
  try{
   const r=await fetch(api(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:next})}),b=await r.json();if(b.code!==0)throw Error(b.message||'切换失败');mode=b.data.mode;select.value=mode;status.textContent='已切换，正在刷新对应环境…';if(parent!==window)parent.postMessage({type:'aiops-environment-switched'},'*');else location.reload();
  }catch(e){
   select.value=mode;const errMsg=e.message||'切换失败';
   showNotice('切换数据环境失败',errMsg);
   status.textContent=errMsg.length>18?errMsg.slice(0,16)+'…':errMsg;
  }finally{select.disabled=false;}
 };
 load();
})();
