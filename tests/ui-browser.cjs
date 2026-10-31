// Run with Playwright available on NODE_PATH; all application/ADC responses are local fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const requests = [], errors = [];
const prefix = '/digital-human/dh/fixture-app/';
let executionFailure=null, htmlFallback=false;
const adc = `window.ADCChat={configured:true,busy:false,environment:'Fixture',newSession:async()=> 'fixture',stop(){},ask:async(_q,o)=>o.onUpdate('验证回答。\\n\\n\`\`\`js\\nconst answer = 2;\\n\`\`\`')};`;
const server = http.createServer((req, res) => {
  requests.push(req.url);
  let url = new URL(req.url, 'http://fixture').pathname;
  const nested = url.startsWith(prefix);
  if (nested) url = '/' + url.slice(prefix.length);
  res.setHeader('Access-Control-Allow-Origin', '*');
  if(url.endsWith('/api/agent/execute') && executionFailure){
    if(executionFailure.network){ req.socket.destroy(); return; }
    res.statusCode=executionFailure.status;
    res.setHeader('x-request-id','fixture-error-123');
    res.setHeader('Content-Type',executionFailure.raw?'text/html':'application/json');
    res.end(executionFailure.raw||JSON.stringify(executionFailure.json)); return;
  }
  if (url.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    let data = [];
    if (url.includes('health')) data = { status: 'healthy' };
    if (url.includes('table-map')) data = { groups: [], tables: [] };
    if (url.includes('capabilities')) data = { tools: [], prompt: 'fixture', sources: [] };
    res.end(JSON.stringify({ code: 0, data })); return;
  }
  if (url === '/__platform/adc/client.js') { res.setHeader('Content-Type', 'text/javascript'); res.end(adc); return; }
  if (url.startsWith('/adc-agent/')) { res.setHeader('Content-Type', 'text/html'); res.end('<textarea></textarea>'); return; }
  // Simulate a base that routes /dev (or all HTML paths when htmlFallback is active) back to the report.
  const file = url === '/' || url === '/dev' || (htmlFallback && url.endsWith('.html')) ? 'static/index.html'
    : url.startsWith('/static/') ? url.slice(1) : 'static' + url;
  const target = path.resolve(root, file);
  if (!target.startsWith(root + path.sep) || !fs.existsSync(target) || fs.statSync(target).isDirectory()) { res.statusCode = 404; res.end(); return; }
  const ext = path.extname(target);
  res.setHeader('Content-Type', { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' }[ext] || 'application/json');
  let content = fs.readFileSync(target);
  if (ext === '.html') {
    content = content.toString().replace(/<script>\s*\/\*\s*\n \* ADCChat v1\.4[\s\S]*?<\/script>/,
      `<script src="${nested ? prefix : '/'}__platform/adc/client.js"></script>`)
      .replace('const onSite = ADC_ORIGINS.includes(location.origin);', 'const onSite = true;');
    if (req.url.includes('sandbox=1')) res.setHeader('Content-Security-Policy', 'sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads');
  }
  res.end(content);
});
let browser;
async function contained(page, selector = '#aiBar') {
  await page.waitForFunction(selector => {
    const r = document.querySelector(selector).getBoundingClientRect(), v = visualViewport;
    return r.width > 0 && r.x >= v.offsetLeft - 1 && r.y >= v.offsetTop - 1 && r.right <= v.offsetLeft + v.width + 1 && r.bottom <= v.offsetTop + v.height + 1;
  }, selector, { timeout: 2000 });
  const box = await page.locator(selector).boundingBox();
  const view = await page.evaluate(() => {
    const v = visualViewport;
    return { x: v.offsetLeft, y: v.offsetTop, width: v.width, height: v.height };
  });
  assert(box, selector + ' visible');
  if(selector === '#aiBar') assert.equal(await page.locator(selector).evaluate(el => el.scrollLeft),0,'Outer panel must not scroll sideways');
  assert(box.x >= view.x - 1 && box.y >= view.y - 1 && box.x + box.width <= view.x + view.width + 1 && box.y + box.height <= view.y + view.height + 1,
    `Bounds ${selector}: ${JSON.stringify({ box, view })}`);
}
async function drag(page, selector, dx, dy, within = { x: 30, y: 20 }) {
  const r = await page.locator(selector).boundingBox();
  const x = r.x + within.x, y = r.y + within.y;
  await page.mouse.move(x, y); await page.mouse.down();
  for (let i = 1; i <= 4; i++) {
    await page.mouse.move(x + dx * i / 4, y + dy * i / 4);
    await contained(page);
  }
  await page.mouse.up();
}
async function workspace(page, origin, pathname, sandbox = false) {
  await page.goto(origin + pathname + (sandbox ? '?sandbox=1' : ''));
  await page.waitForFunction(() => !!window.DragonClaw && !document.body.classList.contains('air-booting'));
  console.log('Workspace:', pathname, sandbox ? 'sandbox' : 'normal');
  if(await page.locator('#aiBar').isVisible()) await page.locator('#aiBarClose').click();
  const url = page.url();
  // Open with a mouse click: opening must leave report DOM and dirty content intact.
  await page.locator('#airReport').evaluate(el => el.dataset.unsavedFixture = 'preserve');
  await page.locator('#airDeveloperOpen').click();
  await page.locator('#airDeveloper iframe:not([hidden])').waitFor();
  console.log('Developer iframe loaded');
  await contained(page, '#airDeveloper');
  if(!sandbox){
    const zoom=await page.context().newCDPSession(page);
    await zoom.send('Emulation.setPageScaleFactor',{pageScaleFactor:1.5});
    await contained(page,'#airDeveloper');
    await zoom.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});
    await contained(page,'#airDeveloper');
    await zoom.detach();
  }
  const frame = page.frameLocator('#airDeveloper iframe');
  await frame.locator('#menuSearch').waitFor();
  await frame.locator('#leftPanel .grp').first().waitFor();
  console.log('Developer endpoints rendered');
  if(process.env.UI_SCREENSHOTS && pathname === '/' && !sandbox) await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS,'developer-modal.png')});
  assert.equal(await frame.locator('#apiBase').inputValue(), pathname + 'api');
  assert.equal(await frame.locator('#aiBar').count(), 0);
  assert.equal(page.url(), url);
  await frame.locator('#menuSearch').fill('health');
  await frame.locator('#menuSearch').press('Escape');
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open);
  assert.equal(await page.locator('#airReport').getAttribute('data-unsaved-fixture'), 'preserve');
  await page.locator('#airDeveloperOpen').click();
  assert.equal(await frame.locator('#menuSearch').inputValue(), 'health');
  // The return control closes the modal rather than navigating the iframe or report.
  await frame.locator('a.topbar-ai[href="./"]').click();
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open);
  await page.locator('#airDeveloperOpen').click();
  await frame.locator('.topbar button.topbar-ai').click();
  await page.waitForFunction(() => !document.querySelector('#airDeveloper').open && !document.querySelector('#aiBar').classList.contains('collapsed'));
  await contained(page);
  assert.equal(await page.locator('#aiBarQ').evaluate(el => el === document.activeElement),true,'Opening the shared assistant should focus its input');
  assert.equal(page.url(), url);
  await page.locator('#aiBarClose').click();
  await page.locator('#airDeveloperOpen').click();
  await page.locator('.air-developer-close').click();
  await page.waitForFunction(() => document.querySelector('#airDeveloperOpen').getAttribute('aria-expanded') === 'false');
  assert.equal(await page.locator('#airDeveloperOpen').evaluate(el => el === document.activeElement), true);
  if (!sandbox) {
    await page.setViewportSize({ width: 390, height: 640 });
    // Toolbar can scroll off at this size; invoke the already-tested button handler.
    await page.locator('#airDeveloperOpen').evaluate(el => el.click());
    await contained(page, '#airDeveloper');
    await page.locator('.air-developer-close').click();
    await page.setViewportSize({ width: 1280, height: 800 });
  }
}
async function assistantFeedback(page){
  await page.evaluate(()=>{
    document.getElementById('aiBarAgent').checked=false;
    window.ADCChat.configured=false;
    window.ADCChat.ask=(_q,options)=>new Promise(resolve=>{
      window.__finishFirst=()=>{window.ADCChat.configured=true;options.onUpdate('首次对话完成');resolve();};
    });
    void window.DragonClaw.send('首次连接测试');
  });
  await page.waitForFunction(()=>!!window.__finishFirst);
  const toggle=page.locator('#aiBarFrameToggle');
  assert.equal(await toggle.getAttribute('aria-disabled'),'true');
  assert.equal(await toggle.evaluate(el=>el.disabled),false,'Waiting control must remain clickable to explain the restriction');
  await toggle.click({force:true});
  assert.match(await page.locator('#aiBarFrameHint').innerText(),/首次对话.*暂不能展开/);
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),false);
  await page.evaluate(()=>window.__finishFirst());
  await page.waitForFunction(()=>document.getElementById('aiBarFrameToggle').getAttribute('aria-disabled')==='false');
  await toggle.click();
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),true);
  await toggle.click();
  // After initial connection, normal in-flight replies allow the original page to be shown.
  await page.evaluate(()=>{delete window.__finishFirst;void window.DragonClaw.send('普通对话测试');});
  await page.waitForFunction(()=>!!window.__finishFirst);
  await toggle.click();
  assert.equal(await page.locator('#aiBarFrameWrap').evaluate(el=>el.classList.contains('open')),true);
  await page.evaluate(()=>window.__finishFirst());
  await page.waitForFunction(()=>!document.getElementById('aiBarSend').classList.contains('busy'));
  await toggle.click();

  const cases=[
    {status:200,json:{code:500,message:'数据源不存在: fixture-readonly; token="fixture-secret-value" <img src=x onerror=alert(1)>'}},
    {status:503,json:{code:-1,message:'基座 API 暂时不可用'}},
    {status:422,json:{detail:[{loc:['body','table'],msg:'Field required',input:'do-not-copy-validation-input'}]}},
    {status:502,raw:'<html>gateway error token=do-not-copy-html</html>'},
    {network:true},
  ];
  for(const fixture of cases){
    executionFailure=fixture;
    await page.evaluate(async()=>{
      document.getElementById('aiBarAgent').checked=true;
      window.__errorPrompts=[];
      let step=0;
      window.ADCChat.ask=async(prompt,options)=>{
        window.__errorPrompts.push(prompt);
        options.onUpdate(step++===0?'```dragon-action\n'+JSON.stringify({tool:'describe_table',args:{source:'netcare',table:'fixture_table',password:'do-not-copy-write-values'},reason:'查看表结构测试'})+'\n```':'查询失败，请核对环境与数据源。');
      };
      await window.DragonClaw.send('查看表结构');
    });
    const card=page.locator('.dct').last(), header=card.locator('.dct-h');
    assert.match(await card.locator('.dct-st').innerText(),/失败.*查看详情/);
    assert.equal(await header.getAttribute('aria-expanded'),'false');
    await card.locator('.dct-st').click();
    assert.equal(await header.getAttribute('aria-expanded'),'true');
    const diagnostic=JSON.parse(await card.locator('pre code').innerText());
    assert.equal(diagnostic.httpStatus,fixture.network?null:fixture.status);
    assert.equal(diagnostic.code,fixture.json?.code??null);
    assert.equal(diagnostic.tool,'describe_table');
    assert.deepEqual(diagnostic.args,{source:'netcare',table:'fixture_table'});
    assert.equal(diagnostic.requestId,fixture.network?'':'fixture-error-123');
    if(fixture.status===200) assert.match(diagnostic.message,/数据源不存在: fixture-readonly/);
    if(fixture.status===422) assert.match(diagnostic.message,/body.*table.*Field required/);
    if(fixture.status===502) assert.match(diagnostic.message,/有效 JSON/);
    if(fixture.network) assert.match(diagnostic.message,/网络请求未完成/);
    const exposed=(await card.innerHTML())+await page.evaluate(()=>window.__errorPrompts.join('\n'));
    for(const secret of ['fixture-secret-value','do-not-copy-html','do-not-copy-write-values','do-not-copy-validation-input']) assert(!exposed.includes(secret),'Diagnostic leaked '+secret);
    assert.equal(await card.locator('img').count(),0,'Error text must not execute HTML');
    await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copiedDiagnostic=text;}}}));
    await card.locator('.dcm-copy').click();
    assert.deepEqual(JSON.parse(await page.evaluate(()=>window.__copiedDiagnostic)),diagnostic);
    await header.focus(); await page.keyboard.press('Enter');
    assert.equal(await header.getAttribute('aria-expanded'),'false');
    await page.keyboard.press('Space');
    assert.equal(await header.getAttribute('aria-expanded'),'true');
  }
  executionFailure=null;
  console.log('PASS: first-session wait explanation, normal in-flight expansion, clickable/copyable error details, business/HTTP/validation/non-JSON/network failures and diagnostic redaction.');
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(8000);
  page.on('pageerror', e => {errors.push(e.message);console.error('PAGE:', e.message);});
  await page.addInitScript(() => { try { localStorage.setItem('api_test_aibar', JSON.stringify({ open: true, x: 5000, y: -400, w: 2000, h: 2000 })); } catch {} });
  await page.goto(origin + '/');
  await page.waitForFunction(() => !!window.DragonClaw);
  await contained(page);
  for (const [dx, dy] of [[-6000, -6000], [6000, 6000], [-6000, 6000], [6000, -6000]]) await drag(page, '.aibar-h', dx, dy);
  for (const [dx, dy] of [[-6000, -6000], [6000, 6000]]) await drag(page, '#aiBarBr', dx, dy, { x: 6, y: 6 });
  for (const dx of [-6000, 6000]) await drag(page, '#aiBarRz', dx, 0, { x: 3, y: 120 });
  await page.locator('#aiBarAgent').uncheck({ force: true });
  await page.evaluate(() => window.DragonClaw.send('1+1'));
  await page.locator('.dcm-copy').waitFor();
  for (const selector of ['#aiBarClose', '#aiBarNewSess', '.dcm-actions button', '.dcm-copy', '#aiBarFrameToggle']) {
    const color = await page.locator(selector).first().evaluate(el => getComputedStyle(el).backgroundColor);
    const rgb = color.match(/[\d.]+/g).map(Number);
    assert(rgb.slice(0, 3).every(channel => channel < 100), `${selector}: unexpected bright background ${color}`);
  }
  for (const zoom of ['50', '70', '100']) { await page.locator('#aiBarFrameZoom').selectOption(zoom); await contained(page); }
  await page.locator('#aiBarFrameToggle').click(); await contained(page); await page.locator('#aiBarFrameToggle').click();
  for (const size of [{ width: 1024, height: 600 }, { width: 640, height: 400 }, { width: 320, height: 280 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size); await contained(page);
    await page.locator('#aiBarClose').click(); await page.evaluate(() => window.DragonClaw.open()); await contained(page);
  }
  // Browser zoom/pinch changes the visual viewport without requiring window.resize.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1.75 });
  await page.waitForTimeout(80); await contained(page);
  await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
  await page.waitForTimeout(80); await contained(page);
  if (process.env.UI_SCREENSHOTS) {
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#aiBar').evaluate(el => el.scrollLeft), 0, 'Viewport changes must not scroll outer panel content sideways');
    fs.mkdirSync(process.env.UI_SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: path.join(process.env.UI_SCREENSHOTS, 'dragon-claw-dark.png') });
  }
  await assistantFeedback(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  console.log('Geometry and dark buttons passed.');
  await workspace(page, origin, '/');
  await workspace(page, origin, prefix);
  htmlFallback = true;
  await workspace(page, origin, prefix, true);
  htmlFallback = false;
  assert(!requests.some(url => /\/dev(?:\?|$)/.test(url)), 'Developer mode must not navigate to /dev');
  assert.deepEqual(errors, []);
  console.log('PASS: restored geometry, four-edge dragging, both resize handles, dark buttons, iframe zoom, viewport resizing, visual viewport zoom, modal state/focus, root and prefixed API paths, sandboxed embedding.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => { await browser?.close(); server.close(); });
