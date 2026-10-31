const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const snapshot=require('../static/air/default-template.json');
const defaults=require('../static/air/default-template.js');
const model=require('../static/air/report-model.js');
const {AiReportKit:kit}=require('../static/air/render-kit.js');
const titles=['','新章节','网络变更','SR与事件','风险治理','License管理','EOS退网收编','第三方软件','内控与稽查','网络安全例会'];
test('curated template retains platform layout, header, styles and every available cell prompt',()=>{
 const doc=model.normalize(defaults.create(snapshot,'2026-09'));
 assert.equal(doc.id,'');assert.equal(doc.updatedAt,'');
 assert.equal(doc.name,'护网与网络安全月报');
 assert.equal(doc.template.title.zh,'埃及代表处交付与服务维护月报');
 assert.deepEqual(doc.chapters.map(c=>c.title.zh),titles);
 assert.deepEqual(doc.chapters.map(c=>c.cells.length),[1,1,4,0,6,1,2,1,1,1]);
 assert.equal(doc.template.meta.length,7);
 assert.equal(doc.template.logo,'air/default-logo.png');
 assert.deepEqual(doc.style.theme,snapshot.style.theme);
 const cells=doc.chapters.flatMap(c=>c.cells);
 assert.equal(cells.filter(c=>c.prompt).length,14);
 assert(cells.every(c=>c.output===null));
 assert(cells.filter(c=>c.recipe).every(c=>c.recipe.sources.every(s=>s.kind==='report'&&s.include==='outline')));
 for(const [i,c] of cells.entries())assert.equal(c.prompt,snapshot.chapters.flatMap(ch=>ch.cells)[i].prompt);
});
test('new reports calculate dates through year boundaries and never mutate the snapshot or each other',()=>{
 const original=JSON.stringify(snapshot);
 for(const [month,period,data] of [['2026-09','202610','202609'],['2026-12','202701','202612']]){
  const doc=defaults.create(snapshot,month);
  assert.equal(doc.template.meta.find(f=>f.label.zh==='报告时间').value.zh,period);
  assert.equal(doc.template.meta.find(f=>f.label.zh==='数据月份').value.zh,data);
  doc.chapters[0].cells[0].prompt='changed';doc.template.title.zh='changed';
 }
 assert.equal(JSON.stringify(snapshot),original);
 assert.throws(()=>defaults.create(snapshot,'2026-13'),/month/);
});
test('portable navigation uses current chapter names and anchors, without SQL or generated business data',()=>{
 const doc=model.normalize(defaults.create(snapshot,'2026-12'));
 const nav=doc.chapters.flatMap(c=>c.cells).find(c=>c.recipe);
 const chapters=doc.chapters.filter(c=>c.heading!==false&&c.numbered!==false).reverse().map((c,i)=>({id:c.id,no:String(i+1).padStart(2,'0'),numbered:true,title:i===0?'改名后的章节':c.title.zh,anchor:'#air-chapter-'+c.id,cells:[]}));
 const source=nav.recipe.sources[0];
 const result=vm.runInNewContext(nav.recipe.compute+';compute(input)',{input:{[source.id]:{chapters},$month:'2026-12'}});
 const html=vm.runInNewContext(nav.recipe.render+';render(result,kit)',{result,kit});
 assert.match(html,/改名后的章节/);
 for(const chapter of chapters)assert(html.includes(chapter.anchor));
 assert.equal((html.match(/class="kit-nav-item"/g)||[]).length,8);
});
