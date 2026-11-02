/* 交互日志（AI 月报与开发者页共用）。
   - 给本应用 /api 请求带上来源页面（X-Ops-Page: air / dev），服务端据此给基座请求日志标注页面；
   - OpsLog.report(entry)：浏览器侧的外部交互（ADC 内嵌对话等）批量上报到 POST api/ops/logs；
   - 打开页面时刷新一次业务表清单（POST api/ops/tables/refresh，服务端对比新增 / 减少并写日志），
     结果放在 OpsLog.tables（Promise），并派发 ops:tables 事件，源表直查下拉据此排序和打失败标签。 */
(function(){
  'use strict';
  if(window.OpsLog) return;
  const page=document.currentScript?.dataset.page==='dev'?'dev':'air';
  const api=path=>new URL('api/'+path,document.baseURI).href;
  const ownApi=url=>{try{const u=new URL(url,document.baseURI);return u.origin===location.origin&&/\/api\//.test(u.pathname);}catch(_){return false;}};
  const nativeFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    if((typeof input==='string'||input instanceof URL)&&ownApi(String(input))){
      const headers=new Headers(init&&init.headers||undefined);
      if(!headers.has('X-Ops-Page')) headers.set('X-Ops-Page',page);
      return nativeFetch(input,{...(init||{}),headers});
    }
    return nativeFetch(input,init);
  };

  let queue=[], timer=0;
  const clip=(v,n=4000)=>{const t=typeof v==='string'?v:(()=>{try{return JSON.stringify(v);}catch(_){return String(v);}})();return t.length>n?t.slice(0,n)+'…（共 '+t.length+' 字，已截断）':t;};
  // 不用 sendBeacon：它带不上数据环境版本头，会被服务端拒绝；keepalive 的 fetch 在页面关闭时也能发出
  function flush(){
    clearTimeout(timer); timer=0;
    if(!queue.length) return;
    const body=JSON.stringify({page,entries:queue.splice(0,50)});
    nativeFetch(api('ops/logs'),{method:'POST',headers:{'Content-Type':'application/json','X-Ops-Page':page},body,keepalive:true}).catch(()=>{});
    if(queue.length) timer=setTimeout(flush,1500);
  }
  function report(entry){
    if(!entry||typeof entry!=='object') return;
    const detail={};
    for(const [k,v] of Object.entries(entry.detail||{})) if(v!==undefined&&v!==null&&v!=='') detail[k]=typeof v==='string'?clip(v):v;
    queue.push({kind:entry.kind||'ui',status:entry.status==='error'?'error':'ok',title:clip(entry.title||'前端事件',300),ms:entry.ms,page,detail});
    if(queue.length>=20) flush(); else if(!timer) timer=setTimeout(flush,1500);
  }
  addEventListener('pagehide',()=>flush());

  let tables=null;
  function refreshTables(force){
    tables=nativeFetch(api('ops/tables/refresh'),{method:'POST',headers:{'Content-Type':'application/json','X-Ops-Page':page},body:JSON.stringify({page,force:!!force})})
      .then(r=>r.json()).then(j=>{if(j.code!==0) throw new Error(j.message||'刷新业务表清单失败');return j.data;})
      .catch(()=>nativeFetch(api('ops/tables')).then(r=>r.json()).then(j=>j.code===0&&j.data?{...(j.data.snapshot||{}),health:j.data.health||{},stale:true}:null).catch(()=>null));
    tables.then(data=>{ if(data) dispatchEvent(new CustomEvent('ops:tables',{detail:data})); });
    return tables;
  }
  // 开发者页嵌在 AI 月报里时（srcdoc），父页面刚刷新过，服务端 60 秒内直接复用，不会重复记日志
  refreshTables(false);
  window.OpsLog={page,report,flush,refreshTables,get tables(){return tables;},api,clip};
})();
