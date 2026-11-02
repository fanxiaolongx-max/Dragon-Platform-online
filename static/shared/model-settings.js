(function(){
'use strict';
let host=null,previous=null,controller=null,working=false;
const en=()=>window.AiReportApp?.state?.lang==='en'||document.documentElement.lang==='en',t=(zh,english)=>en()?english:zh;
const labels={openai:'OpenAI / 兼容接口',responses:'OpenAI Responses',anthropic:'Claude / Anthropic',gemini:'Gemini',ollama:'Ollama',custom:'自定义 HTTP JSON'};
let state=null,current=null;
const busy=()=>{let outer=false;try{if(parent!==window)outer=!!parent.DragonClaw?.busy?.();}catch(_){}return outer||!!window.DragonClaw?.busy?.()||window.AiOpsModels.busy();};
function field(name){return host.querySelector('[name="'+name+'"]');}
function status(message,error=false){if(!host)return;const el=host.querySelector('[data-status]');el.textContent=message;el.classList.toggle('error',error);}
function actions(disabled){if(!host)return;working=disabled;host.querySelectorAll('button,input,select,textarea').forEach(el=>{el.disabled=disabled&&!el.matches('[data-close],[data-stop]');});host.querySelector('[data-stop]').hidden=!disabled;}
function option(select,value,label){const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node);}
function edit(item){
 if(!host)return;current=item||null;
 const defaults={name:'',protocol:'openai',base_url:'',model:'',auth_type:'bearer',auth_header:'',timeout:120,max_tokens:8000,temperature:0.2,verify_ssl:true,response_path:'choices.0.message.content'};
 const c={...defaults,...item};
 for(const [key,value] of Object.entries(defaults)){const el=field(key);if(el.type==='checkbox')el.checked=c[key];else el.value=c[key]??value;}
 for(const key of ['api_key','headers','extra_body','body_template']){field(key).value='';field(key).placeholder=item?.['has_'+key]?(key==='api_key'?t('已加密保存，留空保留','Encrypted; leave blank to retain'):t('已保存，留空保留；JSON 填 {} 清空','Saved; leave blank to retain. Use {} to clear JSON.')):key==='api_key'?t('无认证模型可留空','Optional for models without authentication'):t('可选 JSON 对象','Optional JSON object');}
 field('clear_api_key').checked=false;host.querySelector('[data-delete]').hidden=!item;
 host.querySelector('[data-form-title]').textContent=item?t('编辑模型配置','Edit model'):t('新增模型配置','New model');
 status('');toggleCustom();
}
function toggleCustom(){host.querySelector('[data-custom]').hidden=field('protocol').value!=='custom';}
async function load(){state=await window.AiOpsModels.refresh();renderList();}
function renderList(){
 if(!host)return;const list=host.querySelector('[data-list]');list.replaceChildren();
 const adc=document.createElement('button');adc.type='button';adc.textContent=(state.mode==='adc'?'● ':'○ ')+t('使用 ADC 数字人页面','Use ADC page');adc.onclick=()=>choose('adc');list.append(adc);
 for(const item of state.items){const row=document.createElement('div'),button=document.createElement('button'),use=document.createElement('button');row.className='aim-profile';button.type=use.type='button';button.textContent=(state.mode==='model'&&state.config_id===item.id?'● ':'')+item.name;button.disabled=!!item.locked;button.onclick=()=>edit(item);use.textContent=t('使用','Use');use.disabled=!!item.locked;use.onclick=()=>choose('model',item.id);row.append(button,use);list.append(row);}
 const add=document.createElement('button');add.type='button';add.textContent=t('+ 新增模型','+ Add model');add.onclick=()=>edit(null);list.append(add);
}
async function choose(mode,config_id){
 if(working)return;
 if(busy()){status(t('请先停止或等待当前 AI 任务结束，再切换模型','Stop or finish active AI tasks before switching models'),true);return;}
 actions(true);try{await window.AiOpsModels.request('/select',{mode,config_id});await load();status(t('已切换，后续月报和助理请求使用此通道','Selected for subsequent report and assistant requests'));}catch(error){status(error.message,true);}finally{actions(false);}
}
function payload(){
 const out=current?{id:current.id,revision:current.revision}:{};
 for(const key of ['name','protocol','base_url','model','auth_type','auth_header','response_path','api_key'])out[key]=field(key).value;
 for(const key of ['timeout','max_tokens','temperature'])out[key]=Number(field(key).value);
 out.verify_ssl=field('verify_ssl').checked;out.clear_api_key=field('clear_api_key').checked;
 for(const key of ['headers','extra_body','body_template']){const value=field(key).value.trim();if(value){try{out[key]=JSON.parse(value);}catch(_){throw Error(key+t(' 不是有效 JSON',' is not valid JSON'));}}}
 return out;
}
async function perform(kind){
 if(working)return;
 const target=host;
 if((kind==='save'||kind==='use'||kind==='delete')&&busy()){status(t('请先停止或等待当前 AI 任务结束','Stop or finish active AI tasks first'),true);return;}
 let body;try{body=payload();}catch(error){status(error.message,true);return;}
 if(kind==='delete'&&!confirm(t('删除此模型配置？','Delete this model configuration?')))return;
 controller=new AbortController();actions(true);status(kind==='test'?t('正在调用模型测试…','Testing model…'):t('正在保存…','Saving…'));
 try{
  if(kind==='test'){
   const reply=await window.AiOpsModels.request('/test',body,controller.signal);status(t('测试成功','Test succeeded')+' · '+reply.protocol+' · '+reply.ms+' ms\n'+reply.text);
  }else if(kind==='delete'){
   await window.AiOpsModels.request('/profiles/'+current.id,null,controller.signal,'DELETE');edit(null);await load();status(t('已删除','Deleted'));
  }else{
   const saved=await window.AiOpsModels.request('/profiles',body,controller.signal);if(host!==target)return;edit(saved);
   if(kind==='use')await window.AiOpsModels.request('/select',{mode:'model',config_id:saved.id},controller.signal);
   await load();status(kind==='use'?t('已保存并启用','Saved and selected'):t('已加密保存到应用库','Saved encrypted in the application DB'));
  }
 }catch(error){status(error.name==='AbortError'?t('已停止，请刷新配置确认保存状态','Stopped; refresh settings to confirm any pending save'):error.message,true);}
 finally{if(host===target){controller=null;actions(false);}}
}
function close(){controller?.abort();controller=null;working=false;host.remove();host=null;previous?.focus();document.removeEventListener('keydown',key,true);}
function key(event){if(!host)return;if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();}if(event.key==='Tab'){const nodes=[...host.querySelectorAll('button,input,select,textarea')].filter(x=>!x.disabled&&x.getClientRects().length);if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}}
async function show(){
 if(host){host.querySelector('[data-close]').focus();return;}
 working=false;previous=document.activeElement;host=document.createElement('div');host.className='aim-mask';host.innerHTML=`<section class="aim-dialog" role="dialog" aria-modal="true" aria-labelledby="aim-title">
 <header><strong id="aim-title">${t('AI 模型配置','AI model settings')}</strong><button type="button" data-close aria-label="${t('关闭','Close')}">×</button></header>
 <div class="aim-layout"><aside data-list></aside><main><h3 data-form-title></h3><form autocomplete="off">
 <div class="aim-grid"><label>${t('配置名称','Profile name')}<input name="name" maxlength="100" required></label><label>${t('协议','Protocol')}<select name="protocol"></select></label>
 <label class="aim-wide">${t('API 根地址或完整推理 URL（HTTP / HTTPS）','API root or full inference URL (HTTP / HTTPS)')}<input name="base_url" type="url" placeholder="http://127.0.0.1:11434" required></label>
 <label>${t('模型名称','Model ID')}<input name="model" placeholder="model-id"></label><label>${t('认证方式','Authentication')}<select name="auth_type"></select></label>
 <label>${t('API Key（仅输入新值时替换）','API key (enter to replace)')}<input name="api_key" type="password" autocomplete="new-password"></label><label>${t('自定义认证头名称','Custom auth header')}<input name="auth_header" placeholder="X-API-Key"></label>
 <label>${t('超时（秒）','Timeout (seconds)')}<input name="timeout" type="number" min="5" max="600"></label><label>${t('输出 Token 上限','Max output tokens')}<input name="max_tokens" type="number" min="1" max="131072"></label>
 <label>${t('温度','Temperature')}<input name="temperature" type="number" min="0" max="2" step="0.1"></label><div class="aim-check"><label><input name="verify_ssl" type="checkbox">${t('校验 HTTPS 证书','Verify HTTPS certificates')}</label><label><input name="clear_api_key" type="checkbox">${t('清除已保存的 Key','Clear stored API key')}</label></div></div>
 <details><summary>${t('高级参数与自定义协议','Advanced / custom protocol')}</summary><p>${t('附加参数覆盖协议默认字段，可用 null 省略不支持的字段。请求头和高级 JSON 同样加密保存，读取配置时不回显。','Extra parameters override defaults; null omits unsupported fields. Headers and advanced JSON are encrypted and never returned by read APIs.')}</p>
 <label>${t('附加请求头 JSON','Extra headers JSON')}<textarea name="headers" spellcheck="false" placeholder='{"X-Project":"demo"}'></textarea></label>
 <label>${t('附加请求参数 JSON','Extra request parameters JSON')}<textarea name="extra_body" spellcheck="false" placeholder='{"temperature":null,"max_tokens":null,"max_completion_tokens":8000}'></textarea></label>
 <div data-custom><label>${t('POST JSON 请求模板','POST JSON request template')}<textarea name="body_template" rows="5" spellcheck="false" placeholder='{"model":"\u0024{model}","messages":"\u0024{messages}"}'></textarea></label>
 <p>\u0024{messages} / \u0024{prompt} / \u0024{system} / \u0024{model} / \u0024{max_tokens} / \u0024{temperature}</p><label>${t('正文响应路径','Text response path')}<input name="response_path" placeholder="data.answer"></label></div></details>
 <p class="aim-note">${t('月报与 Dragon Claw 共用所选通道，数据工具仍由本应用访问分配的双库。配置完整内容使用 Fernet 认证加密后存入应用库，密钥在服务端单独保存。迁移时请同时备份密钥文件；HTTP 会以明文传输网络请求。','Report and Dragon Claw share the selected channel. Application DB tools stay within this app. Profiles use authenticated Fernet encryption; the master key stays on the server. Back up the key for migrations. HTTP transmits requests without transport encryption.')}</p>
 <div class="aim-actions"><button type="button" data-test>${t('测试模型','Test model')}</button><button type="submit">${t('保存','Save')}</button><button type="button" data-use>${t('保存并使用','Save and use')}</button><button type="button" data-delete>${t('删除','Delete')}</button><button type="button" data-stop hidden>${t('停止','Stop')}</button></div>
 <pre data-status role="status" aria-live="polite"></pre></form></main></div></section>`;
 document.body.append(host);document.addEventListener('keydown',key,true);host.querySelector('[data-close]').onclick=close;
 for(const [value,label] of Object.entries(labels))option(field('protocol'),value,label);
 for(const value of ['bearer','x-api-key','api-key','x-goog-api-key','none','custom'])option(field('auth_type'),value,value);
 field('protocol').onchange=()=>{const p=field('protocol').value;field('auth_type').value=p==='ollama'?'none':p==='anthropic'?'x-api-key':p==='gemini'?'x-goog-api-key':'bearer';toggleCustom();};
 host.querySelector('form').onsubmit=e=>{e.preventDefault();perform('save');};
 for(const name of ['test','use','delete'])host.querySelector('[data-'+name+']').onclick=()=>perform(name);
 host.querySelector('[data-stop]').onclick=()=>controller?.abort();edit(null);host.querySelector('[data-close]').focus();
 try{await load();}catch(error){status(error.message+t('；若提示表不存在，请通过更新包执行 db/upgrade.sql（本地执行 SQLite 对应脚本）。','; if a table is missing, apply the package database upgrade scripts.'),true);}
}
window.AiOpsModelSettings={show};
document.addEventListener('click',event=>{if(event.target.closest('[data-ai-model-settings]'))show();});
})();
