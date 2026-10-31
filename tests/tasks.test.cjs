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
