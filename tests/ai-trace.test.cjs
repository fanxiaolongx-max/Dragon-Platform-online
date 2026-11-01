const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'../static');
function runtime(){
 const context={console,URL,AbortController,DOMException,setTimeout,clearTimeout,CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},location:{origin:'https://fixture',pathname:'/digital-human/app/index.html'},document:{currentScript:{src:'https://fixture/air/ai-backend.js'}},dispatchEvent(){}};
 context.window=context;
 for(const file of ['shared/ai-diagnostics.js','air/report-model.js','air/ai-backend.js'])vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),context);
 return context;
}
test('diagnostic observers remain bound to their owner, with credentials removed from nested payloads',()=>{
 const c=runtime(),one=[],two=[],D=c.AiOpsDiagnostics;
 const release=D.use(event=>one.push(D.safe(event))),first=D.capture();first('request',{request:{body:{password:'secret-a',sql:"SELECT 'safe'",message:'Cookie: session=hidden\napi_key="secret-b"'},url:'/apps/aiops-report/~host-credential/index.html'}});release();
 const release2=D.use(event=>two.push(D.safe(event)));first('stream_done',{late:true});D.capture()('new_chat');release2();
 assert.equal(one.length,2);assert.equal(two.length,1);assert.doesNotMatch(JSON.stringify(one),/secret-a|secret-b|host-credential|session=hidden/);assert.match(JSON.stringify(one),/SELECT/);
});
test('browser AI dispatcher records full tool/HTTP replies, failed business codes, resolved month SQL, and empty results',async()=>{
 const c=runtime(),events=[],sent=[];let ask=0;
 const full='payload'.repeat(9000);
 c.fetch=async(url,options)=>{const body=JSON.parse(options.body);sent.push(body);return new Response(JSON.stringify(body.args.sql.includes('broken')?{code:500,message:'column missing password=hidden'}:{code:0,data:{result:{rows:[],detail:full}}}),{status:200,headers:{'x-request-id':'tool-request'}});};
 c.DragonClaw={ready:()=>true,conversation:async(_owner,_fresh,fn,options)=>{options.onState?.('queued');options.onDiagnostic?.({stage:'new_chat',status:'success'});try{return await fn({reset:async()=>{},ask:async()=>++ask===1?JSON.stringify({tool:'query',args:{source:'netcare',sql:"SELECT '{{month}}' AS period"}}):ask===2?JSON.stringify({tool:'query',args:{sql:'SELECT broken'}}):JSON.stringify({type:'answer',text:'已检查'})});}finally{options.onDiagnostic?.({stage:'lane_released'});}}};
 const result=await c.API.post('/api/ai-report/cell/chat',{month:'2026-10',message:'查数据',_debug:true},{onEvent:e=>events.push(e)});
 assert.equal(result.type,'answer');assert.equal(sent[0].args.sql,"SELECT '2026-10' AS period");
 const tools=result._trace.filter(s=>s.kind==='tool'),http=result._trace.filter(s=>s.kind==='http');
 assert.equal(tools.length,2);assert.equal(tools[0].status,'success');assert.equal(tools[0].result.rows.length,0);assert.equal(tools[0].result.detail,full);assert.equal(tools[0].modelTruncated,true);
 assert.equal(tools[1].status,'error');assert.equal(http[1].httpStatus,200);assert.equal(http[1].businessCode,500);assert.equal(http[1].requestId,'tool-request');assert.equal(http[0].response.data.result.detail,full);
 assert.equal(result._trace.at(-1).stage,'lane_released');assert.ok(events.some(e=>e.type==='progress'&&e.stage==='new_chat'));assert.doesNotMatch(JSON.stringify(result._trace),/password=hidden/);
});
test('logging off keeps live stages without payload logs; HTTP errors and cancellation keep their actual status',async()=>{
 const c=runtime(),events=[];
 const recipe={sources:[{id:'s1',kind:'sql',source:'netcare',sql:'SELECT 1'}],compute:'function compute(input){return {};}',render:'function render(result,kit){return "";}'};
 c.fetch=async()=>new Response('<html>upstream unavailable</html>',{status:503});
 await assert.rejects(c.API.post('/api/ai-report/run-data',{month:'2026-10',recipe,_debug:true},{onEvent:e=>events.push(e)}),error=>error.status===503&&error.body._trace.some(s=>s.httpStatus===503&&s.response.includes('upstream unavailable')));
 c.fetch=async()=>new Response(JSON.stringify({code:0,data:{input:{s1:{rows:[]}},missing:[]}}));
 const reply=await c.API.post('/api/ai-report/run-data',{month:'2026-10',recipe},{onEvent:e=>events.push(e)});
 assert.equal('_trace' in reply,false);assert.ok(events.some(e=>e.type==='progress'));
 const abort=new AbortController();abort.abort();await assert.rejects(c.API.post('/api/ai-report/run-data',{month:'2026-10',recipe},{signal:abort.signal}),{name:'AbortError'});
});

test('stream event limit never drops subsequent HTTP or monthly-report tool calls',async()=>{
 const c=runtime();let round=0;
 c.fetch=async()=>new Response(JSON.stringify({code:0,data:{result:{rows:[],total:0}}}));
 c.DragonClaw={ready:()=>true,conversation:async(_owner,_fresh,fn,options)=>{
  for(let n=0;n<2003;n++)options.onDiagnostic({stage:'stream_event',event:{type:'fixture',sequence:n}});
  return fn({reset:async()=>{},ask:async()=>++round===1?JSON.stringify({tool:'list_tables',args:{}}):JSON.stringify({type:'answer',text:'完成'})});
 }};
 const result=await c.API.post('/api/ai-report/cell/chat',{month:'2026-10',message:'查表',_debug:true});
 assert.equal(result._trace.filter(s=>s.event).length,2000);
 assert(result._trace.some(s=>s.kind==='http'&&s.status==='success'));
 assert(result._trace.some(s=>s.kind==='tool'&&s.status==='success'));
 assert.equal(result._trace.at(-1).omittedEvents,3);
});

test('AiOps cell prompt, compiler and narrative enforce text-only requests and retry stale output',async()=>{
 const c=runtime(),queue=[];c.fetch=async()=>new Response(JSON.stringify({code:0,data:{input:{},missing:[]}}));
 c.DragonClaw={ready:()=>true,conversation:async(_o,_f,fn)=>fn({reset:async()=>{},ask:async()=>JSON.stringify(queue.shift())})};
 queue.push({prompt:'指标卡展示：显示存量。'},{prompt:'从业务库读取存量，按报告月份计算，仅显示一句话。'});
 const promptReply=await c.API.post('/api/ai-report/cell/prompt',{month:'2026-10',prompt:'指标卡展示：显示存量。',chat:[{role:'user',text:'不需要图表，只呈现一句话'}],_debug:true});
 assert.match(promptReply.prompt,/【展示约束】/);assert(promptReply._trace.some(s=>s.kind==='retry'));
 const recipe={sources:[{id:'s1',kind:'sql',source:'netcare',sql:'SELECT total FROM fixture'}],compute:'function compute(input){return {total:input.s1.rows[0].total};}',render:'function render(result,kit){return kit.kpi([{value:result.total}]);}'};
 queue.push({type:'recipe',recipe});const compiled=await c.API.post('/api/ai-report/cell/compile',{month:'2026-10',prompt:promptReply.prompt});
 assert.equal(compiled.recipe.compute,recipe.compute);assert.match(compiled.recipe.render,/return ""/);assert(compiled.recipe.narrative);
 queue.push({zh:'存量 894 个。待消减为零。',en:'Total is 894. Pending is zero.'},{zh:'存量 894 个，待消减为零。',en:'Total is 894, with zero pending.'});
 const result=await c.API.post('/api/ai-report/cell/narrative',{month:'2026-10',prompt:promptReply.prompt,recipe:compiled.recipe,result:{total:894},_debug:true});
 assert.equal(result.zh,'存量 894 个，待消减为零。');assert(result._trace.some(s=>s.kind==='retry'));assert.equal(queue.length,0);
});
