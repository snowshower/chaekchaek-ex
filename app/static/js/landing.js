import { action, observe, showError } from './client.js';

let resolveReady;
const ready = new Promise(resolve => { resolveReady = resolve; });
observe('landing_view', {}, () => resolveReady()).catch(showError);
for (const card of document.querySelectorAll('[data-book]')) {
  card.addEventListener('click', async event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    try {
      await ready;
      await action('observe', { event_type: 'book_select', book_id: card.dataset.book, display_position: Number(card.dataset.position) }, result => {
        location.assign(`${card.href}?selection=${encodeURIComponent(result.event_id)}`);
      });
    } catch (error) { showError(error); }
  });
}
