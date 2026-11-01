/* One server-side profile controls the report, tools, assistant and developer workspace together. */
(function(){
 'use strict';
 const base=document.getElementById('apiBase');if(!base)return;
 const field=base.closest('.basefield');base.readOnly=true;
 base.closest('.topbar')?.classList.add('has-data-environment');
 const style=document.createElement('style');
 style.textContent=`
 .topbar.has-data-environment .basefield{flex:0 1 360px;min-width:140px}
 .topbar .data-environment-select{flex:0 0 auto;max-width:168px;min-height:34px;padding:6px 10px;border:1px solid #64748b;border-radius:6px;background:#17263d;color:#f8fafc;color-scheme:dark;font:500 12px/1.5 var(--font,sans-serif);cursor:pointer}
 .topbar .data-environment-select option{background:#17263d;color:#f8fafc}
 .topbar .data-environment-select:hover:not(:disabled){background:#223750;border-color:#5eead4}
 .topbar .data-environment-select:focus-visible{outline:2px solid #5eead4;outline-offset:2px}
 .topbar .data-environment-select:disabled{background:#1e293b;color:#cbd5e1;opacity:1;cursor:default;-webkit-text-fill-color:#cbd5e1}
 .topbar .data-environment-status{font-size:11px;color:#cbd5e1;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 @media(max-width:1440px){.topbar .data-environment-status{display:none}}
 @media(max-width:768px){.topbar.has-data-environment{flex-wrap:wrap;height:auto;min-height:62px;padding:10px 12px}.topbar.has-data-environment .topbar-spacer{display:none}}
 @media(forced-colors:active){.topbar .data-environment-select{background:Canvas;color:CanvasText;border-color:ButtonText}.topbar .data-environment-select:disabled{color:GrayText;-webkit-text-fill-color:GrayText}.topbar .data-environment-select option{background:Canvas;color:CanvasText}}`;
 document.head.appendChild(style);
 const select=document.createElement('select');select.className='data-environment-select';select.setAttribute('aria-label','数据环境');
 select.innerHTML='<option value="local">本地模拟基座</option><option value="remote">远端数字人基座</option>';
 field.after(select);
 base.style.width='180px';
 const status=document.createElement('span');status.className='data-environment-status';status.setAttribute('role','status');select.after(status);
 const api=()=>base.value.replace(/\/+$/,'')+'/environment';
 let mode;
 async function load(){
  select.disabled=true;
  try{const r=await fetch(api(),{cache:'no-store'}),b=await r.json();if(b.code!==0)throw Error(b.message||'状态读取失败');
   mode=b.data.mode;select.value=mode;select.disabled=!b.data.switchable;
   status.textContent=b.data.switchable?'应用库与业务库统一使用所选环境':'真实基座部署：环境已锁定';
  }catch(e){status.textContent=e.message;select.disabled=true;}
 }
 select.onchange=async()=>{
  const next=select.value;select.value=mode;let dirty=false;
  if(window.parent!==window){
   const allowed=await new Promise(resolve=>{const id=String(Math.random());const fn=e=>{if(e.source===parent&&e.data?.type==='aiops-environment-preflight-result'&&e.data.id===id){removeEventListener('message',fn);dirty=e.data.dirty;resolve(e.data.allowed);}};addEventListener('message',fn);parent.postMessage({type:'aiops-environment-preflight',id},'*');setTimeout(()=>{removeEventListener('message',fn);resolve(false);},30000);});
   if(!allowed){status.textContent='请等待当前保存或生成结束后再切换';return;}
  }
  if(!confirm((dirty?'当前月报有未保存修改，继续切换会丢弃这些修改。\n':'')+'切换后应用库和业务库都将使用所选环境。两个环境的数据相互独立，不自动迁移。请先保存当前月报。是否继续？'))return;
  select.disabled=true;status.textContent='正在验证两个数据库并切换…';
  try{const r=await fetch(api(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:next})}),b=await r.json();if(b.code!==0)throw Error(b.message||'切换失败');mode=b.data.mode;select.value=mode;status.textContent='已切换，正在刷新对应环境…';if(parent!==window)parent.postMessage({type:'aiops-environment-switched'},'*');else location.reload();
  }catch(e){status.textContent=e.message;select.value=mode;}finally{select.disabled=false;}
 };
 load();
})();
