/* Diagnostics belong to the acquired ADC lane, never to another queued cell. No credentials are collected. */
(function(){
'use strict';
let sink=null;
function safe(value){
  if(Array.isArray(value))return value.map(safe);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,/(?:password|passwd|secret|token|cookie|authorization|api[_-]?key|private[_-]?key|signature)/i.test(key)?'[REDACTED]':safe(item)]));
  if(typeof value!=='string')return value;
  if(/^\s*[\[{]/.test(value)){try{return JSON.stringify(safe(JSON.parse(value)),null,2);}catch(_){}}
  return value.replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/gi,'[REDACTED]')
    .replace(/\b(?:Bearer|Basic)\s+[^\s,;"'<>]+/gi,'[REDACTED]')
    .replace(/((?:["']?)\b(?:[\w-]{0,80}(?:token|password|passwd|secret|cookie|authorization|api[_-]?key|private[_-]?key|signature))["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]<>]+)/gi,'$1[REDACTED]')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi,'$1[REDACTED]@')
    .replace(/((?:\/apps\/[^/\s]+|\/tools\/[^/\s]+)\/)~[^/\s?#"']+/g,'$1~[REDACTED]')
    .replace(/\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,})\b/g,'[REDACTED]');
}
function capture(){const target=sink;return (stage,detail={})=>{try{target?.({at:new Date().toISOString(),kind:'adc',stage,...detail});}catch(_){/* Diagnostics never change request behavior. */}};}
function use(next){const previous=sink;sink=next;return ()=>{if(sink===next)sink=previous;};}
const names={queued:['等待 ADC 通道','Waiting for ADC lane'],lane_acquired:['已取得 ADC 通道','ADC lane acquired'],lane_released:['已释放 ADC 通道','ADC lane released'],frame_load:['加载隐藏 AI 页面','Loading hidden AI page'],frame_ready:['隐藏页面输入框已就绪','Hidden composer ready'],frame_wait:['等待隐藏页面输入框','Waiting for hidden composer'],frame_stealth:['隐身展开 AI 页面','Preparing hidden AI page'],frame_restore:['恢复页面状态','Restoring page state'],composer_muted:['暂时排除外层输入框','Excluding outer composers'],new_chat:['在 AI 页面新建对话','Starting a chat in AI page'],new_chat_fallback:['沿用会话并声明独立任务','Reusing session with task boundary'],session_init:['初始化 AI 会话','Initializing AI session'],session_capture:['捕获本轮会话配置','Capturing session configuration'],capture_hook:['监听 AI 页面请求','Observing AI page requests'],capture_restore:['恢复页面请求监听','Restoring fetch hooks'],composer_found:['已定位 AI 输入框','AI composer found'],composer_fill:['填写实际任务内容','Filling the task prompt'],composer_submit:['触发原页面发送','Submitting through AI page'],request:['等待 AI 页面响应','Waiting for AI page response'],response:['AI 页面已返回响应','AI page response received'],stream_start:['读取 AI 响应流','Reading AI response stream'],stream_event:['接收 AI 响应事件','Receiving AI stream events'],stream_reasoning:['AI 正在处理任务','AI is processing the task'],stream_tool:['内嵌 AI 正在调用工具','Embedded AI is using a tool'],stream_child:['收到 AI 子会话事件','Receiving AI child-session events'],stream_text:['接收 AI 回答正文','Receiving answer text'],stream_done:['AI 响应流已完成','AI stream completed'],stream_incomplete:['AI 响应流提前结束','AI stream ended early'],fallback:['从 AI 工具结果提取正文','Extracting answer from AI tool result'],csrf_read:['检查当前登录凭据状态','Checking authentication readiness'],csrf_ready:['登录凭据检查完成','Authentication readiness checked'],stopped:['已停止读取','Reading stopped'],failed:['调用失败','Call failed'],model:['等待 AI 页面回复','Waiting for AI page reply'],model_done:['解析 AI 返回内容','Parsing AI reply'],tool:['执行月报数据工具','Running report data tool'],tool_done:['月报数据工具已返回','Report data tool returned'],retry:['修正格式并重试','Correcting format and retrying'],http_start:['请求应用数据接口','Requesting application data'],http_done:['应用接口已返回','Application API returned'],sql_validate:['校验配方 SQL','Validating recipe SQL'],sandbox:['计算并渲染格子','Computing and rendering cell']};
function label(stage,en=false){return names[stage]?.[en?1:0]||stage;}
window.AiOpsDiagnostics={safe,use,capture,label};
})();
