const app = document.getElementById('app');

const state = {
  book: null,
  currentDocumentId: null,
  progressTimer: null,
  progressGeneration: 0,
  readerStateWrite: Promise.resolve(),
  dragDocumentId: null,
};

function cancelProgressSave() {
  window.clearTimeout(state.progressTimer);
  state.progressTimer = null;
  state.progressGeneration += 1;
}

function persistReaderState(bookId, documentId, theme) {
  const write = state.readerStateWrite.then(() => request(`/api/books/${bookId}/state`, {
    method: 'PUT',
    body: JSON.stringify({ last_document_id: documentId, theme }),
  }));
  state.readerStateWrite = write.catch(() => {});
  return write;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Request failed.');
  return payload;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

function setLocation(bookId, documentId) {
  const suffix = bookId ? `#book=${bookId}${documentId ? `&doc=${documentId}` : ''}` : '';
  history.replaceState(null, '', `${location.pathname}${suffix}`);
}

function initialRoute() {
  const pathBook = location.pathname.match(/^\/books\/(\d+)$/);
  if (pathBook) return { bookId: Number(pathBook[1]), documentId: null };
  const params = new URLSearchParams(location.hash.slice(1));
  return {
    bookId: params.get('book') ? Number(params.get('book')) : null,
    documentId: params.get('doc') ? Number(params.get('doc')) : null,
  };
}

function renderLibrary(books) {
  cancelProgressSave();
  state.book = null;
  state.currentDocumentId = null;
  app.innerHTML = `
    <main class="library">
      <header class="library-header">
        <div><h1>book</h1></div>
        <span class="book-count">${books.length} books</span>
      </header>
      ${books.length ? `<section class="book-list">${books.map((book) => `
        <button class="book-row" type="button" data-book-id="${book.id}">
          <span><span class="book-title">${escapeHtml(book.title)}</span>${book.description ? `<span class="book-description">${escapeHtml(book.description)}</span>` : ''}</span>
          <span class="book-documents">${book.document_count} chapters</span>
          <span class="book-arrow" aria-hidden="true">&rarr;</span>
        </button>`).join('')}</section>` : '<section class="empty">No books</section>'}
    </main>`;
  app.querySelectorAll('[data-book-id]').forEach((button) => {
    button.addEventListener('click', () => loadBook(Number(button.dataset.bookId)));
  });
  setLocation(null, null);
}

function renderReader() {
  const book = state.book;
  const documents = book.documents;
  app.innerHTML = `
    <div class="reader" data-theme="${book.theme}">
      <header class="reader-header">
        <button id="back" class="icon-button" type="button" title="Books" aria-label="Books">&larr;</button>
        <div><h1>${escapeHtml(book.title)}</h1><p class="subtitle">${escapeHtml(book.description || `${documents.length} chapters`)}</p></div>
        <label class="theme-picker"><span>Theme</span><select id="theme"><option value="light">Light</option><option value="dark">Dark</option></select></label>
        <span id="progress-label" class="progress-label">0%</span>
      </header>
      <aside class="toc">
        <form id="search-form" class="search-form"><label class="sr-only" for="search-input">Search this book</label><input id="search-input" autocomplete="off" placeholder="Search this book"><button title="Search" aria-label="Search" type="submit">&#9906;</button></form>
        <div id="search-results" class="search-results" hidden></div>
        <ol id="toc-list" class="toc-list">${documents.map((document) => chapterItem(document)).join('')}</ol>
      </aside>
      <main class="reading-area">${documents.length ? '<iframe id="reader-frame" class="reader-frame" title="Document reader" sandbox="allow-same-origin allow-popups"></iframe><nav class="chapter-nav"><button id="previous" type="button">Previous</button><button id="next" type="button">Next</button></nav>' : '<div class="reader-empty">No chapters</div>'}</main>
    </div>`;
  const theme = app.querySelector('#theme');
  theme.value = book.theme;
  theme.addEventListener('change', async () => {
    book.theme = theme.value;
    app.querySelector('.reader').dataset.theme = book.theme;
    await persistReaderState(book.id, state.currentDocumentId, book.theme);
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
  });
  app.querySelector('#back').addEventListener('click', showLibrary);
  bindSearch();
  bindChapters();
}

function chapterItem(document) {
  const selected = document.id === state.currentDocumentId ? ' selected' : '';
  return `<li class="toc-item${selected}" draggable="true" data-document-id="${document.id}">
    <button class="toc-open" type="button"><span class="toc-position">${document.position}</span><span class="toc-title">${escapeHtml(document.title)}</span></button>
    <span class="move-controls"><button class="move-button" type="button" data-move="-1" title="Move chapter up" aria-label="Move chapter up">&#8593;</button><button class="move-button" type="button" data-move="1" title="Move chapter down" aria-label="Move chapter down">&#8595;</button></span>
  </li>`;
}

function bindChapters() {
  const list = app.querySelector('#toc-list');
  if (!list) return;
  list.querySelectorAll('.toc-item').forEach((item) => {
    const documentId = Number(item.dataset.documentId);
    item.querySelector('.toc-open').addEventListener('click', () => selectDocument(documentId));
    item.querySelectorAll('[data-move]').forEach((button) => button.addEventListener('click', () => moveChapter(documentId, Number(button.dataset.move))));
    item.addEventListener('dragstart', () => { state.dragDocumentId = documentId; item.classList.add('dragging'); });
    item.addEventListener('dragend', () => { state.dragDocumentId = null; item.classList.remove('dragging'); });
    item.addEventListener('dragover', (event) => event.preventDefault());
    item.addEventListener('drop', async (event) => {
      event.preventDefault();
      if (!state.dragDocumentId || state.dragDocumentId === documentId) return;
      const dragged = list.querySelector(`[data-document-id="${state.dragDocumentId}"]`);
      if (dragged) list.insertBefore(dragged, item);
      await persistOrder();
    });
  });
  const previous = app.querySelector('#previous');
  const next = app.querySelector('#next');
  if (previous) previous.addEventListener('click', () => adjacentDocument(-1));
  if (next) next.addEventListener('click', () => adjacentDocument(1));
}

async function persistOrder() {
  const ids = [...app.querySelectorAll('.toc-item')].map((item) => Number(item.dataset.documentId));
  await request(`/api/books/${state.book.id}/order`, { method: 'PUT', body: JSON.stringify({ document_ids: ids }) });
  state.book = await request(`/api/books/${state.book.id}`);
  renderReader();
  selectDocument(state.currentDocumentId, false);
}

async function moveChapter(documentId, direction) {
  const ids = state.book.documents.map((document) => document.id);
  const index = ids.indexOf(documentId);
  const target = index + direction;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  await request(`/api/books/${state.book.id}/order`, { method: 'PUT', body: JSON.stringify({ document_ids: ids }) });
  state.book = await request(`/api/books/${state.book.id}`);
  renderReader();
  selectDocument(state.currentDocumentId, false);
}

function bindSearch() {
  const form = app.querySelector('#search-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = app.querySelector('#search-input');
    const value = input.value.trim();
    const results = app.querySelector('#search-results');
    if (!value) { results.hidden = true; results.innerHTML = ''; return; }
    try {
      const matches = await request(`/api/search?q=${encodeURIComponent(value)}&book=${state.book.id}`);
      results.innerHTML = matches.length ? matches.map((match) => `<button class="search-result" type="button" data-document-id="${match.id}"><strong>${escapeHtml(match.title)}</strong><span>${escapeHtml(match.snippet || 'Title match')}</span></button>`).join('') : '<div class="search-result">No matches</div>';
      results.hidden = false;
      results.querySelectorAll('[data-document-id]').forEach((button) => button.addEventListener('click', () => selectDocument(Number(button.dataset.documentId))));
    } catch (error) {
      results.textContent = error.message;
      results.hidden = false;
    }
  });
}

async function selectDocument(documentId, saveState = true) {
  const document = state.book.documents.find((item) => item.id === documentId);
  if (!document) return;
  cancelProgressSave();
  const selectionGeneration = state.progressGeneration;
  state.currentDocumentId = documentId;
  app.querySelectorAll('.toc-item').forEach((item) => item.classList.toggle('selected', Number(item.dataset.documentId) === documentId));
  const frame = app.querySelector('#reader-frame');
  if (!frame) return;
  if (saveState) await persistReaderState(state.book.id, documentId, state.book.theme);
  if (selectionGeneration !== state.progressGeneration || state.currentDocumentId !== documentId) return;
  setLocation(state.book.id, documentId);
  const progressGeneration = state.progressGeneration;
  frame.onload = () => restoreProgress(document, frame, progressGeneration);
  frame.src = `/documents/${documentId}/content?theme=${encodeURIComponent(state.book.theme)}`;
  updateNavigation();
}

function restoreProgress(document, frame, progressGeneration) {
  if (progressGeneration !== state.progressGeneration || state.currentDocumentId !== document.id) return;
  const bookId = state.book?.id;
  if (bookId === undefined) return;
  try {
    const child = frame.contentDocument;
    const scrollElement = child.scrollingElement || child.documentElement;
    const maxScroll = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
    scrollElement.scrollTop = maxScroll * Number(document.scroll_ratio || 0);
    updateProgressLabel(Number(document.scroll_ratio || 0));
    scrollElement.addEventListener('scroll', () => {
      const maximum = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
      const ratio = maximum ? scrollElement.scrollTop / maximum : 0;
      updateProgressLabel(ratio);
      window.clearTimeout(state.progressTimer);
      const generation = state.progressGeneration;
      state.progressTimer = window.setTimeout(() => {
        if (generation === state.progressGeneration && state.currentDocumentId === document.id) {
          saveProgress(bookId, document.id, ratio);
        }
      }, 450);
    }, { passive: true });
  } catch (_) {
    updateProgressLabel(0);
  }
}

function updateProgressLabel(ratio) {
  const label = app.querySelector('#progress-label');
  if (label) label.textContent = `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`;
}

function saveProgress(bookId, documentId, ratio) {
  request(`/api/documents/${documentId}/progress`, { method: 'PUT', body: JSON.stringify({ scroll_ratio: ratio }) }).catch(() => {});
  const document = state.book?.id === bookId
    ? state.book.documents.find((item) => item.id === documentId)
    : null;
  if (document) document.scroll_ratio = ratio;
}

function updateNavigation() {
  const index = state.book.documents.findIndex((document) => document.id === state.currentDocumentId);
  const previous = app.querySelector('#previous');
  const next = app.querySelector('#next');
  if (!previous || !next) return;
  previous.disabled = index <= 0;
  next.disabled = index < 0 || index >= state.book.documents.length - 1;
}

function adjacentDocument(direction) {
  const index = state.book.documents.findIndex((document) => document.id === state.currentDocumentId);
  const target = state.book.documents[index + direction];
  if (target) selectDocument(target.id);
}

async function loadBook(bookId, requestedDocumentId = null) {
  cancelProgressSave();
  state.book = await request(`/api/books/${bookId}`);
  const validRequested = state.book.documents.some((document) => document.id === requestedDocumentId);
  const validLast = state.book.documents.some((document) => document.id === state.book.last_document_id);
  state.currentDocumentId = validRequested ? requestedDocumentId : (validLast ? state.book.last_document_id : state.book.documents[0]?.id || null);
  renderReader();
  if (state.currentDocumentId) selectDocument(state.currentDocumentId);
}

async function showLibrary() {
  cancelProgressSave();
  const books = await request('/api/books');
  renderLibrary(books);
}

async function boot() {
  try {
    const route = initialRoute();
    if (route.bookId) await loadBook(route.bookId, route.documentId);
    else await showLibrary();
  } catch (error) {
    app.innerHTML = `<main class="library"><section class="empty">${escapeHtml(error.message)}</section></main>`;
  }
}

window.addEventListener('hashchange', () => {
  const route = initialRoute();
  if (route.bookId && (!state.book || state.book.id !== route.bookId || state.currentDocumentId !== route.documentId)) loadBook(route.bookId, route.documentId);
});

boot();
