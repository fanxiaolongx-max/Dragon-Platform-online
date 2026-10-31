/* Cancellation owns a generation, not merely a spinner. Aborted generations never become active again. */
(function(){
 const active=new Map();let global=new AbortController(),epoch=0;
 const error=()=>new DOMException('已停止生成','AbortError');
 const check=signal=>{if(signal?.aborted)throw error();};
 function wait(promise,signal){
  check(signal);if(!signal)return promise;
  return new Promise((resolve,reject)=>{
   const abort=()=>{cleanup();reject(error());},cleanup=()=>signal.removeEventListener('abort',abort);
   signal.addEventListener('abort',abort,{once:true});
   Promise.resolve(promise).then(value=>{cleanup();if(signal.aborted)reject(error());else resolve(value);},e=>{cleanup();reject(e);});
  });
 }
 function begin(id){active.get(id)?.abort();if(global.signal.aborted)global=new AbortController();const token=new AbortController();active.set(id,token);return token;}
 window.AiReportTasks={begin,signal:id=>active.get(id)?.signal||global.signal,check,wait,isAbort:e=>e?.name==='AbortError',current:(id,token)=>active.get(id)===token,
  stop(){epoch++;global.abort();for(const token of active.values())token.abort();},get epoch(){return epoch;}};
})();
