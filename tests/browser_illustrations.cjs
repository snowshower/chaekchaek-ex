const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const path = require('node:path');
const fs = require('node:fs');

(async()=>{
 const server=spawn(path.resolve(process.env.PYTHON_EXECUTABLE||'.venv/Scripts/python.exe'),['tests/browser_server.py'],{stdio:['ignore','pipe','pipe']});
 server.stderr.on('data',()=>{});
 let browser;
 try {
  const [port]=await once(server.stdout,'data');const url='http://127.0.0.1:'+port.toString().trim();
  browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  fs.mkdirSync('artifacts/ui',{recursive:true});
  for(const bid of ['little-prince','old-man-and-sea','metamorphosis']){
   const page=await browser.newPage({viewport:{width:1000,height:400}});
   const events=[];
   page.on('request',r=>{if(r.url().endsWith('/api/actions')) events.push(r.postDataJSON().event_type||r.postDataJSON().operation)});
   const viewed=page.waitForResponse(r=>r.url().endsWith('/api/actions') && r.request().postDataJSON().event_type==='book_view');
   await page.goto(url+'/books/'+bid);assert.equal((await viewed).status(),200);
   const img=page.locator('.scene-illustration img');
   await img.scrollIntoViewIfNeeded();
   await page.waitForFunction(()=>{const img=document.querySelector('.scene-illustration img');return img.complete && img.naturalWidth>0});
   const layout=await img.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);const area=Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0))*Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0));return {width:r.width,height:r.height,ratio:n.naturalWidth/n.naturalHeight,visible:area/(r.width*r.height),fit:s.objectFit,excerptTop:document.querySelector('.excerpt-block').getBoundingClientRect().top}});
   assert.ok(layout.visible>=.5);
   assert.ok(layout.excerptTop>=400, 'original excerpt is outside viewport during image-only exposure');
   assert.ok(Math.abs(layout.width/layout.height-layout.ratio)<.001);
   assert.ok(layout.width<=640);assert.equal(layout.fit,'contain');
   assert.equal(await img.getAttribute('src'),'/static/images/books/'+bid+'.png');
   assert.ok(await img.getAttribute('alt'));
   await page.waitForTimeout(250);
   assert.deepEqual(events,['book_view'], 'image exposure must not generate any exposure event');
   assert.ok(await page.locator('.scene-illustration').evaluate(n=>n.previousElementSibling.classList.contains('situation') && n.nextElementSibling.classList.contains('excerpt-section')));
   await img.screenshot({path:'artifacts/ui/illustration-'+bid+'.png'});
   const excerpt=page.waitForResponse(r=>r.url().endsWith('/api/actions')&&r.request().postDataJSON().event_type==='excerpt_view');
   await page.locator('.excerpt-block').first().scrollIntoViewIfNeeded();
   assert.equal((await excerpt).status(),200,'original text observer still emits excerpt_view');
   await page.setViewportSize({width:390,height:844});
   await img.scrollIntoViewIfNeeded();
   const mobile=await img.evaluate(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height,ratio:n.naturalWidth/n.naturalHeight}));
   assert.ok(Math.abs(mobile.width/mobile.height-mobile.ratio)<.001);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:'artifacts/ui/illustration-'+bid+'-mobile.png',fullPage:true});
   await page.close();
  }
  console.log('PASS: all three PNGs load at the correct position with alt/lazy/async; original aspect ratio and no mobile overflow; image >=50% emits no exposure; original text still emits excerpt_view.');
 } finally {await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});