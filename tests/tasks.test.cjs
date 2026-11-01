const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function tasks(){const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/air/tasks.js'),'utf8'),{window,AbortController,DOMException,Promise,Map});return window.AiReportTasks;}
test('stopped waits reject immediately and ignore late success',async()=>{
 const t=tasks(),token=t.begin('one');let resolve;
 const wait=t.wait(new Promise(r=>resolve=r),token.signal);
 t.stop();await assert.rejects(wait,{name:'AbortError'});resolve('late');
 assert.throws(()=>t.check(token.signal),{name:'AbortError'});
});
test('fresh generation never revives aborted cell or batch tokens',()=>{
 const t=tasks(),one=t.begin('one'),epoch=t.epoch;
 t.stop();const next=t.begin('one');
 assert.equal(t.epoch,epoch+1);assert(one.signal.aborted);assert(!next.signal.aborted);
 assert.equal(t.current('one',one),false);assert.equal(t.current('one',next),true);
});

test('superseding a cell also cancels its previous controller',()=>{const t=tasks(),old=t.begin('cell');const current=t.begin('cell');assert(old.signal.aborted);t.stop();assert(current.signal.aborted);});

test('failed sources never reach generated compute or narrative; successful empty queries remain valid',async()=>{
 let payload={input:{s1:null},missing:[{id:'s1',label:'拦截数据',error:'no such column: fixture'}]},computes=0,narratives=0;
 const window={},context={window,API:{post:async()=>payload},AiReportModel:{presentationRecipe:r=>r,normalizeOutput:x=>x},AiReportSandbox:{run:async()=>{computes++;return {result:{total:0},html:'0',widgets:[]};}},AiReportSanitize:{clean:x=>x},AiReportWidgets:{cleanSpecs:x=>x},AiReportTrace:{local:async(_id,_stage,work)=>work(),post:async(_id,_label,path)=>{if(path.endsWith('/run-data'))return payload;narratives++;return {};}}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/air/runner.js'),'utf8'),context);
 const cell={id:'test',recipe:{sources:[{id:'s1',kind:'sql',label:'拦截数据'}],narrative:{prompt:'总结'}}};
 await assert.rejects(window.AiReportRunner.run(cell,'2026-10'),/no such column: fixture/);
 assert.equal(computes,0);assert.equal(narratives,0);assert.match(cell.output.error,/不能将查询失败当作 0/);assert.equal(cell.missing[0].id,'s1');
 payload={input:{s1:null},missing:[]};
 await assert.rejects(window.AiReportRunner.run(cell,'2026-10'),/数据源未返回结果/);
 assert.equal(computes,0);
 payload={input:{s1:{rows:[]}},missing:[]};
 await window.AiReportRunner.run(cell,'2026-10',{withNarrative:false});
 assert.equal(computes,1);assert.equal(narratives,0);assert.equal(cell.output.result.total,0);assert.equal(cell.output.error,'');
});
