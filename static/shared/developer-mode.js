/* Developer workspace inside the monthly report; no navigation to /dev. */
(function(){
  'use strict';
  const trigger=document.getElementById('airDeveloperOpen');
  if(!trigger) return;
  const dialog=document.createElement('dialog');
  dialog.className='air-developer';
  dialog.id='airDeveloper';
  dialog.setAttribute('aria-labelledby','airDeveloperTitle');
  dialog.innerHTML='<header class="air-developer-head"><div><strong id="airDeveloperTitle">开发者模式</strong><span>数据链路 · 源表直查 · 接口调试</span></div><button type="button" class="air-developer-close" aria-label="关闭开发者模式">关闭 <span aria-hidden="true">×</span></button></header><div class="air-developer-status" role="status"><span></span><button type="button" hidden>重试</button></div><iframe title="AiOps 开发者工作台" hidden></iframe>';
  document.body.appendChild(dialog);
  const frame=dialog.querySelector('iframe'), status=dialog.querySelector('[role=status]');
  const retry=status.querySelector('button');
  let loaded=false, loading=false;
  function fit(){
    if(!dialog.open) return;
    const v=window.visualViewport;
    const width=v?v.width:window.innerWidth, height=v?v.height:window.innerHeight;
    const gap=Math.min(width<=600?6:12,width/8,height/8);
    Object.assign(dialog.style,{inset:'auto',margin:'0',left:((v?v.offsetLeft:0)+gap)+'px',top:((v?v.offsetTop:0)+gap)+'px',width:Math.max(1,width-gap*2)+'px',height:Math.max(1,height-gap*2)+'px'});
  }
  window.addEventListener('resize',fit);
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize',fit);
    window.visualViewport.addEventListener('scroll',fit);
  }
  function close(){ dialog.close(); }
  dialog.querySelector('.air-developer-close').onclick=close;
  dialog.addEventListener('close',()=>{
    trigger.setAttribute('aria-expanded','false');
  });

  function embeddedDocument(source){
    const doc=new DOMParser().parseFromString(source,'text/html');
    if(!doc.getElementById('apiBase') || !doc.getElementById('menuSearch')) throw new Error('服务器未返回开发者工作台，请确认已安装完整的新版本应用包');
    // The embedded workspace uses the report's application prefix, including a hosted access token.
    const base=doc.createElement('base');
    base.href=new URL('./',document.baseURI).href;
    doc.querySelectorAll('base').forEach(node=>node.remove());
    doc.head.prepend(base);
    // Use the one assistant in the parent report rather than starting another ADC session in srcdoc.
    doc.querySelectorAll('script').forEach(script=>{
      if(script.textContent.includes('ADCChat v1.4 一体版 F12 脚本')
          || script.textContent.includes('window.DC_SITE=')
          || /(?:shared\/dragon-claw\.js|\/__platform\/adc\/client\.js)(?:\?|$)/.test(script.getAttribute('src')||'')) script.remove();
    });
    doc.querySelectorAll('#aiBar,#aiBarRz,#aiBarFab').forEach(node=>node.remove());
    const bootstrap=doc.createElement('script');
    bootstrap.textContent=`(()=>{
      const notify=action=>parent.postMessage({type:'aiops-developer',action},'*');
      window.__openAiBar=()=>notify('assistant');
      document.addEventListener('click',event=>{
        if(event.target.closest('a.topbar-ai[href="./"]')){event.preventDefault();notify('close');}
      });
      document.addEventListener('keydown',event=>{
        if(event.key==='Escape'&&!event.defaultPrevented&&!document.querySelector('.dlg-mask:not([hidden])')){event.preventDefault();notify('close');}
      });
    })();`;
    base.after(bootstrap);
    return '<!doctype html>\n'+doc.documentElement.outerHTML;
  }

  async function load(){
    if(loaded || loading) return;
    loading=true; status.hidden=false; retry.hidden=true;
    status.querySelector('span').textContent='正在加载开发者工作台…';
    try{
      const response=await fetch(new URL('static/dev.html',document.baseURI),{cache:'no-store'});
      if(!response.ok) throw new Error('加载失败（HTTP '+response.status+'）');
      const html=embeddedDocument(await response.text());
      if(!dialog.open){ loading=false; return; }
      frame.hidden=false;
      // Give the developer sidebar its real viewport during initialization.
      frame.getBoundingClientRect();
      frame.addEventListener('load',()=>{
        loaded=true; loading=false; status.hidden=true; frame.hidden=false;
      },{once:true});
      frame.srcdoc=html;
    }catch(error){
      loading=false; status.querySelector('span').textContent=error.message||'开发者工作台加载失败'; retry.hidden=false;
    }
  }
  retry.onclick=load;
  trigger.onclick=()=>{
    if(!dialog.open) dialog.showModal();
    fit();
    trigger.setAttribute('aria-expanded','true');
    load();
  };
  window.addEventListener('message',event=>{
    if(event.source!==frame.contentWindow || !dialog.open || event.data?.type!=='aiops-developer') return;
    if(event.data.action==='close') close();
    if(event.data.action==='assistant'){
      close(); window.DragonClaw?.open();
    }
  });
})();
