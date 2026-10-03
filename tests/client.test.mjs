import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { test } from 'node:test';

globalThis.crypto ??= webcrypto;
const listeners = new Map();
const nodes = {
  '#bootstrap': { dataset: { json: JSON.stringify({ page_view_id: 'page', csrf: 'token', exposure_policy: 'cards' }) } },
  '#page-error': { textContent: '' },
  '#retry': { hidden: true, addEventListener(kind, listener) { this.listener = listener; } },
};
globalThis.document = {
  visibilityState: 'visible',
  querySelector: selector => nodes[selector],
  addEventListener(kind, listener) { listeners.set(kind, listener); },
};
globalThis.innerWidth = 400;
globalThis.innerHeight = 800;
let observer;
globalThis.IntersectionObserver = class {
  constructor(callback) { this.callback = callback; observer = this; }
  observe() {}
  unobserve() {}
};
const requests = [];
globalThis.fetch = async (_url, options) => {
  requests.push(JSON.parse(options.body));
  return { ok: true, json: async () => ({ ok: true }) };
};
const client = await import('../app/static/js/client.js');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('50% active-tab exposure only, page deduplication, no DOM-only event', async () => {
  const tracking = client.exposures();
  const node = { getBoundingClientRect: () => ({ left: 0, top: 0, right: 400, bottom: 1000, width: 400, height: 1000 }) };
  tracking.watch(node, 'excerpt_view');
  assert.equal(requests.length, 0);
  observer.callback([{ target: node, intersectionRatio: .49 }]);
  await flush();
  assert.equal(requests.length, 0);
  document.visibilityState = 'hidden';
  observer.callback([{ target: node, intersectionRatio: .9 }]);
  await flush();
  assert.equal(requests.length, 0);
  document.visibilityState = 'visible';
  observer.callback([{ target: node, intersectionRatio: .5 }]);
  await flush();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].visibility_ratio, .5);
  assert.equal(requests[0].active_tab, true);
  observer.callback([{ target: node, intersectionRatio: 1 }]);
  listeners.get('visibilitychange')();
  await flush();
  assert.equal(requests.length, 1);
});

test('response loss retries the exact payload and does not call success before acknowledgment', async () => {
  let confirmed = false;
  let calls = 0;
  const seen = [];
  globalThis.fetch = async (_url, options) => {
    seen.push(options.body);
    if (++calls === 1) throw new Error('network failed');
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await assert.rejects(client.action('short', { body: '글' }, () => { confirmed = true; }));
  assert.equal(confirmed, false);
  assert.equal(nodes['#retry'].hidden, false);
  await nodes['#retry'].listener();
  assert.equal(confirmed, true);
  assert.equal(seen[0], seen[1]);
  assert.equal(nodes['#retry'].hidden, true);
  assert.equal(nodes['#page-error'].textContent, '');
});

test('cards use individual block area and deduplicate multiple cards', async () => {
  client.bootstrap.exposure_policy = 'cards';
  globalThis.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ ok: true }) };
  };
  const before = requests.length;
  const tracking = client.exposures();
  const first = { getBoundingClientRect: () => ({ left: 0, top: 600, right: 400, bottom: 1000, width: 400, height: 400 }) };
  const second = { getBoundingClientRect: () => ({ left: 0, top: 801, right: 400, bottom: 1001, width: 400, height: 200 }) };
  tracking.watch(first, 'excerpt_view');
  tracking.watch(second, 'excerpt_view');
  document.visibilityState = 'hidden';
  observer.callback([{ target: first, intersectionRatio: 1 }]);
  await flush();
  assert.equal(requests.length, before);
  document.visibilityState = 'visible';
  listeners.get('visibilitychange')();
  await flush();
  assert.equal(requests.length, before + 1);
  assert.equal(requests.at(-1).visibility_ratio, .5);
  observer.callback([{ target: second, intersectionRatio: 1 }]);
  await flush();
  assert.equal(requests.length, before + 1);
});
test('definitive validation error keeps input editable and allows a corrected request', async () => {
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1
    ? { ok: false, status: 400, json: async () => ({ error: '검증 실패' }) }
    : { ok: true, json: async () => ({ ok: true }) };
  await assert.rejects(client.action('short', { body: 'invalid' }));
  assert.equal(nodes['#retry'].hidden, true);
  await client.action('short', { body: '수정한 글' });
  assert.equal(calls, 2);
});
