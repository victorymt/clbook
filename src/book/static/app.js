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

function setLocation(bookId, documentId, replace = false) {
  const suffix = bookId ? `#book=${bookId}${documentId ? `&doc=${documentId}` : ''}` : '';
  // The shelf is always rooted at `/`; retaining a `/books/<id>` pathname
  // would make a browser refresh reopen a deleted book.
  const basePath = bookId ? location.pathname : '/';
  const url = `${basePath}${suffix}`;
  (replace ? history.replaceState : history.pushState).call(history, null, '', url);
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

function renderStatus(title, detail = '') {
  const statusClass = title.startsWith('Unable') ? ' status-error' : '';
  app.innerHTML = `<main class="library"><section class="empty status-view${statusClass}" role="status"><span class="status-dot" aria-hidden="true"></span><strong>${escapeHtml(title)}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ''}</section></main>`;
}

function showReaderError(message) {
  const titleGroup = app.querySelector('.reader-title-group');
  if (!titleGroup) return;
  let error = titleGroup.querySelector('.reader-error');
  if (!error) {
    error = document.createElement('span');
    error.className = 'reader-error';
    error.setAttribute('role', 'alert');
    titleGroup.append(error);
  }
  error.textContent = message;
}

function clearReaderError() {
  app.querySelector('.reader-error')?.remove();
}

function renderLibrary(books) {
  cancelProgressSave();
  state.book = null;
  state.currentDocumentId = null;
  const bookLabel = books.length === 1 ? 'book' : 'books';
  app.innerHTML = `
    <main class="library">
      <header class="library-header">
        <div class="library-heading"><span class="library-kicker">Your shelves</span><h1>book</h1></div>
        <div class="library-header-actions"><button id="add-book" class="primary-button" type="button">New book</button><div class="book-count"><strong>${books.length}</strong><span>${bookLabel}</span></div></div>
      </header>
      ${books.length ? `<section class="book-list" aria-label="Books">${books.map((book, index) => `
        <button class="book-row" type="button" data-book-id="${book.id}">
          <span class="book-index" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span>
          <span class="book-copy"><span class="book-title">${escapeHtml(book.title)}</span>${book.description ? `<span class="book-description">${escapeHtml(book.description)}</span>` : '<span class="book-description book-description-empty">No description</span>'}</span>
          <span class="book-documents"><strong>${book.document_count}</strong><span>${book.document_count === 1 ? 'chapter' : 'chapters'}</span></span>
          <span class="book-arrow" aria-hidden="true">&rarr;</span>
        </button>`).join('')}</section>` : '<section class="empty"><strong>No books yet</strong><span>Create a book to start building your shelf.</span></section>'}
    </main>`;
  app.querySelectorAll('[data-book-id]').forEach((button) => {
    button.addEventListener('click', () => loadBook(Number(button.dataset.bookId)));
  });
  setLocation(null, null, true);
  app.querySelector('#add-book')?.addEventListener('click', createBook);
}

async function createBook() {
  const title = window.prompt('Book title');
  if (!title?.trim()) return;
  const description = window.prompt('Description (optional)', '') || '';
  try {
    const book = await request('/api/books', { method: 'POST', body: JSON.stringify({ title: title.trim(), description }) });
    await loadBook(book.id);
  } catch (error) {
    renderStatus('Unable to create this book', error.message);
  }
}

function renderReader() {
  const book = state.book;
  const documents = book.documents;
  const chapterLabel = documents.length === 1 ? 'chapter' : 'chapters';
  app.innerHTML = `
    <div class="reader" data-theme="${book.theme}">
      <header class="reader-header">
        <button id="back" class="icon-button" type="button" title="Back to books" aria-label="Back to books">&larr;</button>
        <div class="reader-title-group"><span class="reader-kicker">Reading</span><h1>${escapeHtml(book.title)}</h1><p class="subtitle">${escapeHtml(book.description || `${documents.length} ${chapterLabel}`)}</p></div>
        <div class="reader-actions"><button id="edit-book" class="icon-button" type="button" title="Edit book" aria-label="Edit book">✎</button><button id="delete-book" class="icon-button" type="button" title="Delete book" aria-label="Delete book">×</button></div>
        <label class="theme-picker"><span>Theme</span><select id="theme" aria-label="Theme"><option value="light">Light</option><option value="dark">Dark</option></select></label>
        <div class="progress-wrap" aria-label="Reading progress"><div class="progress-copy"><span>Progress</span><strong id="progress-label">0%</strong></div><div class="progress-track" aria-hidden="true"><span id="progress-bar"></span></div></div>
      </header>
      <aside class="toc">
        <div class="toc-heading"><div><span class="toc-kicker">Contents</span><h2>Chapters</h2></div><span class="toc-count">${documents.length}</span></div>
        <form id="search-form" class="search-form"><label class="sr-only" for="search-input">Search this book</label><input id="search-input" autocomplete="off" placeholder="Search chapters"><button title="Search" aria-label="Search" type="submit">&#8981;</button></form>
        <div id="search-results" class="search-results" role="status" aria-live="polite" hidden></div>
        <ol id="toc-list" class="toc-list">${documents.map((document) => chapterItem(document)).join('')}</ol>
      </aside>
      <main class="reading-area">${documents.length ? '<iframe id="reader-frame" class="reader-frame" title="Document reader" sandbox="allow-same-origin allow-popups"></iframe><nav class="chapter-nav" aria-label="Chapter navigation"><button id="previous" type="button"><span aria-hidden="true">&larr;</span> Previous</button><span id="chapter-position" class="chapter-position" aria-live="polite"></span><button id="next" type="button">Next <span aria-hidden="true">&rarr;</span></button></nav>' : '<div class="reader-empty"><strong>No chapters</strong><span>Add a document to this book to start reading.</span></div>'}</main>
    </div>`;
  const theme = app.querySelector('#theme');
  theme.value = book.theme;
  theme.addEventListener('change', async () => {
    const previousTheme = book.theme;
    book.theme = theme.value;
    app.querySelector('.reader').dataset.theme = book.theme;
    try {
      await persistReaderState(book.id, state.currentDocumentId, book.theme);
      clearReaderError();
      if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
    } catch (error) {
      book.theme = previousTheme;
      theme.value = previousTheme;
      app.querySelector('.reader').dataset.theme = previousTheme;
      showReaderError(`Unable to save theme: ${error.message}`);
    }
  });
  app.querySelector('#back').addEventListener('click', showLibrary);
  app.querySelector('#edit-book').addEventListener('click', editBook);
  app.querySelector('#delete-book').addEventListener('click', deleteBook);
  bindSearch();
  bindChapters();
  updateBookProgress();
}

async function editBook() {
  if (!state.book) return;
  const title = window.prompt('Book title', state.book.title);
  if (!title?.trim()) return;
  const description = window.prompt('Description (optional)', state.book.description || '');
  if (description === null) return;
  try {
    state.book = await request(`/api/books/${state.book.id}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim(), description }) });
    renderReader();
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
  } catch (error) {
    renderStatus('Unable to edit this book', error.message);
  }
}

async function deleteBook() {
  if (!state.book || !window.confirm(`Delete “${state.book.title}” and its archived chapters?`)) return;
  try {
    await request(`/api/books/${state.book.id}?with_documents=true`, { method: 'DELETE' });
    await showLibrary();
  } catch (error) {
    renderStatus('Unable to delete this book', error.message);
  }
}

function chapterItem(document) {
  const selected = document.id === state.currentDocumentId ? ' selected' : '';
  const progress = Math.round(Math.max(0, Math.min(1, Number(document.scroll_ratio || 0))) * 100);
  const first = document.position <= 1 ? ' disabled' : '';
  const last = document.position >= state.book.documents.length ? ' disabled' : '';
  const stale = document.source_stale ? ' <span class="toc-stale" title="Source file changed">●</span>' : '';
  return `<li class="toc-item${selected}" draggable="true" data-document-id="${document.id}">
    <button class="toc-open" type="button"${document.id === state.currentDocumentId ? ' aria-current="page"' : ''}><span class="toc-position">${String(document.position).padStart(2, '0')}</span><span class="toc-title">${escapeHtml(document.title)}${stale}</span><span class="toc-progress" aria-label="${progress}% complete"><span style="width: ${progress}%"></span></span></button>
    <span class="move-controls"><button class="move-button" type="button" data-move="-1" title="Move chapter up" aria-label="Move chapter up"${first}>&#8593;</button><button class="move-button" type="button" data-move="1" title="Move chapter down" aria-label="Move chapter down"${last}>&#8595;</button><button class="move-button" type="button" data-rename title="Rename chapter" aria-label="Rename chapter">✎</button><button class="move-button" type="button" data-refresh title="Refresh chapter" aria-label="Refresh chapter">↻</button></span>
  </li>`;
}

function bindChapters() {
  const list = app.querySelector('#toc-list');
  if (!list) return;
  list.querySelectorAll('.toc-item').forEach((item) => {
    const documentId = Number(item.dataset.documentId);
    item.querySelector('.toc-open').addEventListener('click', () => selectDocument(documentId));
    item.querySelectorAll('[data-move]').forEach((button) => button.addEventListener('click', () => moveChapter(documentId, Number(button.dataset.move))));
    item.querySelector('[data-rename]')?.addEventListener('click', () => renameChapter(documentId));
    item.querySelector('[data-refresh]')?.addEventListener('click', () => refreshChapter(documentId));
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

async function renameChapter(documentId) {
  const document = state.book?.documents.find((item) => item.id === documentId);
  if (!document) return;
  const title = window.prompt('Chapter title', document.title);
  if (!title?.trim()) return;
  try {
    await request(`/api/documents/${documentId}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) });
    await loadBook(state.book.id, state.currentDocumentId);
  } catch (error) {
    renderStatus('Unable to rename this chapter', error.message);
  }
}

async function refreshChapter(documentId) {
  if (!window.confirm('Refresh this chapter from its source file?')) return;
  try {
    await request(`/api/documents/${documentId}/refresh`, { method: 'POST', body: JSON.stringify({}) });
    await loadBook(state.book.id, documentId);
  } catch (error) {
    renderStatus('Unable to refresh this chapter', error.message);
  }
}

async function persistOrder() {
  const ids = [...app.querySelectorAll('.toc-item')].map((item) => Number(item.dataset.documentId));
  try {
    await request(`/api/books/${state.book.id}/order`, { method: 'PUT', body: JSON.stringify({ document_ids: ids }) });
    state.book = await request(`/api/books/${state.book.id}`);
    renderReader();
    selectDocument(state.currentDocumentId, false);
  } catch (error) {
    renderStatus('Unable to save chapter order', error.message);
    await loadBook(state.book.id, state.currentDocumentId);
  }
}

async function moveChapter(documentId, direction) {
  const ids = state.book.documents.map((document) => document.id);
  const index = ids.indexOf(documentId);
  const target = index + direction;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  try {
    await request(`/api/books/${state.book.id}/order`, { method: 'PUT', body: JSON.stringify({ document_ids: ids }) });
    state.book = await request(`/api/books/${state.book.id}`);
    renderReader();
    selectDocument(state.currentDocumentId, false);
  } catch (error) {
    renderStatus('Unable to move this chapter', error.message);
    await loadBook(state.book.id, state.currentDocumentId);
  }
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
      results.innerHTML = matches.length ? matches.map((match) => `<button class="search-result" type="button" data-document-id="${match.id}"><strong>${escapeHtml(match.title)}</strong><span>${escapeHtml(match.snippet || 'Title match')}</span></button>`).join('') : '<div class="search-result search-empty">No matches</div>';
      results.hidden = false;
      results.querySelectorAll('[data-document-id]').forEach((button) => button.addEventListener('click', () => {
        results.hidden = true;
        selectDocument(Number(button.dataset.documentId));
      }));
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
  const frame = app.querySelector('#reader-frame');
  if (!frame) return;
  if (saveState) {
    try {
      await persistReaderState(state.book.id, documentId, state.book.theme);
    } catch (error) {
      if (selectionGeneration === state.progressGeneration) {
        showReaderError(`Unable to select this chapter: ${error.message}`);
      }
      return;
    }
  }
  if (selectionGeneration !== state.progressGeneration) return;
  state.currentDocumentId = documentId;
  app.querySelectorAll('.toc-item').forEach((item) => {
    const isSelected = Number(item.dataset.documentId) === documentId;
    item.classList.toggle('selected', isSelected);
    const button = item.querySelector('.toc-open');
    if (isSelected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  clearReaderError();
  setLocation(state.book.id, documentId, !saveState);
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
    updateBookProgress();
    scrollElement.addEventListener('scroll', () => {
      const maximum = Math.max(0, scrollElement.scrollHeight - scrollElement.clientHeight);
      const ratio = maximum ? scrollElement.scrollTop / maximum : 0;
      updateProgressLabel(ratio);
      document.scroll_ratio = ratio;
      updateBookProgress();
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
  const bounded = Math.max(0, Math.min(1, ratio));
  if (label) label.textContent = `${Math.round(bounded * 100)}%`;
  const bar = app.querySelector('#progress-bar');
  if (bar) bar.style.width = `${bounded * 100}%`;
  const tocProgress = app.querySelector(`.toc-item[data-document-id="${state.currentDocumentId}"] .toc-progress`);
  const tocBar = tocProgress?.querySelector(':scope > span');
  if (tocProgress) tocProgress.setAttribute('aria-label', `${Math.round(bounded * 100)}% complete`);
  if (tocBar) tocBar.style.width = `${bounded * 100}%`;
}

function updateBookProgress() {
  const documents = state.book?.documents || [];
  const ratio = documents.length
    ? documents.reduce((sum, item) => sum + Number(item.scroll_ratio || 0), 0) / documents.length
    : 0;
  const label = app.querySelector('#progress-label');
  const bar = app.querySelector('#progress-bar');
  const bounded = Math.max(0, Math.min(1, ratio));
  if (label) label.textContent = `${Math.round(bounded * 100)}%`;
  if (bar) bar.style.width = `${bounded * 100}%`;
}

function saveProgress(bookId, documentId, ratio) {
  request(`/api/documents/${documentId}/progress`, { method: 'PUT', body: JSON.stringify({ scroll_ratio: ratio }) }).catch(() => {});
  const document = state.book?.id === bookId
    ? state.book.documents.find((item) => item.id === documentId)
    : null;
  if (document) document.scroll_ratio = ratio;
  if (state.book?.documents.length) {
    state.book.progress = state.book.documents.reduce((sum, item) => sum + Number(item.scroll_ratio || 0), 0) / state.book.documents.length;
    updateBookProgress();
  }
}

function updateNavigation() {
  const index = state.book.documents.findIndex((document) => document.id === state.currentDocumentId);
  const previous = app.querySelector('#previous');
  const next = app.querySelector('#next');
  if (!previous || !next) return;
  previous.disabled = index <= 0;
  next.disabled = index < 0 || index >= state.book.documents.length - 1;
  const position = app.querySelector('#chapter-position');
  if (position) position.textContent = index >= 0 ? `${index + 1} / ${state.book.documents.length}` : '';
}

function adjacentDocument(direction) {
  const index = state.book.documents.findIndex((document) => document.id === state.currentDocumentId);
  const target = state.book.documents[index + direction];
  if (target) selectDocument(target.id);
}

async function loadBook(bookId, requestedDocumentId = null) {
  cancelProgressSave();
  renderStatus('Opening book');
  try {
    state.book = await request(`/api/books/${bookId}`);
    const validRequested = state.book.documents.some((document) => document.id === requestedDocumentId);
    const validLast = state.book.documents.some((document) => document.id === state.book.last_document_id);
    state.currentDocumentId = validRequested ? requestedDocumentId : (validLast ? state.book.last_document_id : state.book.documents[0]?.id || null);
    renderReader();
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
    else setLocation(state.book.id, null, true);
  } catch (error) {
    renderStatus('Unable to open this book', error.message);
  }
}

async function showLibrary() {
  cancelProgressSave();
  renderStatus('Loading library');
  try {
    const books = await request('/api/books');
    renderLibrary(books);
  } catch (error) {
    renderStatus('Unable to load the library', error.message);
  }
}

async function boot() {
  try {
    const route = initialRoute();
    if (route.bookId) await loadBook(route.bookId, route.documentId);
    else await showLibrary();
  } catch (error) {
    renderStatus('Unable to load the library', error.message);
  }
}

async function handleNavigation() {
  const route = initialRoute();
  if (route.bookId) {
    if (!state.book || state.book.id !== route.bookId || state.currentDocumentId !== route.documentId) await loadBook(route.bookId, route.documentId);
  } else if (state.book) {
    await showLibrary();
  }
}

window.addEventListener('hashchange', handleNavigation);
window.addEventListener('popstate', handleNavigation);

window.addEventListener('keydown', (event) => {
  if (!state.book || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    adjacentDocument(-1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    adjacentDocument(1);
  }
});

boot();
