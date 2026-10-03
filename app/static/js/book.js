import { action, bootstrap, observe, element, lengthCheck, exposures, showError } from './client.js';

let state;
let dirty = new Set();
const observed = exposures();
const status = document.querySelector('#save-status');
let resolveReady;
const pageReady = new Promise(resolve => { resolveReady = resolve; });
const initial = observe('book_view', {}, async result => {
  state = result.state;
  render();
  const excerpt = document.querySelector('#excerpt');
  if (bootstrap.exposure_policy === 'cards') {
    // Dialogues are real text blocks, never headings or sentinel markers.
    for (const block of excerpt.querySelectorAll('.excerpt-block')) {
      const paragraphs = block.textContent.split('\n').filter(text => text.trim());
      if (paragraphs.length > 1) {
        block.replaceWith(...paragraphs.map(text => element('p', 'excerpt-block', text)));
      }
    }
    for (const block of excerpt.querySelectorAll('.excerpt-block')) observed.watch(block, 'excerpt_view');
  }
  resolveReady();
});
initial.catch(showError);

async function save(operation, data, callback = () => {}) {
  await pageReady;
  status.textContent = '';
  return action(operation, data, async result => {
    await callback(result);
    state = result.state;
    render();
    status.textContent = operation === 'observe' ? '' : '저장했습니다.';
  });
}

function results(kind) {
  const container = document.querySelector(`#${kind}-results`);
  observed.forgetWithin(container);
  container.replaceChildren();
  if (!state[`${kind}_results`]) { container.hidden = true; return; }
  container.hidden = false;
  container.append(element('h3', '', kind === 'emoji' ? '이모지 반응' : '투표 결과'));
  const block = element('div', 'result-block');
  for (const result of state[`${kind}_results`]) {
    const row = element('div', 'result-row');
    row.append(element('span', '', result.label), element('span', '', `${result.count}명 · ${result.ratio === null ? 'N/A' : (result.ratio * 100).toFixed(1) + '%'}`));
    block.append(row);
  }
  container.append(block);
  observed.watch(block, `${kind}_results_reveal`);
}

function revealPath(area) {
  const directHere = state.origins.community === bootstrap.page_view_id;
  if (area === 'community_reviews') return directHere ? 'community_open' : 'community_restore';
  if (state.origins.short === bootstrap.page_view_id) return 'short_review_submit';
  if (state.entitlements.short) return 'return_visit';
  return directHere ? 'community_open' : 'community_restore';
}

function attachExposure(node, review, area) {
  if (review.mine) return;
  const data = { target_id: review.id, exposure_area: area, reveal_source: revealPath(area) };
  // Separate observers need separate DOM nodes only in the observer map, so register a multi-event wrapper below.
  // Actual review cards are observed; no artificial exposure markers.
  watchReview(node, review, data);
}

const reviewObservers = new Map();
const reviewEmitted = new Set();
const reviewObserver = bootstrap.exposure_policy === 'cards' ? new IntersectionObserver(entries => {
  for (const entry of entries) emitReview(entry.target, entry.intersectionRatio);
}, { threshold: [.5] }) : null;

function emitReview(node, ratio) {
  if (ratio < .5 || document.visibilityState !== 'visible') return;
  const tracked = reviewObservers.get(node);
  if (!tracked) return;
  const kinds = tracked.review.type === 'short' ? ['short_reviews_reveal', 'others_reveal'] : ['others_reveal'];
  for (const kind of kinds) {
    const key = kind === 'short_reviews_reveal' ? `${kind}:${tracked.data.reveal_source}` : kind;
    if (reviewEmitted.has(key)) continue;
    reviewEmitted.add(key);
    observe(kind, { ...tracked.data, visibility_ratio: ratio, active_tab: true }).catch(() => reviewEmitted.delete(key));
  }
}

function watchReview(node, review, data) {
  if (!reviewObserver) return;
  reviewObservers.set(node, { review, data });
  reviewObserver.observe(node);
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  for (const node of reviewObservers.keys()) {
    const r = node.getBoundingClientRect();
    const area = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) * Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
    emitReview(node, r.width * r.height ? area / (r.width * r.height) : 0);
  }
});

function reviewCard(review, community) {
  const card = element('article', 'review-card');
  const meta = element('div', 'review-meta');
  if (review.mine) meta.append(element('span', 'mine-label', '내 감상'));
  meta.append(element('time', '', new Date(review.created_at).toLocaleDateString('ko-KR')));
  card.append(meta, element('p', '', review.body));
  if (community) {
    const controls = element('div', 'review-actions');
    if (!review.mine) {
      const likeButton = element('button', '', `좋아요 ${review.likes}`);
      likeButton.type = 'button';
      likeButton.setAttribute('aria-pressed', String(review.liked));
      likeButton.addEventListener('click', () => runBusy(likeButton, () => save('like', { target_id: review.id, active: !review.liked })));
      const replyButton = element('button', '', `답글 ${review.replies.length}`);
      replyButton.type = 'button';
      replyButton.addEventListener('click', () => runBusy(replyButton, async () => {
        await save('observe', { event_type: 'reply_start', target_id: review.id }, () => {});
        const currentCard = document.querySelector(`#community [data-review-id="${review.id}"]`);
        if (currentCard && !currentCard.querySelector('.reply-form')) currentCard.append(replyForm(review.id));
      }));
      controls.append(likeButton, replyButton);
    } else {
      controls.append(element('span', 'muted', `좋아요 ${review.likes} · 답글 ${review.replies.length}`));
    }
    card.append(controls);
    if (review.replies.length) {
      const replies = element('div', 'replies');
      for (const reply of review.replies) {
        const item = element('div', 'reply');
        if (reply.mine) item.append(element('span', 'mine-label', '내 답글'));
        item.append(element('p', '', reply.body));
        if (reply.mine) {
          const edit = element('button', 'quiet', '수정하기');
          edit.type = 'button';
          edit.addEventListener('click', () => { if (!item.querySelector('form')) item.append(replyForm(review.id, reply)); });
          const remove = element('button', 'quiet', '삭제하기');
          remove.type = 'button';
          remove.addEventListener('click', () => runBusy(remove, () => save('reply', { reply_id: reply.id, delete: true })));
          item.append(edit, remove);
        }
        replies.append(item);
      }
      card.append(replies);
    }
  }
  card.dataset.reviewId = review.id;
  return card;
}

function list(container, reviews, community, area) {
  for (const node of reviewObservers.keys()) if (container.contains(node)) { reviewObserver?.unobserve(node); reviewObservers.delete(node); }
  container.replaceChildren();
  if (!reviews.length) { container.append(element('p', 'empty', '아직 남겨진 감상이 없습니다.')); return; }
  for (const review of reviews) {
    const card = reviewCard(review, community);
    container.append(card);
    if (bootstrap.exposure_policy === 'cards') attachExposure(card, review, area);
  }

}

function render() {
  for (const kind of ['emoji', 'poll']) {
    for (const button of document.querySelectorAll(`[data-choice="${kind}"]`)) button.setAttribute('aria-pressed', String(button.dataset.option === state[`${kind}_selection`]));
    document.querySelector(`[data-cancel="${kind}"]`).hidden = state[`${kind}_selection`] === null;
    results(kind);
  }
  for (const kind of ['short', 'full']) {
    const own = state.own_reviews[kind];
    const form = document.querySelector(`#${kind}-form`);
    const input = form.querySelector('textarea');
    if (!dirty.has(kind)) input.value = own?.body || '';
    form.querySelector('[type=submit]').textContent = own && !own.deleted ? '수정하기' : '등록하기';
    form.querySelector('[data-delete]').hidden = !own || own.deleted;
    if (kind === 'full' && own && !own.deleted) form.hidden = false;
  }
  const individual = document.querySelector('#individual-short');
  individual.hidden = !state.short_reviews;
  if (state.short_reviews) list(document.querySelector('#individual-list'), state.short_reviews.filter(r => !r.mine), false, 'individual_short_reviews');
  const community = document.querySelector('#community');
  community.hidden = !state.community_open;
  document.querySelector('.community-gateway').hidden = state.community_open;
  if (state.community_open) for (const kind of ['short', 'full']) list(document.querySelector(`#community-${kind}`), state.community[kind], true, 'community_reviews');
}

async function runBusy(button, task) {
  button.disabled = true;
  try { await task(); } catch (error) { showError(error); }
  finally { button.disabled = false; }
}

function replyForm(targetId, reply = null) {
  const form = element('form', 'reply-form');
  const label = element('label', '', reply ? '답글 수정' : '답글 남기기');
  const textarea = element('textarea');
  textarea.id = `reply-${crypto.randomUUID()}`;
  label.htmlFor = textarea.id;
  textarea.rows = 3;
  textarea.value = reply?.body || '';
  const limit = element('p', 'muted', '최대 300자');
  const submit = element('button', '', reply ? '수정하기' : '등록하기');
  submit.type = 'submit';
  form.append(label, textarea, limit, submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    runBusy(submit, async () => {
      lengthCheck(textarea, 300);
      await save('reply', { target_id: targetId, body: textarea.value, ...(reply ? { reply_id: reply.id } : {}) });
    });
  });
  return form;
}

for (const button of document.querySelectorAll('[data-choice]')) button.addEventListener('click', () => runBusy(button, () => save(button.dataset.choice, { option_id: button.dataset.option })));
for (const button of document.querySelectorAll('[data-cancel]')) button.addEventListener('click', () => runBusy(button, () => save(button.dataset.cancel, { option_id: null })));
for (const form of document.querySelectorAll('.review-form')) {
  const kind = form.dataset.kind;
  const input = form.querySelector('textarea');
  input.addEventListener('input', () => dirty.add(kind));
  if (kind === 'short') input.addEventListener('focus', event => {
    if (event.isTrusted && !state?.own_reviews.short) pageReady.then(() => observe('short_review_start')).catch(showError);
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    runBusy(form.querySelector('[type=submit]'), async () => {
      lengthCheck(input, kind === 'short' ? 150 : 2000);
      await save(kind, { body: input.value }, () => {
        dirty.delete(kind);
      });
    });
  });
}
for (const button of document.querySelectorAll('[data-delete]')) button.addEventListener('click', () => runBusy(button, () => save(button.dataset.delete, { delete: true }, () => dirty.delete(button.dataset.delete))));
document.querySelector('#community-open').addEventListener('click', event => runBusy(event.target, () => save('observe', { event_type: 'community_open' })));
document.querySelector('#full-open').addEventListener('click', event => runBusy(event.target, async () => {
  await pageReady;
  await observe('full_review_start', {}, () => { document.querySelector('#full-form').hidden = false; });
}));
