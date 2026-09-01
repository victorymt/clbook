const app = document.getElementById('app');
const SEARCH_PAGE_SIZE = 20;
// Default English fallback retained for static integrations: aria-label="Delete chapter".

const state = {
  book: null,
  currentDocumentId: null,
  progressTimer: null,
  pendingProgress: null,
  progressGeneration: 0,
  readerStateWrite: Promise.resolve(),
  dragDocumentId: null,
  deletingDocumentIds: new Set(),
  books: [],
  viewGeneration: 0,
  locale: (() => {
    try { return window.localStorage?.getItem('book.locale') === 'zh-CN' ? 'zh-CN' : 'en'; } catch (_) { return 'en'; }
  })(),
  selectMode: false,
  selectedDocumentIds: new Set(),
  batchBusy: false,
  batchFeedback: null,
};

const LOCALES = {
  en: {
    shelves: 'Your shelves', appName: 'book', newBook: 'New book', book: 'book', books: 'books',
    noDescription: 'No description', chapter: 'chapter', chapters: 'chapters', noBooks: 'No books yet',
    createBook: 'Create a book to start building your shelf.', reading: 'Reading', back: 'Back to books',
    editBook: 'Edit book', deleteBook: 'Delete book', theme: 'Theme', light: 'Light', dark: 'Dark', progress: 'Progress',
    contents: 'Contents', search: 'Search chapters', searchBook: 'Search this book', chaptersTitle: 'Chapters',
    select: 'Select', exitSelect: 'Done', selectAll: 'Select all', clearSelection: 'Clear', selected: 'selected', batchAction: 'Batch action', batchToolbar: 'Batch chapter actions',
    refreshSelected: 'Refresh selected', deleteSelected: 'Delete selected', apply: 'Apply', cancel: 'Cancel',
    confirmBatchDelete: 'Delete the selected chapters? Only archived copies will be removed.',
    confirmBatchRefresh: 'Refresh the selected chapters from their source files?', confirmRefreshChapter: 'Refresh this chapter from its source file?',
    batchProgress: 'Processing…', batchDone: (ok, fail) => `${ok} succeeded, ${fail} failed`,
    previous: 'Previous', next: 'Next', noChapters: 'No chapters', addChapter: 'Add a document to this book to start reading.',
    language: 'Language', english: 'English', chinese: '简体中文',
    opening: 'Opening book', loadingLibrary: 'Loading library', unableCreate: 'Unable to create this book', unableEdit: 'Unable to edit this book', unableDeleteBook: 'Unable to delete this book', unableOpen: 'Unable to open this book', unableLoad: 'Unable to load the library', unableRename: 'Unable to rename this chapter', unableRefresh: 'Unable to refresh this chapter', unableOrder: 'Unable to save chapter order', unableMove: 'Unable to move this chapter',
    titlePrompt: 'Book title', descriptionPrompt: 'Description (optional)', chapterTitlePrompt: 'Chapter title',
    searchResults: 'Search results', searching: 'Searching…', noMatches: 'No matches', titleMatch: 'Title match', loadMore: 'Load more', tryAgain: 'Try again', loading: 'Loading…', complete: 'complete', requestFailed: 'Request failed.', invalidSearchResponse: 'Search returned an invalid response.', sourceChanged: 'Source file changed', moveUp: 'Move chapter up', moveDown: 'Move chapter down', renameChapter: 'Rename chapter', refreshChapter: 'Refresh chapter', deleteChapter: 'Delete chapter', unableSaveTheme: 'Unable to save theme', unableSelect: 'Unable to select this chapter', unableDelete: 'Unable to delete this chapter', chapterPositionSaveFailed: 'Chapter deleted, but the new reading position could not be saved', batchItemFailed: 'Request failed.',
    confirmDeleteBook: (title) => `Delete “${title}” and its archived chapters?`, confirmDeleteChapter: (title) => `Delete chapter “${title}”?\n\nOnly the archived copy will be removed. The original source file will stay on disk.`,
    searchMore: (count) => `Showing ${count} results. More matches available.`, searchAll: (count) => `All ${count} results shown.`,
  },
  'zh-CN': {
    shelves: '书架', appName: '书籍', newBook: '新建书籍', book: '本书', books: '本书',
    noDescription: '暂无描述', chapter: '章节', chapters: '章节', noBooks: '暂无书籍',
    createBook: '创建一本书，开始构建你的书架。', reading: '阅读中', back: '返回书架',
    editBook: '编辑书籍', deleteBook: '删除书籍', theme: '主题', light: '浅色', dark: '深色', progress: '进度',
    contents: '目录', search: '搜索章节', searchBook: '搜索本书', chaptersTitle: '章节',
    select: '选择', exitSelect: '完成', selectAll: '全选', clearSelection: '清空', selected: '已选', batchAction: '批量操作', batchToolbar: '批量章节操作',
    refreshSelected: '刷新所选', deleteSelected: '删除所选', apply: '执行', cancel: '取消',
    confirmBatchDelete: '删除所选章节？仅会删除归档副本。',
    confirmBatchRefresh: '从源文件刷新所选章节？', confirmRefreshChapter: '从源文件刷新此章节？',
    batchProgress: '处理中…', batchDone: (ok, fail) => `成功 ${ok} 项，失败 ${fail} 项`,
    previous: '上一章', next: '下一章', noChapters: '暂无章节', addChapter: '向本书添加文档后即可开始阅读。',
    language: '语言', english: 'English', chinese: '简体中文',
    opening: '正在打开书籍', loadingLibrary: '正在加载书架', unableCreate: '无法创建书籍', unableEdit: '无法编辑书籍', unableDeleteBook: '无法删除书籍', unableOpen: '无法打开书籍', unableLoad: '无法加载书架', unableRename: '无法重命名章节', unableRefresh: '无法刷新章节', unableOrder: '无法保存章节顺序', unableMove: '无法移动章节',
    titlePrompt: '书名', descriptionPrompt: '描述（可选）', chapterTitlePrompt: '章节标题',
    searchResults: '搜索结果', searching: '搜索中…', noMatches: '没有匹配项', titleMatch: '标题匹配', loadMore: '加载更多', tryAgain: '重试', loading: '加载中…', complete: '已完成', requestFailed: '请求失败。', invalidSearchResponse: '搜索返回了无效结果。', sourceChanged: '源文件已更改', moveUp: '上移章节', moveDown: '下移章节', renameChapter: '重命名章节', refreshChapter: '刷新章节', deleteChapter: '删除章节', unableSaveTheme: '无法保存主题', unableSelect: '无法选择此章节', unableDelete: '无法删除此章节', chapterPositionSaveFailed: '章节已删除，但无法保存新的阅读位置', batchItemFailed: '请求失败。',
    confirmDeleteBook: (title) => `删除“${title}”及其归档章节？`, confirmDeleteChapter: (title) => `删除章节“${title}”？\n\n仅会删除归档副本，原始源文件将保留。`,
    searchMore: (count) => `显示 ${count} 条结果，还有更多结果。`, searchAll: (count) => `已显示全部 ${count} 条结果。`,
  },
};
function t(key, ...args) { const value = LOCALES[state.locale][key] ?? LOCALES.en[key] ?? key; return typeof value === 'function' ? value(...args) : value; }
function setLocale(locale) {
  state.locale = locale === 'zh-CN' ? 'zh-CN' : 'en';
  try { window.localStorage?.setItem('book.locale', state.locale); } catch (_) { /* storage may be unavailable */ }
  document.documentElement.lang = state.locale;
  if (state.book) { const current = state.currentDocumentId; renderReader(); if (current) selectDocument(current, false); }
  else renderLibrary(state.books);
}
function languagePicker() {
  return `<label class="language-picker"><span>${t('language')}</span><select id="locale" aria-label="${t('language')}"><option value="en"${state.locale === 'en' ? ' selected' : ''}>${t('english')}</option><option value="zh-CN"${state.locale === 'zh-CN' ? ' selected' : ''}>${t('chinese')}</option></select></label>`;
}

function renderBatchFeedback() {
  const node = app.querySelector('#batch-feedback');
  if (!node) return;
  const feedback = state.batchFeedback;
  node.hidden = !feedback;
  node.classList.toggle('batch-error', Boolean(feedback?.error || feedback?.failed?.length));
  node.replaceChildren();
  if (!feedback) return;
  const summary = document.createElement('strong');
  summary.textContent = feedback.error || t('batchDone', feedback.succeeded?.length || 0, feedback.failed?.length || 0);
  node.append(summary);
  if (feedback.failed?.length) {
    const details = document.createElement('ul');
    feedback.failed.forEach((item) => {
      const detail = document.createElement('li');
      detail.textContent = `${item.id}: ${item.error || t('batchItemFailed')}`;
      details.append(detail);
    });
    node.append(details);
  }
}

function cancelProgressSave() {
  window.clearTimeout(state.progressTimer);
  state.progressTimer = null;
  state.pendingProgress = null;
  state.progressGeneration += 1;
}

function flushProgressSave() {
  window.clearTimeout(state.progressTimer);
  state.progressTimer = null;
  const pending = state.pendingProgress;
  state.pendingProgress = null;
  return pending ? saveProgress(pending.bookId, pending.documentId, pending.ratio) : Promise.resolve();
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
  if (!response.ok) throw new Error(payload.error || t('requestFailed'));
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
  const statusClass = title.startsWith('Unable') || title.startsWith('无法') ? ' status-error' : '';
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
  state.selectMode = false;
  state.selectedDocumentIds.clear();
  state.batchFeedback = null;
  state.books = Array.isArray(books) ? books : [];
  const bookLabel = books.length === 1 ? t('book') : t('books');
  app.innerHTML = `
    <main class="library">
      <header class="library-header">
        <div class="library-heading"><span class="library-kicker">${t('shelves')}</span><h1>${t('appName')}</h1></div>
        <div class="library-header-actions">${languagePicker()}<button id="add-book" class="primary-button" type="button">${t('newBook')}</button><div class="book-count"><strong>${books.length}</strong><span>${bookLabel}</span></div></div>
      </header>
      ${books.length ? `<section class="book-list" aria-label="${t('books')}">${books.map((book, index) => `
        <button class="book-row" type="button" data-book-id="${book.id}">
          <span class="book-index" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span>
          <span class="book-copy"><span class="book-title">${escapeHtml(book.title)}</span>${book.description ? `<span class="book-description">${escapeHtml(book.description)}</span>` : `<span class="book-description book-description-empty">${t('noDescription')}</span>`}</span>
          <span class="book-documents"><strong>${book.document_count}</strong><span>${book.document_count === 1 ? t('chapter') : t('chapters')}</span></span>
          <span class="book-arrow" aria-hidden="true">&rarr;</span>
        </button>`).join('')}</section>` : `<section class="empty"><strong>${t('noBooks')}</strong><span>${t('createBook')}</span></section>`}
      </main>`;
  app.querySelector('#locale')?.addEventListener('change', (event) => setLocale(event.target.value));
  app.querySelectorAll('[data-book-id]').forEach((button) => {
    button.addEventListener('click', () => loadBook(Number(button.dataset.bookId)));
  });
  setLocation(null, null, true);
  app.querySelector('#add-book')?.addEventListener('click', createBook);
}

async function createBook() {
  const title = window.prompt(t('titlePrompt'));
  if (!title?.trim()) return;
  const description = window.prompt(t('descriptionPrompt'), '') || '';
  try {
    const book = await request('/api/books', { method: 'POST', body: JSON.stringify({ title: title.trim(), description }) });
    await loadBook(book.id);
  } catch (error) {
    renderStatus(t('unableCreate'), error.message);
  }
}

function renderReader() {
  const book = state.book;
  const documents = book.documents;
  const chapterLabel = documents.length === 1 ? t('chapter') : t('chapters');
  app.innerHTML = `
    <div class="reader" data-theme="${book.theme}">
      <header class="reader-header">
        <button id="back" class="icon-button" type="button" title="${t('back')}" aria-label="${t('back')}">&larr;</button>
        <div class="reader-title-group"><span class="reader-kicker">${t('reading')}</span><h1>${escapeHtml(book.title)}</h1><p class="subtitle">${escapeHtml(book.description || `${documents.length} ${chapterLabel}`)}</p></div>
        <div class="reader-actions"><button id="edit-book" class="icon-button" type="button" title="${t('editBook')}" aria-label="${t('editBook')}">✎</button><button id="delete-book" class="icon-button" type="button" title="${t('deleteBook')}" aria-label="${t('deleteBook')}">×</button></div>
        ${languagePicker()}<label class="theme-picker"><span>${t('theme')}</span><select id="theme" aria-label="${t('theme')}"><option value="light">${t('light')}</option><option value="dark">${t('dark')}</option></select></label>
        <div class="progress-wrap" aria-label="${t('progress')}"><div class="progress-copy"><span>${t('progress')}</span><strong id="progress-label">0%</strong></div><div class="progress-track" aria-hidden="true"><span id="progress-bar"></span></div></div>
      </header>
      <aside class="toc">
        <div class="toc-heading"><div><span class="toc-kicker">${t('contents')}</span><h2>${t('chaptersTitle')}</h2></div><div class="toc-heading-actions"><span class="toc-count">${documents.length}</span><button id="toggle-select" class="select-toggle" type="button">${state.selectMode ? t('exitSelect') : t('select')}</button></div></div>
        ${state.selectMode ? `<div class="batch-toolbar" role="toolbar" aria-label="${t('batchToolbar')}"><label class="batch-check"><input id="select-all" type="checkbox"><span>${t('selectAll')}</span></label><button id="clear-selection" class="secondary-button" type="button">${t('clearSelection')}</button><span id="selection-count" aria-live="polite">0 ${t('selected')}</span><select id="batch-action" aria-label="${t('batchAction')}"><option value="refresh">${t('refreshSelected')}</option><option value="delete">${t('deleteSelected')}</option></select><button id="batch-apply" class="primary-button" type="button" disabled>${state.batchBusy ? t('batchProgress') : t('apply')}</button><button id="batch-cancel" class="secondary-button" type="button">${t('cancel')}</button></div>` : ''}
        <div id="batch-feedback" class="batch-feedback" role="status" aria-live="polite" hidden></div>
        <form id="search-form" class="search-form"><label class="sr-only" for="search-input">${t('searchBook')}</label><input id="search-input" autocomplete="off" placeholder="${t('search')}"><button title="${t('search')}" aria-label="${t('search')}" type="submit">&#8981;</button></form>
        <div id="search-results" class="search-results" role="region" aria-label="${t('searchResults')}" hidden></div>
        <ol id="toc-list" class="toc-list">${documents.map((document) => chapterItem(document)).join('')}</ol>
      </aside>
      <main class="reading-area">${documents.length ? `<iframe id="reader-frame" class="reader-frame" title="${t('reading')}" sandbox="allow-same-origin allow-popups"></iframe><nav class="chapter-nav" aria-label="${t('chaptersTitle')}"><button id="previous" type="button"><span aria-hidden="true">&larr;</span> ${t('previous')}</button><span id="chapter-position" class="chapter-position" aria-live="polite"></span><button id="next" type="button">${t('next')} <span aria-hidden="true">&rarr;</span></button></nav>` : `<div class="reader-empty"><strong>${t('noChapters')}</strong><span>${t('addChapter')}</span></div>`}</main>
    </div>`;
  const theme = app.querySelector('#theme');
  app.querySelector('#locale')?.addEventListener('change', (event) => setLocale(event.target.value));
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
      showReaderError(`${t('unableSaveTheme')}: ${error.message}`);
    }
  });
  app.querySelector('#back').addEventListener('click', showLibrary);
  app.querySelector('#edit-book').addEventListener('click', editBook);
  app.querySelector('#delete-book').addEventListener('click', deleteBook);
  bindSearch();
  bindChapters();
  bindBatchControls();
  renderBatchFeedback();
  updateBookProgress();
}

async function editBook() {
  if (!state.book) return;
  const title = window.prompt(t('titlePrompt'), state.book.title);
  if (!title?.trim()) return;
  const description = window.prompt(t('descriptionPrompt'), state.book.description || '');
  if (description === null) return;
  try {
    state.book = await request(`/api/books/${state.book.id}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim(), description }) });
    renderReader();
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
  } catch (error) {
    renderStatus(t('unableEdit'), error.message);
  }
}

async function deleteBook() {
  if (!state.book || !window.confirm(t('confirmDeleteBook', state.book.title))) return;
  try {
    await flushProgressSave();
    await request(`/api/books/${state.book.id}?with_documents=true`, { method: 'DELETE' });
    await showLibrary();
  } catch (error) {
    renderStatus(t('unableDeleteBook'), error.message);
  }
}

function chapterItem(document) {
  const selected = document.id === state.currentDocumentId ? ' selected' : '';
  const progress = Math.round(Math.max(0, Math.min(1, Number(document.scroll_ratio || 0))) * 100);
  const first = document.position <= 1 ? ' disabled' : '';
  const last = document.position >= state.book.documents.length ? ' disabled' : '';
  const stale = document.source_stale ? ` <span class="toc-stale" title="${t('sourceChanged')}">●</span>` : '';
  return `<li class="toc-item${selected}" draggable="${!state.selectMode}" data-document-id="${document.id}">
    ${state.selectMode ? `<label class="chapter-check"><input type="checkbox" data-select-document="${document.id}"${state.selectedDocumentIds.has(document.id) ? ' checked' : ''} aria-label="${t('select')} ${escapeHtml(document.title)}"></label>` : ''}<button class="toc-open" type="button"${document.id === state.currentDocumentId ? ' aria-current="page"' : ''}><span class="toc-position">${String(document.position).padStart(2, '0')}</span><span class="toc-title">${escapeHtml(document.title)}${stale}</span><span class="toc-progress" aria-label="${progress}% ${t('complete')}"><span style="width: ${progress}%"></span></span></button>
    <span class="move-controls"${state.selectMode ? ' hidden' : ''}><button class="move-button" type="button" data-move="-1" title="${t('moveUp')}" aria-label="${t('moveUp')}"${first}>&#8593;</button><button class="move-button" type="button" data-move="1" title="${t('moveDown')}" aria-label="${t('moveDown')}"${last}>&#8595;</button><button class="move-button" type="button" data-rename title="${t('renameChapter')}" aria-label="${t('renameChapter')}">✎</button><button class="move-button" type="button" data-refresh title="${t('refreshChapter')}" aria-label="${t('refreshChapter')}">↻</button><button class="move-button danger-button" type="button" data-delete title="${t('deleteChapter')}" aria-label="${t('deleteChapter')}">&times;</button></span>
  </li>`;
}

function bindChapters() {
  const list = app.querySelector('#toc-list');
  if (!list) return;
  list.querySelectorAll('.toc-item').forEach((item) => {
    const documentId = Number(item.dataset.documentId);
    item.querySelector('.toc-open').addEventListener('click', () => selectDocument(documentId));
    item.querySelector('[data-select-document]')?.addEventListener('change', (event) => {
      if (event.target.checked) state.selectedDocumentIds.add(documentId); else state.selectedDocumentIds.delete(documentId);
      updateBatchControls();
    });
    item.querySelectorAll('[data-move]').forEach((button) => button.addEventListener('click', () => moveChapter(documentId, Number(button.dataset.move))));
    item.querySelector('[data-rename]')?.addEventListener('click', () => renameChapter(documentId));
    item.querySelector('[data-refresh]')?.addEventListener('click', () => refreshChapter(documentId));
    item.querySelector('[data-delete]')?.addEventListener('click', () => deleteChapter(documentId));
    item.addEventListener('dragstart', () => { state.dragDocumentId = documentId; item.classList.add('dragging'); });
    item.addEventListener('dragend', () => { state.dragDocumentId = null; item.classList.remove('dragging'); });
    item.addEventListener('dragover', (event) => event.preventDefault());
    item.addEventListener('drop', async (event) => {
      event.preventDefault();
      if (!state.dragDocumentId || state.dragDocumentId === documentId) return;
      const dragged = list.querySelector(`[data-document-id="${state.dragDocumentId}"]`);
      if (!dragged) return;
      const items = [...list.children];
      if (items.indexOf(dragged) < items.indexOf(item)) item.after(dragged);
      else item.before(dragged);
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
  const title = window.prompt(t('chapterTitlePrompt'), document.title);
  if (!title?.trim()) return;
  try {
    await request(`/api/documents/${documentId}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) });
    await loadBook(state.book.id, state.currentDocumentId);
  } catch (error) {
    renderStatus(t('unableRename'), error.message);
  }
}

async function refreshChapter(documentId) {
  if (!window.confirm(t('confirmRefreshChapter'))) return;
  try {
    await request(`/api/documents/${documentId}/refresh`, { method: 'POST', body: JSON.stringify({}) });
    await loadBook(state.book.id, documentId);
  } catch (error) {
    renderStatus(t('unableRefresh'), error.message);
  }
}

async function deleteChapter(documentId) {
  const book = state.book;
  const index = book?.documents.findIndex((item) => item.id === documentId) ?? -1;
  const document = index >= 0 ? book.documents[index] : null;
  if (!book || !document || state.deletingDocumentIds.has(documentId) || !window.confirm(t('confirmDeleteChapter', document.title))) return;

  const deletingCurrent = documentId === state.currentDocumentId;
  const replacementId = deletingCurrent
    ? (book.documents[index + 1] || book.documents[index - 1])?.id || null
    : state.currentDocumentId;
  const deleteButton = app.querySelector(`.toc-item[data-document-id="${documentId}"] [data-delete]`);
  state.deletingDocumentIds.add(documentId);
  if (deleteButton) deleteButton.disabled = true;

  try {
    await flushProgressSave();
    if (deletingCurrent) cancelProgressSave();
    await request(`/api/documents/${documentId}`, { method: 'DELETE' });
    await loadBook(book.id, replacementId);
    if (deletingCurrent && replacementId && state.book?.id === book.id && state.currentDocumentId === replacementId) {
      try {
        await persistReaderState(book.id, replacementId, state.book.theme);
      } catch (error) {
        showReaderError(`${t('chapterPositionSaveFailed')}: ${error.message}`);
      }
    }
  } catch (error) {
    showReaderError(`${t('unableDelete')}: ${error.message}`);
  } finally {
    state.deletingDocumentIds.delete(documentId);
    const currentButton = app.querySelector(`.toc-item[data-document-id="${documentId}"] [data-delete]`);
    if (currentButton) currentButton.disabled = false;
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
    renderStatus(t('unableOrder'), error.message);
    await loadBook(state.book.id, state.currentDocumentId);
  }
}

function updateBatchControls() {
  const count = state.selectedDocumentIds.size;
  const countNode = app.querySelector('#selection-count');
  if (countNode) countNode.textContent = `${count} ${t('selected')}`;
  const apply = app.querySelector('#batch-apply');
  if (apply) apply.disabled = !count || state.batchBusy;
  const all = app.querySelector('#select-all');
  const total = state.book?.documents.length || 0;
  if (all) { all.checked = total > 0 && count === total; all.indeterminate = count > 0 && count < total; }
}

function bindBatchControls() {
  app.querySelector('#toggle-select')?.addEventListener('click', () => {
    state.selectMode = !state.selectMode;
    if (!state.selectMode) state.selectedDocumentIds.clear();
    renderReader();
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
  });
  app.querySelector('#batch-cancel')?.addEventListener('click', () => {
    state.selectMode = false;
    state.selectedDocumentIds.clear();
    renderReader();
    if (state.currentDocumentId) selectDocument(state.currentDocumentId, false);
  });
  app.querySelector('#select-all')?.addEventListener('change', (event) => {
    if (event.target.checked) state.book.documents.forEach((doc) => state.selectedDocumentIds.add(doc.id));
    else state.selectedDocumentIds.clear();
    app.querySelectorAll('[data-select-document]').forEach((input) => { input.checked = event.target.checked; });
    updateBatchControls();
  });
  app.querySelector('#clear-selection')?.addEventListener('click', () => {
    state.selectedDocumentIds.clear();
    app.querySelectorAll('[data-select-document]').forEach((input) => { input.checked = false; });
    updateBatchControls();
  });
  app.querySelector('#batch-apply')?.addEventListener('click', executeBatch);
  updateBatchControls();
}

async function executeBatch() {
  if (state.batchBusy || !state.book || !state.selectedDocumentIds.size) return;
  const bookId = state.book.id;
  const action = app.querySelector('#batch-action')?.value || 'refresh';
  if (!window.confirm(action === 'delete' ? t('confirmBatchDelete') : t('confirmBatchRefresh'))) return;
  state.batchBusy = true;
  state.batchFeedback = null;
  renderBatchFeedback();
  const apply = app.querySelector('#batch-apply');
  if (apply) { apply.disabled = true; apply.textContent = t('batchProgress'); }
  try {
    await flushProgressSave();
    const ids = [...state.selectedDocumentIds];
    const result = await request(`/api/books/${bookId}/documents/batch`, { method: 'POST', body: JSON.stringify({ action, document_ids: ids }) });
    const failed = Array.isArray(result.failed) ? result.failed : [];
    const succeeded = Array.isArray(result.succeeded) ? result.succeeded : [];
    const succeededIds = new Set(succeeded.map((item) => Number(item.id)));
    const failedIds = new Set(failed.map((item) => Number(item.id)));
    state.batchFeedback = { succeeded, failed };
    if (failed.length) {
      state.selectedDocumentIds = failedIds;
    } else {
      state.selectedDocumentIds.clear();
      state.selectMode = false;
    }
    const current = state.currentDocumentId;
    const deletedIds = action === 'delete' ? succeededIds : new Set();
    const currentDeleted = deletedIds.has(current);
    let replacement = current;
    if (currentDeleted) {
      const oldIndex = state.book.documents.findIndex((doc) => doc.id === current);
      replacement = null;
      for (let index = oldIndex + 1; index < state.book.documents.length; index += 1) {
        if (!deletedIds.has(state.book.documents[index].id)) {
          replacement = state.book.documents[index].id;
          break;
        }
      }
      if (replacement === null) {
        for (let index = oldIndex - 1; index >= 0; index -= 1) {
          if (!deletedIds.has(state.book.documents[index].id)) {
            replacement = state.book.documents[index].id;
            break;
          }
        }
      }
    }
    await loadBook(bookId, replacement);
    if (failed.length) {
      state.selectedDocumentIds = new Set([...failedIds].filter((id) => state.book?.documents.some((doc) => doc.id === id)));
      state.selectMode = true;
      renderReader();
      if (state.currentDocumentId) await selectDocument(state.currentDocumentId, false);
    }
    if (action === 'delete' && currentDeleted && state.book?.id === bookId && state.currentDocumentId === replacement) {
      try {
        await persistReaderState(bookId, replacement, state.book.theme);
      } catch (error) {
        showReaderError(`${t('chapterPositionSaveFailed')}: ${error.message}`);
      }
    }
  } catch (error) {
    state.batchFeedback = { error: error.message || t('requestFailed'), succeeded: [], failed: [] };
    renderBatchFeedback();
  } finally {
    state.batchBusy = false;
    const finishedApply = app.querySelector('#batch-apply');
    if (finishedApply) finishedApply.textContent = t('apply');
    updateBatchControls();
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
    renderStatus(t('unableMove'), error.message);
    await loadBook(state.book.id, state.currentDocumentId);
  }
}

function bindSearch() {
  const form = app.querySelector('#search-form');
  const input = app.querySelector('#search-input');
  const results = app.querySelector('#search-results');
  let currentSearch = null;

  const bindResultActions = () => {
    results.querySelectorAll('[data-document-id]').forEach((button) => button.addEventListener('click', () => {
      currentSearch = null;
      results.hidden = true;
      results.setAttribute('aria-busy', 'false');
      selectDocument(Number(button.dataset.documentId));
    }));
    results.querySelector('[data-search-more]')?.addEventListener('click', () => loadNextPage(currentSearch));
  };

  const renderSearch = (search) => {
    if (currentSearch !== search) return;
    const previousScrollTop = results.querySelector('#search-items')?.scrollTop || 0;
    results.setAttribute('aria-busy', String(search.loading));
    if (!search.matches.length) {
      if (search.loading) {
        results.innerHTML = `<div class="search-feedback" role="status" aria-live="polite" tabindex="-1">${t('searching')}</div>`;
      } else if (search.error) {
        results.innerHTML = `<div class="search-feedback search-error" role="alert" tabindex="-1">${escapeHtml(search.error)}</div><div class="search-more-row"><button class="search-more" type="button" data-search-more>${t('tryAgain')}</button></div>`;
      } else {
        results.innerHTML = `<div class="search-feedback" role="status" tabindex="-1">${t('noMatches')}</div>`;
      }
      results.hidden = false;
      bindResultActions();
      return;
    }

    const summary = search.hasMore ? t('searchMore', search.matches.length) : t('searchAll', search.matches.length);
    const items = search.matches.map((match) => `<button class="search-result" type="button" data-document-id="${match.id}"><strong>${escapeHtml(match.title)}</strong><span>${escapeHtml(match.snippet || t('titleMatch'))}</span></button>`).join('');
    const feedback = search.error ? `<div class="search-feedback search-error" role="alert">${escapeHtml(search.error)}</div>` : '';
    const more = search.hasMore || search.error
      ? `<div class="search-more-row"><button class="search-more" type="button" data-search-more aria-controls="search-items" aria-describedby="search-summary" aria-disabled="${search.loading}">${search.loading ? t('loading') : (search.error ? t('tryAgain') : t('loadMore'))}</button></div>`
      : '';
    results.innerHTML = `<div id="search-summary" class="search-summary" role="status" aria-live="polite" tabindex="-1">${summary}</div><div id="search-items" class="search-items">${items}</div>${feedback}${more}`;
    results.querySelector('#search-items').scrollTop = previousScrollTop;
    results.hidden = false;
    bindResultActions();
  };

  const loadNextPage = async (search) => {
    if (!search || currentSearch !== search || search.loading) return;
    const previousCount = search.matches.length;
    const retryingFirstPage = previousCount === 0 && Boolean(search.error);
    search.loading = true;
    search.error = '';
    renderSearch(search);
    if (previousCount) results.querySelector('[data-search-more]')?.focus({ preventScroll: true });
    else if (retryingFirstPage) results.querySelector('[role="status"]')?.focus();
    try {
      const page = await request(`/api/search?q=${encodeURIComponent(search.query)}&book=${state.book.id}&limit=${SEARCH_PAGE_SIZE + 1}&offset=${search.nextOffset}`);
      if (currentSearch !== search) return;
      if (!Array.isArray(page)) throw new Error(t('invalidSearchResponse'));
      const visiblePage = page.slice(0, SEARCH_PAGE_SIZE);
      search.matches.push(...visiblePage);
      search.nextOffset += visiblePage.length;
      search.hasMore = page.length > SEARCH_PAGE_SIZE;
    } catch (error) {
      if (currentSearch === search) search.error = error.message;
    } finally {
      if (currentSearch === search) {
        search.loading = false;
        renderSearch(search);
        if (previousCount) {
          const nextControl = results.querySelector('[data-search-more]');
          const firstNewResult = results.querySelectorAll('[data-document-id]')[previousCount];
          if (nextControl) nextControl.focus({ preventScroll: true });
          else (firstNewResult || results.querySelector('#search-summary'))?.focus();
        } else if (retryingFirstPage) {
          (results.querySelector('[data-search-more]') || results.querySelector('[data-document-id]') || results.querySelector('[role="status"], [role="alert"]'))?.focus();
        }
      }
    }
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) {
      currentSearch = null;
      results.hidden = true;
      results.innerHTML = '';
      results.setAttribute('aria-busy', 'false');
      return;
    }
    if (currentSearch?.query === value && currentSearch.loading && currentSearch.nextOffset === 0) return;
    currentSearch = { query: value, matches: [], nextOffset: 0, hasMore: false, loading: false, error: '' };
    loadNextPage(currentSearch);
  });
  input.addEventListener('input', () => {
    if (currentSearch && input.value.trim() !== currentSearch.query) {
      currentSearch = null;
      results.hidden = true;
      results.innerHTML = '';
      results.setAttribute('aria-busy', 'false');
    }
  });
}

async function selectDocument(documentId, saveState = true) {
  const document = state.book.documents.find((item) => item.id === documentId);
  if (!document) return;
  await flushProgressSave();
  cancelProgressSave();
  const selectionGeneration = state.progressGeneration;
  const frame = app.querySelector('#reader-frame');
  if (!frame) return;
  if (saveState) {
    try {
      await persistReaderState(state.book.id, documentId, state.book.theme);
    } catch (error) {
      if (selectionGeneration === state.progressGeneration) {
        showReaderError(`${t('unableSelect')}: ${error.message}`);
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
      state.pendingProgress = { bookId, documentId: document.id, ratio };
      const generation = state.progressGeneration;
      state.progressTimer = window.setTimeout(() => {
        if (generation === state.progressGeneration && state.currentDocumentId === document.id) {
          const pending = state.pendingProgress;
          state.progressTimer = null;
          state.pendingProgress = null;
          if (pending) saveProgress(pending.bookId, pending.documentId, pending.ratio);
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
  if (tocProgress) tocProgress.setAttribute('aria-label', `${Math.round(bounded * 100)}% ${t('complete')}`);
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
  const write = request(`/api/documents/${documentId}/progress`, { method: 'PUT', body: JSON.stringify({ scroll_ratio: ratio }) }).catch(() => {});
  const document = state.book?.id === bookId
    ? state.book.documents.find((item) => item.id === documentId)
    : null;
  if (document) document.scroll_ratio = ratio;
  if (state.book?.documents.length) {
    state.book.progress = state.book.documents.reduce((sum, item) => sum + Number(item.scroll_ratio || 0), 0) / state.book.documents.length;
    updateBookProgress();
  }
  return write;
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
  const generation = ++state.viewGeneration;
  const switchingBook = state.book?.id !== bookId;
  if (switchingBook) {
    state.selectMode = false;
    state.selectedDocumentIds.clear();
    state.batchFeedback = null;
  }
  await flushProgressSave();
  cancelProgressSave();
  if (generation !== state.viewGeneration) return;
  renderStatus(t('opening'));
  try {
    const book = await request(`/api/books/${bookId}`);
    if (generation !== state.viewGeneration) return;
    state.book = book;
    const validRequested = state.book.documents.some((document) => document.id === requestedDocumentId);
    const validLast = state.book.documents.some((document) => document.id === state.book.last_document_id);
    state.currentDocumentId = validRequested ? requestedDocumentId : (validLast ? state.book.last_document_id : state.book.documents[0]?.id || null);
    renderReader();
    if (state.currentDocumentId) await selectDocument(state.currentDocumentId, false);
    else setLocation(state.book.id, null, true);
  } catch (error) {
    if (generation === state.viewGeneration) renderStatus(t('unableOpen'), error.message);
  }
}

async function showLibrary() {
  const generation = ++state.viewGeneration;
  await flushProgressSave();
  cancelProgressSave();
  if (generation !== state.viewGeneration) return;
  renderStatus(t('loadingLibrary'));
  try {
    const books = await request('/api/books');
    if (generation !== state.viewGeneration) return;
    renderLibrary(books);
  } catch (error) {
    if (generation === state.viewGeneration) renderStatus(t('unableLoad'), error.message);
  }
}

async function boot() {
  try {
    document.documentElement.lang = state.locale;
    const route = initialRoute();
    if (route.bookId) await loadBook(route.bookId, route.documentId);
    else await showLibrary();
  } catch (error) {
    renderStatus(t('unableLoad'), error.message);
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
