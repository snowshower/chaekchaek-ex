const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const server = spawn(path.resolve(process.env.PYTHON_EXECUTABLE || '.venv/Scripts/python.exe'),
    ['tests/browser_server.py'], {env:{...process.env, BROWSER_DASHBOARD_FIXTURE:'1'}, stdio:['ignore','pipe','pipe']});
  let browser, diagnostics = '';
  server.stderr.on('data', data => { diagnostics += data; });
  try {
    const [chunk] = await Promise.race([once(server.stdout, 'data'),
      once(server, 'exit').then(([code]) => {throw new Error(`Browser fixture server exited early (${code}): ${diagnostics}`);})]);
    const url = 'http://127.0.0.1:' + chunk.toString().trim();
    browser = await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true});
    const page = await browser.newPage({httpCredentials:{username:'admin',password:'browser-password'}});
    fs.mkdirSync('artifacts/dashboard', {recursive:true});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({width,height:900});
      const response = await page.goto(url+'/admin/');
      assert.equal(response.status(), 200);
      assert.equal(await page.locator('[data-kpi="visitors"] > strong').innerText(), '2명');
      for (const name of ['light_participation','text_participation','community_direct','others_exposure']) {
        assert.equal(await page.locator(`[data-kpi="${name}"] > strong`).innerText(), '50.0%');
      }
      assert.equal(await page.locator('.book-dashboard-card').count(), 3);
      assert.equal(await page.locator('#test-data').count(), 0);
      const overflow = () => page.evaluate(() => ({page:document.documentElement.scrollWidth > innerWidth,
        elements:[...document.querySelectorAll('.dashboard, .dashboard *')].filter(e =>
          e.getClientRects().length && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline').map(e=>e.className || e.tagName)}));
      assert.deepEqual(await overflow(), {page:false,elements:[]}, `collapsed overflow at ${width}`);
      if (width === 1440) {
        const cards = await page.locator('.book-dashboard-card').evaluateAll(nodes => nodes.map(n => {const r=n.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}));
        assert.equal(new Set(cards.map(c=>c.top)).size, 1);
        assert.ok(cards.every(c=>c.bottom < 900), 'all three compact cards fit desktop viewport');
      }
      await page.screenshot({path:`artifacts/dashboard/admin-${width}.png`,fullPage:true});
      await page.locator('details').evaluateAll(nodes => nodes.forEach(n => {n.open=true;}));
      assert.deepEqual(await overflow(), {page:false,elements:[]}, `expanded overflow at ${width}`);
      await page.screenshot({path:`artifacts/dashboard/admin-${width}-expanded.png`,fullPage:true});
    }
    assert.deepEqual(errors, []);
    console.log('PASS: dashboard matches seeded union statistics; desktop 1440 and mobile 390/320 have no overflow, collapsed or expanded; three desktop cards fit 900px height.');
  } catch (error) {
    console.error(diagnostics.slice(-2000));
    throw error;
  } finally {
    await browser?.close();
    server.kill();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
