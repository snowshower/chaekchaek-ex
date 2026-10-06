export const bootstrap = JSON.parse(document.querySelector('#bootstrap').dataset.json);
// Attribution is already persisted server-side; this emits no request or event.
const entryUrl = new URL(window.location.href);
if (entryUrl.searchParams.has('src')) {
  entryUrl.searchParams.delete('src');
  window.history.replaceState(window.history.state, '', entryUrl.pathname + entryUrl.search + entryUrl.hash);
}
let sequence = 0;
let queue = Promise.resolve();
let pending = null;
const errorNode = document.querySelector('#page-error');
const retryButton = document.querySelector('#retry');

export function showError(error) { errorNode.textContent = error.message || String(error); }
export function clearError() { errorNode.textContent = ''; }

export function action(operation, data = {}, onSuccess = async () => {}) {
  const payload = { ...data, operation, event_id: crypto.randomUUID(), page_view_id: bootstrap.page_view_id, client_occurred_at: new Date().toISOString(), client_sequence: ++sequence };
  const work = async () => {
    if (pending) throw new Error('저장 여부를 확인하지 못한 요청이 있습니다. 같은 요청을 먼저 다시 시도해주세요.');
    const send = async () => {
      const response = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': bootstrap.csrf }, body: JSON.stringify(payload) });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(result.error || '요청에 실패했습니다.');
        error.retryable = response.status >= 500;
        throw error;
      }
      pending = null;
      if (retryButton) retryButton.hidden = true;
      clearError();
      await onSuccess(result);
      return result;
    };
    try { return await send(); }
    catch (error) {
      pending = error.retryable === false ? null : { send };
      if (retryButton) retryButton.hidden = !pending;
      showError(new Error(error.message + (pending ? '\n입력은 유지됩니다. 같은 요청을 다시 시도할 수 있습니다.' : '')));
      throw error;
    }
  };
  const result = queue.then(work);
  queue = result.catch(() => {});
  return result;
}

if (retryButton) retryButton.addEventListener('click', async () => {
  if (!pending) return;
  retryButton.disabled = true;
  try { await pending.send(); }
  catch (error) { showError(error); }
  finally { retryButton.disabled = false; }
});

export function observe(kind, data = {}, onSuccess) { return action('observe', { event_type: kind, ...data }, onSuccess); }

export async function loadState() {
  const response = await fetch(`/api/books/${bootstrap.book_id}/state?page_view_id=${bootstrap.page_view_id}`);
  const state = await response.json();
  if (!response.ok) throw new Error(state.error || '현재 상태를 불러올 수 없습니다.');
  return state;
}

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function lengthCheck(input, maximum) {
  if (!input.value.trim()) throw new Error('공백만 있는 글은 등록할 수 없습니다.');
  if (Array.from(input.value).length > maximum) throw new Error(`최대 ${maximum.toLocaleString()}자까지 작성할 수 있습니다.`);
}

// Cards policy observes content blocks, excluding headers and empty states.
export function exposures() {
  const emitted = new Set();
  const watched = new Map();
  let observer;
  function emit(node, ratio) {
    const task = watched.get(node);
    if (!task || ratio < .5 || document.visibilityState !== 'visible' || emitted.has(task.key)) return;
    emitted.add(task.key);
    observe(task.kind, { ...task.data, visibility_ratio: ratio, active_tab: true }).catch(() => { emitted.delete(task.key); });
  }
  if (bootstrap.exposure_policy === 'cards') observer = new IntersectionObserver(entries => entries.forEach(entry => emit(entry.target, entry.intersectionRatio)), { threshold: [.5] });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    for (const node of watched.keys()) {
      const box = node.getBoundingClientRect();
      const visibleWidth = Math.max(0, Math.min(box.right, innerWidth) - Math.max(box.left, 0));
      const visibleHeight = Math.max(0, Math.min(box.bottom, innerHeight) - Math.max(box.top, 0));
      emit(node, box.width * box.height ? visibleWidth * visibleHeight / (box.width * box.height) : 0);
    }
  });
  return {
    watch(node, kind, data = {}, key = kind) { if (!observer) return; watched.set(node, { kind, data, key }); observer.observe(node); },
    forgetWithin(parent) { for (const node of watched.keys()) if (parent.contains(node)) { observer?.unobserve(node); watched.delete(node); } },
  };
}
