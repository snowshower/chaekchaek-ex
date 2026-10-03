const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const path = require('node:path');

const isAction = (response, type) => {
  if (!response.url().endsWith('/api/actions')) return false;
  const data = response.request().postDataJSON();
  return (data.event_type || data.operation) === type;
};
async function action(page, type, click) {
  const response = page.waitForResponse(r => isAction(r, type));
  await click();
  const result = await response;
  assert.equal(result.status(), 200, await result.text());
  assert.equal((await result.json()).ok, true);
  return result;
}

(async () => {
  // browser_server uses pending by default to cover stale pre-cards startup settings.
  const server = spawn(path.resolve(process.env.PYTHON_EXECUTABLE || '.venv/Scripts/python.exe'),
    ['tests/browser_server.py'], {stdio: ['ignore', 'pipe', 'pipe']});
  let browser;
  let diagnostics = '';
  server.stderr.on('data', data => { diagnostics += data; });
  try {
    const [chunk] = await once(server.stdout, 'data');
    const url = 'http://127.0.0.1:' + chunk.toString().trim();
    browser = await chromium.launch({
      executablePath: process.env.BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
      headless: true,
    });
    const a = await browser.newPage({viewport:{width:1000,height:800}});
    const b = await browser.newPage({viewport:{width:1000,height:800}});
    const errors = [], reveals = [];
    for (const page of [a,b]) page.on('pageerror', error => errors.push(error.message));
    b.on('response', response => {
      if (isAction(response, 'others_reveal')) reveals.push(response);
    });
    await a.goto(url+'/books/metamorphosis');
    assert.equal(await a.locator('#bootstrap').evaluate(n => JSON.parse(n.dataset.json).exposure_policy), 'cards');
    await a.locator('#short-body').fill('Browser writer A');
    await action(a, 'short', () => a.locator('#short-form [type=submit]').click());
    await b.goto(url+'/books/metamorphosis');
    const reveal = b.waitForResponse(r => isAction(r, 'others_reveal'));
    await action(b, 'community_open', () => b.locator('#community-open').click());
    const card = b.locator('#community-short .review-card').first();
    await card.scrollIntoViewIfNeeded();
    const response = await reveal;
    assert.equal(response.status(), 200, await response.text());
    assert.equal((await response.json()).ok, true);
    const payload = response.request().postDataJSON();
    assert.equal(payload.active_tab, true);
    assert.ok(payload.visibility_ratio >= .5);
    assert.ok(payload.target_id);
    assert.equal(await card.locator('.mine-label').count(), 0);
    await action(b, 'like', () => card.getByRole('button', {name:'좋아요 0'}).click());
    await action(b, 'reply_start', () => card.getByRole('button', {name:'답글 0'}).click());
    await card.locator('.reply-form textarea').fill('Browser reply B');
    await action(b, 'reply', () => card.locator('.reply-form [type=submit]').click());
    assert.equal(reveals.length, 1, 'multiple short cards and rerenders must not duplicate exposure on the page');
    assert.equal(await b.locator('#page-error').innerText(), '');
    assert.deepEqual(errors, []);
    const admin = await browser.newPage({httpCredentials:{username:'admin',password:'browser-password'}});
    await admin.goto(url+'/admin/');
    const scope = admin.locator('#test-data section').filter({has:admin.getByRole('heading', {name:/metamorphosis/})});
    const metric = name => scope.locator('tbody tr').filter({has:admin.getByRole('cell',{name,exact:true})}).first();
    assert.equal(await metric('타인 감상 실제 노출률 E/V').locator('td').nth(1).innerText(), '1');
    assert.equal(await metric('타인 감상 실제 노출률 E/V').locator('td').nth(2).innerText(), '2');
    assert.equal(await metric('상호작용률 (L∪R)/E').locator('td').nth(1).innerText(), '1');
    assert.equal(await admin.locator('.admin-summary strong').first().innerText(), '0 / 50명');
    console.log('PASS: legacy pending → cards bootstrap → real review DOM → native IntersectionObserver ≥50% → others_reveal POST 200 → like/reply → test admin E/V=1/2, interaction=1/1, experiment visitors=0; no page errors');
  } catch (error) {
    console.error(diagnostics.slice(-3000));
    throw error;
  } finally {
    await browser?.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });