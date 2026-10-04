const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const path = require('node:path');
const fs = require('node:fs');

const isAction = (r, kind) => r.url().endsWith('/api/actions') &&
  (r.request().postDataJSON().event_type || r.request().postDataJSON().operation) === kind;
async function action(page, kind, click) {
  const response = page.waitForResponse(r => isAction(r, kind));
  await click();
  assert.equal((await response).status(), 200);
}

(async () => {
  const server = spawn(path.resolve(process.env.PYTHON_EXECUTABLE || '.venv/Scripts/python.exe'),
    ['tests/browser_server.py'], {env:{...process.env, BROWSER_SEED_FIXTURE:'1', BROWSER_DASHBOARD_FIXTURE:'0'}, stdio:['ignore','pipe','pipe']});
  let browser;
  try {
    const [chunk] = await Promise.race([once(server.stdout, 'data'),
      once(server, 'exit').then(([code]) => {throw new Error(`Seed fixture server exited early (${code})`);})]);
    const fixture = JSON.parse(chunk.toString().trim());
    const origin = 'http://127.0.0.1:' + fixture.port;
    browser = await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true});
    const seed = await browser.newPage({viewport:{width:390,height:844}});
    await seed.goto(origin + fixture.seed_path);
    assert.ok(!(await seed.context().cookies()).some(c=>c.name==='visitor_id'));
    assert.ok(await seed.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const activated = seed.waitForResponse(r => new URL(r.url()).pathname === '/seed/activate' && r.request().method() === 'POST');
    await seed.getByRole('button',{name:'참여 시작',exact:true}).click();
    const activation = await activated;
    assert.equal(activation.status(), 303, 'seed activation failed');
    await seed.waitForURL(origin+'/');
    assert.ok((await seed.context().cookies()).some(c=>c.name==='visitor_id'));
    await seed.goto(origin+'/books/metamorphosis');
    await action(seed,'emoji',()=>seed.locator('.emoji-choices button').nth(0).click());
    await action(seed,'poll',()=>seed.locator('.poll-choices button').nth(0).click());
    await seed.locator('#short-body').fill('처음 남긴 한 줄 감상');
    await action(seed,'short',()=>seed.locator('#short-form [type=submit]').click());
    await action(seed,'community_open',()=>seed.locator('#community-open').click());
    await action(seed,'full_review_start',()=>seed.locator('#full-open').click());
    await seed.locator('#full-body').fill('처음 남긴 자유 감상');
    await action(seed,'full',()=>seed.locator('#full-form [type=submit]').click());
    const reader = await browser.newPage({viewport:{width:1000,height:800}});
    await reader.goto(origin+'/books/metamorphosis');
    await action(reader,'emoji',()=>reader.locator('.emoji-choices button').nth(1).click());
    const revealed = reader.waitForResponse(r=>isAction(r,'others_reveal'));
    await action(reader,'community_open',()=>reader.locator('#community-open').click());
    const card = reader.locator('#community-short .review-card').first();
    await card.scrollIntoViewIfNeeded();
    const exposure = await revealed;
    assert.equal(exposure.status(), 200);
    assert.ok(exposure.request().postDataJSON().visibility_ratio >= .5);
    assert.equal(await card.locator('.mine-label').count(), 0);
    assert.equal(await reader.locator('#community-full .review-card').count(), 1);
    await action(reader,'like',()=>card.getByRole('button',{name:'좋아요 0',exact:true}).click());
    await action(reader,'reply_start',()=>card.getByRole('button',{name:'답글 0',exact:true}).click());
    await card.locator('.reply-form textarea').fill('일반 참여자의 답글');
    await action(reader,'reply',()=>card.locator('.reply-form [type=submit]').click());
    const admin = await browser.newPage({httpCredentials:{username:'admin',password:'browser-password'}});
    await admin.goto(origin+'/admin/');
    assert.equal(await admin.locator('[data-kpi="visitors"] > strong').innerText(), '1명');
    assert.equal(await admin.locator('[data-kpi="others_exposure"] > strong').innerText(), '100.0%');
    assert.equal(await admin.locator('[data-kpi="text_participation"] > strong').innerText(), '0.0%');
    const book = admin.locator('[data-book="metamorphosis"]');
    assert.match(await book.locator('[data-event="like"] dd').innerText(), /^1/);
    assert.match(await book.locator('[data-event="reply_submit"] dd').innerText(), /^1/);
    const fresh = await browser.newPage();
    assert.equal((await fresh.goto(origin + fixture.seed_path)).status(), 400);
    assert.ok(!(await fresh.context().cookies()).some(c=>c.name==='visitor_id'));
    const before = (await reader.context().cookies()).find(c=>c.name==='visitor_id').value;
    assert.equal((await reader.goto(origin + fixture.seed_path)).status(), 409);
    assert.equal((await reader.context().cookies()).find(c=>c.name==='visitor_id').value,before);
    fs.mkdirSync('artifacts/seed',{recursive:true});
    await admin.screenshot({path:'artifacts/seed/admin-normal-actions.png',fullPage:true});
    console.log('PASS: first-entry seed onboarding → public short/full → normal native ≥50% exposure and like/reply → seed excluded from KPI; replay and normal-browser conversion rejected.');
  } finally {
    await browser?.close();
    server.kill();
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
