let quotes = {};
const $ = (id) => document.getElementById(id),
  token = document.querySelector('meta[name="blynger-token"]').content;
let page = null,
  pages = [],
  dirty = false,
  mode = 'visual',
  selection = null,
  generated = [],
  publicationReady = false,
  siteOrigin = '',
  editRevision = 0,
  refreshRevision = 0,
  readerLoadRevision = 0,
  currentWorkspace = 'openers',
  postSort = 'updated';
const saveQueue = new BlyngerEditorSafety.SerialQueue(),
  pageRequests = new BlyngerEditorSafety.LatestRequest();
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
async function api(path, data) {
  const r = await fetch('/api/' + path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Blynger-Token': token },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const d = await r.json();
  if (!r.ok) {
    const e = Error(d.error || 'Something went wrong.');
    Object.assign(e, d);
    throw e;
  }
  return d;
}
function status(s) {
  $('status').textContent = s;
}
function modal(title, body) {
  $('dialogTitle').textContent = title;
  $('dialogBody').innerHTML = body;
  if (!$('dialog').open) $('dialog').showModal();
}
function error(e) {
  status(e.message);
  if (e.code === 'fragment-file-conflict') {
    const names = (e.files || []).join(', '),
      explanation = e.can_accept
        ? 'Blynger checked that the writing, links, and fragment boundaries are unchanged. The current ' +
          (e.files.length === 1 ? 'file differs' : 'files differ') +
          ' only in surrounding details that are safe to leave as they are.'
        : 'The writing or links changed too, so Blynger cannot safely move the private fragment identities automatically.';
    modal(
      'Blynger — File changes found',
      '<div class="notice ' +
        (e.can_accept ? '' : 'error') +
        '"><b>' +
        esc(names) +
        '</b><br>' +
        esc(explanation) +
        '</div><div class="dialog-actions"><button id="cancelFileChanges">Keep reviewing</button>' +
        (e.can_accept
          ? '<button id="acceptFileChanges">Use ' +
            (e.files.length === 1 ? 'file' : 'files') +
            ' as ' +
            (e.files.length === 1 ? 'it is' : 'they are') +
            '</button>'
          : '') +
        '</div>',
    );
    $('cancelFileChanges').onclick = () => $('dialog').close();
    if (e.can_accept)
      $('acceptFileChanges').onclick = () =>
        run(async () => {
          const b = $('acceptFileChanges');
          b.disabled = true;
          b.textContent = 'Saving…';
          const result = await api('accept-file-changes', { files: e.files });
          $('dialog').close();
          status(result.message + ' Continuing review…');
          $('publish').click();
        });
    return;
  }
  const fragmentProblem =
      e.code === 'fragment-state' ||
      /fragment (?:anchors|boundar|break|ranges?)/i.test(e.message),
    affected = e.page || page?.name,
    samePage = affected === page?.name,
    canClear = fragmentProblem && samePage && page?.kind === 'post';
  const explanation = !fragmentProblem
    ? ''
    : samePage
      ? 'Your writing and ordinary formatting will be kept. This removes every reusable fragment boundary from this draft so you can save now and add fragments again later.'
      : 'The fragment problem belongs to ' +
        affected +
        ', not the page currently open. Open that page to review its boundaries; this draft is not the cause.';
  modal(
    'Blynger — Something needs attention',
    '<div class="notice error">' +
      esc((affected && !samePage ? affected + ': ' : '') + e.message) +
      '</div>' +
      (explanation ? '<p>' + esc(explanation) + '</p>' : '') +
      '<div class="dialog-actions"><button id="dismissError">OK</button>' +
      (fragmentProblem && !samePage
        ? '<button id="openBrokenFragmentPage">Open ' + esc(affected) + '</button>'
        : '') +
      (canClear
        ? '<button id="clearBrokenFragments">Remove all fragments and save draft</button>'
        : '') +
      '</div>',
  );
  $('dismissError').onclick = () => $('dialog').close();
  if (fragmentProblem && !samePage)
    $('openBrokenFragmentPage').onclick = () =>
      run(async () => {
        $('dialog').close();
        await openPage(affected);
      });
  if (canClear)
    $('clearBrokenFragments').onclick = () =>
      run(async () => {
        const b = $('clearBrokenFragments');
        b.disabled = true;
        if (mode === 'source') applySource();
        fragmentEditor.clearAll();
        $('dialog').close();
        await save(false, true);
        status('Draft saved without fragments. Your writing is unchanged.');
      });
}
async function run(fn) {
  try {
    await fn();
  } catch (e) {
    error(e);
  }
}
$('closeDialog').onclick = () => $('dialog').close();
function syncPublishButton() {
  const ready = dirty || publicationReady,
    b = $('publish');
  b.classList.toggle('ready', ready);
  b.disabled = publishing || !ready;
}
async function updatePublicationState() {
  publicationReady = (await api('publication-status')).ready;
  syncPublishButton();
}
function mark() {
  editRevision += 1;
  dirty = true;
  $('saveState').textContent = 'Unsaved changes';
  $('draftBadge').textContent = 'EDITING';
  count();
}
function count() {
  const words = $('editor').innerText.trim().split(/\s+/).filter(Boolean).length;
  $('wordcount').textContent = words.toLocaleString() + ' words';
  syncPublishButton();
}
function localImages(s) {
  if (siteOrigin) s = s.split(siteOrigin + 'blyg/media/').join('/preview/blyg/media/');
  return s.replace(/(src=["'])\/(?!preview\/)/g, '$1/preview/');
}
function publicImages(s) {
  return s.replace(/(src=["'])\/preview\//g, '$1/');
}
function prettySource(s) {
  const held = [];
  s = s.replace(
    /<(pre|code|script|style)\b[\s\S]*?<\/\1>/gi,
    (m) => '___BLYNGER_HELD_' + (held.push(m) - 1) + '___',
  );
  s = s
    .replace(
      /(<\/(?:p|h[1-6]|blockquote|ul|ol|figure|figcaption|table)>)[ \t]*(?=<)/gi,
      '$1\n\n',
    )
    .replace(/\n{3,}/g, '\n\n');
  return s.replace(/___BLYNGER_HELD_(\d+)___/g, (_, i) => held[Number(i)]);
}
const fragmentEditor = new FragmentEditor($('editor'), mark, status);
function raw() {
  if (mode === 'source') return $('source').value;
  return page.prefix + publicImages(fragmentEditor.html()) + page.suffix;
}
function sourceParts(value) {
  for (const tag of ['article', 'body']) {
    const open = new RegExp('<' + tag + '\\b[^>]*>', 'i').exec(value);
    if (!open) continue;
    const start = open.index + open[0].length,
      close = new RegExp('</' + tag + '\\s*>', 'i').exec(value.slice(start));
    if (close)
      return {
        prefix: value.slice(0, start),
        body: value.slice(start, start + close.index),
        suffix: value.slice(start + close.index),
      };
  }
  return { prefix: '', body: value, suffix: '' };
}
function applySource() {
  if (mode !== 'source') return;
  const parts = sourceParts($('source').value);
  page.prefix = parts.prefix;
  page.suffix = parts.suffix;
  fragmentEditor.replace(localImages(parts.body));
  mode = 'visual';
  fragmentEditor.layer.hidden = page.kind !== 'post' && page.name !== 'openers.html';
  $('source').hidden = true;
  $('editor').hidden = false;
  $('visualTab').classList.add('active');
  $('sourceTab').classList.remove('active');
  count();
  status('HTML changes applied to Write. Save or queue the draft when ready.');
}
function capture() {
  const s = window.getSelection();
  if (s.rangeCount && $('editor').contains(s.anchorNode))
    selection = s.getRangeAt(0).cloneRange();
}
function insert(content) {
  if (mode === 'source') {
    const t = $('source');
    t.setRangeText(content, t.selectionStart, t.selectionEnd, 'end');
    mark();
    return;
  }
  $('editor').focus();
  const s = window.getSelection();
  s.removeAllRanges();
  if (selection && $('editor').contains(selection.startContainer)) s.addRange(selection);
  else {
    const r = document.createRange();
    r.selectNodeContents($('editor'));
    r.collapse(false);
    s.addRange(r);
  }
  document.execCommand('insertHTML', false, localImages(content));
  capture();
  mark();
}
function restoreSelection() {
  const s = window.getSelection();
  if (selection && $('editor').contains(selection.startContainer)) {
    s.removeAllRanges();
    s.addRange(selection);
  }
}
function straightQuotes(value) {
  return String(value).replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
}
document.execCommand('defaultParagraphSeparator', false, 'p');
function normalizeParagraphs() {
  for (const div of [...$('editor').children])
    if (div.tagName === 'DIV' && !div.classList.length && !div.id) {
      const p = document.createElement('p');
      p.innerHTML = div.innerHTML;
      div.replaceWith(p);
    }
}
$('editor').addEventListener('beforeinput', (e) => {
  if (
    e.inputType === 'insertText' &&
    /[“”‘’]/.test(e.data || '') &&
    !e.target.closest('blockquote')
  ) {
    e.preventDefault();
    document.execCommand('insertText', false, straightQuotes(e.data));
  }
});
function editorBlock(node) {
  const element = node?.nodeType === 1 ? node : node?.parentElement,
    block = element?.closest?.(
      '#editor > p,#editor > h1,#editor > h2,#editor > h3,#editor > h4,#editor > h5,#editor > h6,#editor > div,#editor > blockquote,#editor > ul,#editor > ol',
    );
  return block && $('editor').contains(block) ? block : null;
}
function selectedEditorBlocks() {
  restoreSelection();
  const s = window.getSelection();
  if (!s.rangeCount) return [];
  const range = s.getRangeAt(0);
  if (range.collapsed) {
    const block = editorBlock(range.startContainer);
    return block ? [block] : [];
  }
  return [...$('editor').children].filter((node) => {
    try {
      return range.intersectsNode(node);
    } catch {
      return false;
    }
  });
}
function updateFormatState() {
  if (mode !== 'visual') return;
  for (const name of ['bold', 'italic']) {
    const b = document.querySelector('[data-format="' + name + '"]'),
      active = document.queryCommandState(name);
    b.classList.toggle('selected', active);
    b.setAttribute('aria-pressed', String(active));
  }
  const centered = !!editorBlock(window.getSelection().anchorNode)?.classList.contains(
    'blynger-centered',
  );
  $('center').classList.toggle('selected', centered);
  $('center').setAttribute('aria-pressed', String(centered));
}
$('editor').addEventListener('input', () => {
  normalizeParagraphs();
  updateFormatState();
  mark();
});
$('source').addEventListener('input', mark);
for (const event of ['keyup', 'mouseup', 'focus'])
  $('editor').addEventListener(event, () => {
    capture();
    updateFormatState();
  });
document.addEventListener('selectionchange', () => {
  if (mode === 'visual' && document.activeElement === $('editor')) updateFormatState();
});
// Paste prose, not arbitrary active HTML from another site.
function imageMarkup(url, alt, size = 'standard') {
  size = /^(standard|small|wide|full)$/.test(size) ? size : 'standard';
  return (
    '<p class="blynger-image blynger-image-' +
    size +
    '"><img src="' +
    esc(url) +
    '" alt="' +
    esc(alt || '') +
    '"></p>'
  );
}
async function imageFileData(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
function pasteQuoteText(block, text) {
  const cite = block.querySelector(':scope > cite.blynger-blockquote-source'),
    parts = text
      .replace(/\r/g, '')
      .split(/\n\s*\n/)
      .map((part) => part.split('\n'));
  const nodes = parts.map((lines) => {
    const p = document.createElement('p');
    lines.forEach((line, i) => {
      if (i) p.append(document.createElement('br'));
      p.append(document.createTextNode(line));
    });
    return p;
  });
  const s = window.getSelection(),
    r = s.rangeCount ? s.getRangeAt(0) : null,
    target =
      r &&
      (r.startContainer.nodeType === 1
        ? r.startContainer
        : r.startContainer.parentElement
      )?.closest('p');
  if (target && target.parentElement === block && r && r.collapsed) {
    const tail = r.cloneRange();
    tail.setEndAfter(target.lastChild || target);
    const after = tail.extractContents();
    target.after(...nodes);
    if (after.textContent || after.querySelector?.('*')) {
      const p = document.createElement('p');
      p.append(after);
      nodes.at(-1).after(p);
    }
    if (!target.textContent && !target.children.length) target.remove();
  } else block.insertBefore(document.createDocumentFragment(), cite);
  if (!(target && target.parentElement === block) && nodes.length)
    block.insertBefore(
      nodes.reduce((f, n) => (f.append(n), f), document.createDocumentFragment()),
      cite,
    );
  s.removeAllRanges();
  const end = document.createRange(),
    last = nodes.at(-1) || block;
  end.selectNodeContents(last);
  end.collapse(false);
  s.addRange(end);
}
$('editor').addEventListener('paste', (e) => {
  e.preventDefault();
  let text = e.clipboardData.getData('text/plain').trim();
  const anchor = window.getSelection().anchorNode,
    block = (anchor?.nodeType === 1 ? anchor : anchor?.parentElement)?.closest?.(
      'blockquote.blynger-citation,blockquote.blyg-transclusion',
    );
  if (/^https?:\/\/\S+\.(?:png|jpe?g|gif|webp|avif)(?:[?#]\S*)?$/i.test(text) && !block) {
    run(async () => {
      const verified = await api('image-url', { url: text });
      const alt = prompt('Image description (optional)') || '';
      const size = (
        prompt('Image size: standard, small, wide, or full', 'standard') || 'standard'
      ).toLowerCase();
      insert(imageMarkup(verified.url, alt, size));
    });
    return;
  }
  if (block) {
    pasteQuoteText(block, text);
  } else document.execCommand('insertText', false, straightQuotes(text));
  normalizeParagraphs();
  capture();
  mark();
});
window.addEventListener('beforeunload', (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});
function shortDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ''
    : date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
}
function renderPages() {
  const q = $('search').value.toLowerCase();
  let shown = pages.filter((p) =>
    currentWorkspace === 'posts'
      ? !p.main && p.kind === 'post' && (postSort === 'deleted' ? p.deleted : !p.deleted)
      : currentWorkspace === 'pages'
        ? p.kind === 'page' || (p.main && p.name !== 'openers.html')
        : false,
  );
  if (currentWorkspace === 'posts')
    shown.sort(
      postSort === 'alpha'
        ? (a, b) => a.title.localeCompare(b.title)
        : (a, b) =>
            String(b[postSort === 'deleted' ? 'updated' : postSort] || '').localeCompare(
              String(a[postSort === 'deleted' ? 'updated' : postSort] || ''),
            ),
    );
  $('pages').replaceChildren();
  for (const p of shown) {
    if (!(p.title + ' ' + p.name).toLowerCase().includes(q)) continue;
    const b = document.createElement('button');
    b.className = 'page-item' + (page && page.name === p.name ? ' active' : '');
    const label = p.main
      ? {
          'index.html': 'Home',
          'portfolio.html': 'Portfolio',
          'privacypolicy.html': 'Privacy policy',
        }[p.name] || p.title
      : p.title;
    const date =
      currentWorkspace === 'posts'
        ? ' · ' +
          (postSort === 'created' ? 'created ' : 'updated ') +
          shortDate(p[postSort === 'deleted' ? 'updated' : postSort])
        : '';
    b.innerHTML =
      '<span class="icon">' +
      (p.main || p.kind === 'page' ? '▣' : '▤') +
      '</span><span class="name">' +
      esc(label) +
      '<small>' +
      esc(p.name) +
      (p.deleted ? ' · deleted' : p.draft ? ' · draft' : '') +
      esc(date) +
      '</small></span>';
    b.onclick = () => run(() => openPage(p.name));
    $('pages').append(b);
  }
  if (!$('pages').children.length)
    $('pages').textContent =
      postSort === 'deleted'
        ? 'No deleted posts.'
        : 'No matching ' + (currentWorkspace === 'posts' ? 'posts.' : 'pages.');
}
async function refresh() {
  const request = ++refreshRevision,
    result = await Promise.all([api('pages'), api('settings'), api('publication-status')]);
  if (request !== refreshRevision) return;
  pages = result[0];
  const s = result[1];
  siteOrigin = s.site;
  publicationReady = result[2].ready;
  renderPages();
  syncPublishButton();
}
function responseLabel(stub) {
  if (!stub) return '';
  if (stub.url) {
    try {
      return 'RESPONSE TO · ' + new URL(stub.url).hostname.replace(/^www\./, '');
    } catch {
      return 'RESPONSE TO · WEB PAGE';
    }
  }
  const cited = stub.cited || {},
    source = cited.source || cited.author || stub.origin;
  return 'RESPONSE TO · ' + source + ' · v' + stub.version;
}
async function openPage(name) {
  if (
    dirty &&
    !confirm('Leave this page and discard unsaved edits? Saved drafts are kept.')
  )
    return false;
  const ticket = pageRequests.begin(editRevision);
  const result = await Promise.all([
    api('page?name=' + encodeURIComponent(name)),
    api('settings'),
  ]);
  if (!pageRequests.accepts(ticket, editRevision)) {
    status('Kept newer edits instead of replacing them with a delayed page load.');
    return false;
  }
  page = result[0];
  const settings = result[1];
  currentWorkspace = workspaceForPage(page);
  showWriting();
  editRevision += 1;
  mode = 'visual';
  dirty = false;
  selection = null;
  generated = page.generated || [];
  quotes = page.quotes || {};
  $('editor').innerHTML = localImages(page.body);
  const fragmentRepair = fragmentEditor.load(page.fragments);
  $('newOpener').hidden = page.name !== 'openers.html';
  $('editHeadline').hidden =
    (page.kind !== 'page' &&
      ['index.html', 'portfolio.html', 'openers.html', 'privacypolicy.html'].includes(
        page.name,
      )) ||
    !!page.deleted;
  $('deletePost').hidden =
    page.kind !== 'post' ||
    ['index.html', 'portfolio.html', 'openers.html', 'privacypolicy.html'].includes(
      page.name,
    );
  $('deletePost').textContent = page.deleted ? 'Restore post…' : 'Delete post…';
  $('editor').contentEditable = page.deleted ? 'false' : 'true';
  for (const id of ['save', 'queue', 'preview', 'images', 'sourceTab'])
    $(id).disabled = !!page.deleted;
  $('tk').disabled = !!page.deleted || page.kind !== 'post';
  for (const id of ['versions', 'mainFragment', 'quote', 'fragment', 'removeFragment'])
    $(id).disabled = !!page.deleted || page.kind !== 'post';
  fragmentEditor.layer.hidden = page.kind !== 'post' && page.name !== 'openers.html';
  $('source').value = page.raw;
  $('sourceFind').hidden = true;
  $('editor').hidden = false;
  $('source').hidden = true;
  $('visualTab').classList.add('active');
  $('sourceTab').classList.remove('active');
  $('heading').textContent = page.title;
  $('filename').textContent = settings.site_label + ' / ' + page.name;
  const marker = $('responseMarker');
  marker.textContent = responseLabel(page.stub_of);
  marker.hidden = !page.stub_of;
  $('pinPlan').hidden = !page.pin_available;
  $('pinOnPublish').checked = !!page.pin_on_publish;
  $('kind').textContent =
    page.name === 'openers.html'
      ? 'OPENERS EDITOR'
      : page.new
        ? page.kind === 'page'
          ? 'NEW PAGE'
          : 'NEW POST'
        : page.kind !== 'post'
          ? 'PAGE EDITOR'
          : 'POST EDITOR';
  if (fragmentRepair) {
    $('draftBadge').textContent = 'EDITING';
    $('saveState').textContent = 'Unsaved repair';
  } else {
    $('draftBadge').textContent = page.draft ? 'DRAFT' : 'LOCAL';
    $('saveState').textContent = page.draft ? 'Saved draft' : 'Ready';
  }
  renderPages();
  count();
  status(
    fragmentRepair
      ? 'Blynger repaired this post and added the missing H2 fragment breaks. Save the draft to keep the repair.'
      : 'Editing ' + page.name + ' — changes stay local.',
  );
  return true;
}
async function saveOnce(clearFragments = false) {
  if (!page) return;
  if (!dirty) {
    status('No unsaved changes.');
    return;
  }
  if (mode === 'source') applySource();
  const target = page,
    name = page.name,
    revision = editRevision,
    payload = {
      name,
      base: page.base,
      raw: raw(),
      generated: structuredClone(generated),
      quotes: structuredClone(quotes),
      fragments: fragmentEditor.snapshot(),
      clear_fragments: clearFragments,
      stub_of: page.stub_of,
      forked_from: page.forked_from,
      pin_on_publish: $('pinOnPublish').checked,
    };
  const result = await api('save', payload);
  if (page !== target || page.name !== name) return result;
  if (editRevision !== revision) {
    status('Draft saved, with newer edits still unsaved.');
    $('saveState').textContent = 'Newer unsaved changes';
    $('draftBadge').textContent = 'EDITING';
    await refresh();
    return result;
  }
  const fresh = await api('page?name=' + encodeURIComponent(name));
  if (page !== target || editRevision !== revision) return result;
  page = fresh;
  dirty = false;
  $('saveState').textContent = 'Draft saved';
  $('draftBadge').textContent = 'DRAFT';
  status(result.message);
  await refresh();
  return result;
}
function save(requireClean = true, clearFragments = false) {
  const operation = saveQueue.enqueue(() => saveOnce(clearFragments));
  return operation.then((result) => {
    if (requireClean && dirty)
      throw Error('Newer edits remain unsaved. Save them before continuing.');
    return result;
  });
}
async function requireSaved() {
  if (dirty) await save();
  if (dirty) throw Error('Newer edits remain unsaved. Save them before continuing.');
}
$('save').onclick = () => run(() => save(false));
$('search').oninput = renderPages;
for (const button of document.querySelectorAll('#postSort button'))
  button.onclick = () => {
    postSort = button.dataset.sort;
    for (const peer of document.querySelectorAll('#postSort button'))
      peer.classList.toggle('active', peer === button);
    renderPages();
  };
$('pinOnPublish').onchange = () => {
  if (page) {
    page.pin_on_publish = $('pinOnPublish').checked;
    mark();
  }
};
$('queue').onclick = () =>
  run(async () => {
    if (!page || readerActive) return;
    const pending = dirty || page.draft;
    await requireSaved();
    if (!pending) {
      status('No changes to queue.');
      return;
    }
    await updatePublicationState();
    status(
      (page.title || page.name) +
        ' is saved for the next publication. You can keep working elsewhere.',
    );
  });
$('new').onclick = () => {
  modal(
    'New post',
    '<label>Post title<input id="newTitle" placeholder="What’s on your mind?"></label><p class="hint">New posts appear at the top of your homepage when you publish.</p><div class="dialog-actions"><button id="createPost">Create draft</button></div>',
  );
  $('newTitle').focus();
  $('createPost').onclick = () =>
    run(async () => {
      if (dirty) await save();
      const p = await api('new', { title: $('newTitle').value });
      $('dialog').close();
      await refresh();
      await openPage(p.name);
    });
};
function pageFilename(title) {
  const stem = title
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  return (stem || 'new-page') + '.html';
}
$('newPage').onclick = () => {
  modal(
    'New page',
    '<label>Page title<input id="newPageTitle" placeholder="Posts, 2015–2017"></label><label>Filename / URL<input id="newPageName" placeholder="2015-2017.html"></label><p class="hint">Creates an ordinary website page. It will not appear in your homepage post list, RSS, or Blyg archive.</p><div class="dialog-actions"><button id="createPage">Create draft</button></div>',
  );
  const title = $('newPageTitle'),
    name = $('newPageName');
  let edited = false;
  title.oninput = () => {
    if (!edited) name.value = pageFilename(title.value);
  };
  name.oninput = () => {
    edited = true;
  };
  title.focus();
  $('createPage').onclick = () =>
    run(async () => {
      if (dirty) await save();
      const p = await api('new-page', { title: title.value, name: name.value });
      $('dialog').close();
      await refresh();
      await openPage(p.name);
    });
};
$('sourceTab').onclick = () => {
  if (!page || mode === 'source') return;
  fragmentEditor.snapshot();
  const at = fragmentEditor.cursor(),
    needle = at
      ? publicImages(at.cloneNode(true).outerHTML).replace(
          / data-fragment-block="[^"]+"/g,
          '',
        )
      : '';
  $('source').value = prettySource(dirty ? raw() : page.raw);
  $('source').readOnly = false;
  mode = 'source';
  fragmentEditor.layer.hidden = true;
  $('source').hidden = false;
  $('editor').hidden = true;
  $('sourceTab').classList.add('active');
  $('visualTab').classList.remove('active');
  status('Editing HTML. Return to Write to review it before saving or queuing.');
  const pos = needle ? $('source').value.indexOf(needle) : -1;
  if (pos >= 0) {
    $('source').focus();
    $('source').setSelectionRange(pos, pos);
    $('source').scrollTop = Math.max(
      0,
      ($('source').scrollHeight * pos) / $('source').value.length -
        $('source').clientHeight / 3,
    );
  }
};
$('visualTab').onclick = () => {
  if (mode === 'source') applySource();
};
function sourceFind(back = false) {
  const needle = $('sourceFindText').value;
  if (!needle) return;
  const t = $('source'),
    hay = t.value.toLowerCase(),
    q = needle.toLowerCase();
  let at = back
    ? hay.lastIndexOf(q, Math.max(0, t.selectionStart - 1))
    : hay.indexOf(q, t.selectionEnd);
  if (at < 0) at = back ? hay.lastIndexOf(q) : hay.indexOf(q);
  if (at >= 0) {
    t.focus();
    t.setSelectionRange(at, at + needle.length);
  }
}
function visualFind(back = false) {
  const needle = $('sourceFindText').value.toLowerCase();
  if (!needle) return;
  const walker = document.createTreeWalker($('editor'), NodeFilter.SHOW_TEXT),
    nodes = [];
  let text = '',
    node;
  while ((node = walker.nextNode())) {
    nodes.push({ node, start: text.length });
    text += node.data;
  }
  const s = window.getSelection();
  let current = back ? 0 : text.length;
  if (s.rangeCount && $('editor').contains(s.anchorNode)) {
    const r = s.getRangeAt(0).cloneRange();
    r.selectNodeContents($('editor'));
    r.setEnd(s.anchorNode, s.anchorOffset);
    current = r.toString().length;
  }
  const hay = text.toLowerCase();
  let at = back
    ? hay.lastIndexOf(needle, Math.max(0, current - 1))
    : hay.indexOf(needle, current);
  if (at < 0) at = back ? hay.lastIndexOf(needle) : hay.indexOf(needle);
  if (at < 0) return;
  const locate = (offset) => {
      for (let i = nodes.length - 1; i >= 0; i--)
        if (offset >= nodes[i].start) return [nodes[i].node, offset - nodes[i].start];
      return [nodes[0].node, 0];
    },
    start = locate(at),
    end = locate(at + needle.length),
    range = document.createRange();
  range.setStart(...start);
  range.setEnd(...end);
  s.removeAllRanges();
  s.addRange(range);
  selection = range.cloneRange();
  $('editor').focus();
  range.startContainer.parentElement?.scrollIntoView({ block: 'center' });
}
function findCurrent(back = false) {
  mode === 'source' ? sourceFind(back) : visualFind(back);
}
function openFind() {
  if (!page) return;
  $('sourceFind').hidden = false;
  $('sourceFindText').focus();
  $('sourceFindText').select();
}
function openLink() {
  if (mode !== 'visual') return;
  capture();
  const choices = pages
    .filter((p) => p.kind === 'page' || (p.main && p.name !== 'openers.html'))
    .sort((a, b) => a.title.localeCompare(b.title));
  modal(
    'Add link',
    '<label>Web address<input id="linkAddress" placeholder="https://… or /page.html"></label><label>Or choose one of your Pages<select id="linkPage"><option value="">Choose a Page…</option>' +
      choices
        .map(
          (p) =>
            '<option value="/' +
            esc(p.name) +
            '">' +
            esc(p.title) +
            ' — /' +
            esc(p.name) +
            '</option>',
        )
        .join('') +
      '</select></label><p class="hint">Pages are permanent site pages such as /year-2018.html. Numbered filenames are reserved for Posts.</p><div class="dialog-actions"><button id="cancelLink">Cancel</button><button id="applyLink">Add link</button></div>',
  );
  const address = $('linkAddress'),
    picker = $('linkPage');
  picker.onchange = () => {
    if (picker.value) address.value = picker.value;
  };
  $('cancelLink').onclick = () => $('dialog').close();
  address.focus();
  $('applyLink').onclick = () => {
    const url = address.value.trim();
    if (!/^(?:https?:\/\/|\/)(?!\/)/i.test(url)) {
      status('Use a full web address or a site Page beginning with /.');
      address.focus();
      return;
    }
    const label = selection?.toString() || url;
    $('dialog').close();
    $('editor').focus();
    restoreSelection();
    if (!document.execCommand('createLink', false, url)) {
      insert('<a href="' + esc(url) + '">' + esc(label) + '</a>');
      return;
    }
    capture();
    mark();
    status('Link added. Save the draft when ready.');
  };
}
window.addEventListener('keydown', (e) => {
  if (!e.metaKey || e.altKey) return;
  const key = e.key.toLowerCase();
  if (key === 'f' && page && !readerActive) {
    e.preventDefault();
    openFind();
  } else if (key === 'k' && mode === 'visual' && !readerActive) {
    e.preventDefault();
    capture();
    openLink();
  } else if ((key === 'b' || key === 'i') && mode === 'visual' && !readerActive) {
    e.preventDefault();
    restoreSelection();
    document.execCommand(key === 'b' ? 'bold' : 'italic', false, null);
    capture();
    updateFormatState();
    mark();
  }
});
$('sourceFindNext').onclick = () => findCurrent(false);
$('sourceFindPrev').onclick = () => findCurrent(true);
$('sourceFindText').onkeydown = (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    findCurrent(e.shiftKey);
  }
  if (e.key === 'Escape') $('sourceFindClose').click();
};
$('sourceFindClose').onclick = () => {
  $('sourceFind').hidden = true;
  (mode === 'source' ? $('source') : $('editor')).focus();
};
for (const b of document.querySelectorAll('[data-format],[data-block]')) {
  if (['bold', 'italic'].includes(b.dataset.format))
    b.setAttribute('aria-pressed', 'false');
  b.onmousedown = (e) => e.preventDefault();
  b.onclick = () => {
    if (mode !== 'visual') return;
    restoreSelection();
    $('editor').focus();
    document.execCommand(b.dataset.format || 'formatBlock', false, b.dataset.block || null);
    normalizeParagraphs();
    if (b.dataset.block === 'h2') fragmentEditor.addDivider();
    capture();
    updateFormatState();
    mark();
  };
}
$('center').onmousedown = (e) => e.preventDefault();
$('center').onclick = () => {
  if (mode !== 'visual') return;
  const blocks = selectedEditorBlocks().filter(
    (block) => !block.matches('blockquote.blyg-transclusion'),
  );
  if (!blocks.length) return;
  const remove = blocks.every((block) => block.classList.contains('blynger-centered'));
  for (const block of blocks) block.classList.toggle('blynger-centered', !remove);
  capture();
  updateFormatState();
  mark();
  status(remove ? 'Centering removed.' : 'Centered.');
};
$('blockquote').onclick = () => {
  if (mode !== 'visual') return;
  const cite = (prompt('Citation URL (optional)') || '').trim();
  $('editor').focus();
  document.execCommand('formatBlock', false, 'blockquote');
  const block = fragmentEditor.cursor();
  if (block) block.classList.add('blynger-citation');
  if (block && cite && /^https?:\/\//.test(cite)) {
    block.setAttribute('cite', cite);
    block.querySelector(':scope > cite.blynger-blockquote-source')?.remove();
    const c = document.createElement('cite'),
      a = document.createElement('a');
    c.className = 'blynger-blockquote-source';
    a.href = cite;
    try {
      a.textContent = '—' + new URL(cite).hostname.replace(/^www\./, '');
    } catch {
      a.textContent = '—source';
    }
    c.append(a);
    block.append(c);
  }
  mark();
};
$('link').onmousedown = (e) => e.preventDefault();
$('link').onclick = openLink;
$('preview').onclick = () => {
  if (!page) return;
  modal(
    'Preview — ' + page.title,
    '<iframe class="preview-frame" id="previewFrame" sandbox="" title="Page preview"></iframe><p class="hint">Preview only. Nothing has been published.</p>',
  );
  const r = dirty ? raw() : page.raw;
  $('previewFrame').srcdoc = localImages(r).replace(
    /<head([^>]*)>/i,
    '<head$1><base href="' + location.origin + '/preview/">',
  );
};
$('images').onclick = () =>
  run(async () => {
    capture();
    const imgs = await api('images');
    modal(
      'Image library',
      '<label>Add an image<input id="upload" type="file" accept="image/png,image/jpeg,image/gif,image/webp"></label><label>Image description<input id="imageAlt" placeholder="A short description for readers"></label><label>Image size<select id="imageSize"><option value="standard">Standard — 400 pixels or 77% of the screen</option><option value="small">Small — up to 200 pixels</option><option value="wide">Wide — 77% of the screen</option><option value="full">Full width</option></select></label><div class="image-grid" id="imageGrid"></div>',
    );
    const grid = $('imageGrid'),
      markup = (url) => imageMarkup(url, $('imageAlt').value, $('imageSize').value);
    for (const im of imgs) {
      const b = document.createElement('button');
      b.innerHTML = '<img src="/preview' + esc(im.url) + '" alt="">' + esc(im.name);
      b.onclick = () => {
        $('dialog').close();
        insert(markup(im.url));
      };
      grid.append(b);
    }
    $('upload').onchange = () =>
      run(async () => {
        const f = $('upload').files[0];
        if (!f) return;
        status('Adding image…');
        const result = await api('upload', {
          data: await imageFileData(f),
          name: f.name,
          alt: $('imageAlt').value,
        });
        $('dialog').close();
        insert(markup(result.url));
        status('Image added to the draft.');
      });
  });
$('tk').onclick = () => {
  if (!page) return;
  if (page.kind !== 'post') {
    status('TK is available only for posts.');
    return;
  }
  if (mode === 'source') {
    status('Return to Write to insert TK with its fragment boundaries.');
    return;
  }
  capture();
  const selected = window.getSelection().toString();
  modal(
    'TK assistant — ChatGPT via Codex',
    '<p>Describe what you want to add. You’ll review the text before inserting it.</p><textarea id="instruction" placeholder="For example: write a two-sentence transition into the next section.">' +
      esc(selected.replace(/^\[TK\]|\[\/TK\]$/g, '')) +
      '</textarea><p class="hint">Uses your local Codex sign-in. Generated text gets a light gray background. Your instructions remain private.</p><div class="dialog-actions"><button id="generate">Generate text</button></div>',
  );
  $('generate').onclick = () =>
    run(async () => {
      const b = $('generate');
      b.disabled = true;
      b.textContent = 'Writing…';
      status('TK is writing. This may take a minute.');
      try {
        const result = await api('tk', {
          name: page.name,
          instruction: $('instruction').value,
          context: $('editor').innerText,
        });
        modal(
          'Review TK text',
          '<div class="generated-result">' +
            result.html +
            '</div><p class="hint">Check wording and facts before using this text.</p><div class="dialog-actions"><button id="discardTK">Discard</button><button id="insertTK">Insert into draft</button></div>',
        );
        $('discardTK').onclick = () => $('dialog').close();
        $('insertTK').onclick = () => {
          $('dialog').close();
          if (mode === 'source') {
            status(
              'Return to Write before inserting TK so fragment boundaries can be created.',
            );
            return;
          }
          const inserted = fragmentEditor.insertTK(result.html, selection);
          if (inserted) {
            const index = [...$('editor').querySelectorAll('.blyg-tk-gen')].indexOf(
              inserted,
            );
            while (generated.length < index) generated.push({ sources: [] });
            generated.splice(index, 0, result.provenance);
            capture();
          }
        };
      } finally {
        b.disabled = false;
        b.textContent = 'Generate text';
      }
    });
};
$('migrate').onclick = () => {
  modal(
    'Rebuild Blyg archive',
    '<p>Ordinary publishing already keeps the Blyg archive current.</p><p class="hint">Usually automatic. Use only after a Blynger upgrade or to repair the archive.</p><div class="dialog-actions"><button id="cancelRebuild">Cancel</button><button id="confirmRebuild">Rebuild archive</button></div>',
  );
  $('cancelRebuild').onclick = () => $('dialog').close();
  $('confirmRebuild').onclick = () =>
    run(async () => {
      const button = $('confirmRebuild');
      button.disabled = true;
      status('Rebuilding Blyg archive…');
      const result = await api('migrate', {});
      $('dialog').close();
      status(result.message);
      await refresh();
    });
};
$('settings').onclick = () =>
  run(async () => {
    const s = await api('configuration');
    const field = (id, label, value) =>
      '<label>' +
      label +
      '<input id="' +
      id +
      '" value="' +
      esc(value || '') +
      '"></label>';
    modal(
      'Settings',
      '<p class="hint">These values live in Blynger’s private settings file. They affect future work and never restyle old pages.</p>' +
        field('site_root', 'Website folder', s.site_root) +
        field('data_root', 'Private data folder', s.data_root) +
        field('site_url', 'Public website address', s.site_url) +
        field('site_label', 'Website name', s.site_label) +
        field('author_name', 'Author name', s.author_name) +
        field('author_signature', 'Default signature', s.author_signature) +
        field('blyg_title', 'Blyg title', s.blyg_title) +
        field('feed_description', 'Feed description', s.feed_description) +
        field('blogroll_heading', 'Blogroll heading', s.blogroll_heading) +
        field('twitter_creator', 'Social account (optional)', s.twitter_creator) +
        '<h3>Publishing</h3>' +
        field('remote', 'Git remote', s.remote) +
        field('branch', 'Git branch', s.branch) +
        field('ssh_key', 'SSH key file', s.ssh_key) +
        field('ssh_user', 'SSH account name', s.ssh_user) +
        field('hostname', 'SSH hostname', s.hostname) +
        field('remote_path', 'Remote repository path', s.remote_path) +
        '<p class="hint">Blynger stores only the key’s location, never its contents.</p><div id="connectionResult"></div><div class="dialog-actions"><button id="saveSettings">Save settings</button><button id="testConnection">Test connection</button></div>',
    );
    $('saveSettings').onclick = () =>
      run(async () => {
        const data = {};
        for (const id of [
          'site_root',
          'data_root',
          'site_url',
          'site_label',
          'author_name',
          'author_signature',
          'blyg_title',
          'feed_description',
          'blogroll_heading',
          'twitter_creator',
          'remote',
          'branch',
          'ssh_key',
          'ssh_user',
          'hostname',
          'remote_path',
        ])
          data[id] = $(id).value;
        const r = await api('configuration', data);
        $('connectionResult').textContent = r.message;
      });
    $('testConnection').onclick = async () => {
      const b = $('testConnection');
      b.disabled = true;
      $('connectionResult').textContent = 'Connecting…';
      try {
        const r = await api('connection', {});
        $('connectionResult').textContent = r.message;
      } catch (e) {
        $('connectionResult').textContent = e.message;
      } finally {
        b.disabled = false;
      }
    };
  });
$('publish').onclick = () =>
  publicationTask(async () => {
    if (dirty) await save();
    status('Preparing local publication files…');
    await api('prepare', { review: false });
    status('Checking the hosted version…');
    const r = await api('refresh-review', {});
    modal(
      'Review publication',
      '<p><b>' +
        r.changes.length +
        ' files ready for ' +
        esc(r.settings.site) +
        '</b></p>' +
        (r.planned_pins
          ? '<div class="notice"><b>' +
            r.planned_pins +
            ' irrevocable version ' +
            (r.planned_pins === 1 ? 'pin is' : 'pins are') +
            ' included.</b></div>'
          : '') +
        '<div class="notice">This includes earlier edits already present in your site folder. Publishing will commit these website files and send them to the configured Git host. Drafts and app files are excluded.</div><div class="filelist">' +
        (r.changes
          .map(
            (c) =>
              esc((c.deleted ? '− ' : c.new ? '+ ' : '~ ') + c.path) +
              ' <small>' +
              (c.deleted ? 'remove' : Math.ceil(c.bytes / 1024) + ' KB') +
              '</small>',
          )
          .join('<br>') || 'No new file changes. You may retry a previously failed push.') +
        '</div>' +
        r.comparisons
          .map(
            (c) =>
              '<details><summary>Compare ' +
              esc(c.path) +
              ' with the hosted version</summary><pre class="diff">' +
              esc(c.diff) +
              '</pre></details>',
          )
          .join('') +
        '<label>Git update note<input id="publicationNote" maxlength="1000" value="' +
        esc(r.commit_message) +
        '"></label><p class="hint">Automatically lists changed pages. You can replace it with a short summary of a broader change.</p><div id="publishResult"></div><div class="dialog-actions"><button id="cancelPublish">Keep local</button><button id="confirmPublish" class="publish">Publish to website</button></div>',
    );
    $('publicationNote').onchange = () =>
      run(() => api('publication-note', { note: $('publicationNote').value }));
    $('cancelPublish').onclick = () => {
      $('dialog').close();
      status('Prepared locally. Nothing sent to the website.');
    };
    $('confirmPublish').onclick = async () => {
      if (publishing) return;
      publishing = true;
      setPublishBusy(true, 'Posting');
      const b = $('confirmPublish');
      b.disabled = true;
      b.textContent = 'Posting';
      status('Posting…');
      try {
        const result = await api('publish', {
          signature: r.signature,
          note: $('publicationNote').value,
        });
        $('publishResult').textContent = result.message;
        status(result.message);
        b.textContent = 'Close';
        b.onclick = () => $('dialog').close();
        await refresh();
        if (page) await openPage(page.name);
      } catch (e) {
        $('publishResult').className = 'notice error';
        $('publishResult').textContent = e.message;
        b.textContent = 'Retry publication';
        status('Publication failed: ' + e.message);
      } finally {
        publishing = false;
        setPublishBusy(false);
        b.disabled = false;
      }
    };
    if (page) page = await api('page?name=' + encodeURIComponent(page.name));
    await refresh();
  });
setInterval(
  () => {
    if (readerActive && !readerBusy) readerOperation('reader-sync', { subscription: null });
  },
  90 * 60 * 1000,
);

$('revert').onclick = () =>
  run(async () => {
    if (
      !page ||
      !confirm(
        'Discard this saved draft and unsaved edits? The existing site file will remain as it is.',
      )
    )
      return;
    const name = page.new ? 'index.html' : page.name;
    await api('discard', { name: page.name });
    dirty = false;
    await refresh();
    await openPage(name);
  });

$('versions').onclick = () =>
  run(async () => {
    if (!page) return;
    if (dirty) await save();
    const history = await api('versions?name=' + encodeURIComponent(page.name));
    modal(
      'Versions — ' + page.title,
      '<p>Published versions are kept privately on this Mac. A pin makes one version permanently public after you review and publish.</p><label>Change note<input id="revisionNote" placeholder="What are you changing?"></label><div class="dialog-actions"><button id="startRevision">Start a revision</button></div><div id="versionRows"></div>',
    );
    $('startRevision').onclick = () =>
      run(async () => {
        const updated = await api('revise', {
          name: page.name,
          note: $('revisionNote').value,
        });
        $('dialog').close();
        await refresh();
        await openPage(updated.name);
        status('Revision draft ready. Edit, save, then review and publish.');
      });
    if (!history.versions.length)
      $('versionRows').textContent =
        'No published versions archived yet. Your first publication starts version 1.';
    for (const v of history.versions) {
      const row = document.createElement('section');
      row.className = 'version-row';
      row.innerHTML =
        '<h3>Version ' +
        v.version +
        (v.version === history.current ? ' · current' : '') +
        '</h3><p>' +
        esc(v.at) +
        ' · ' +
        esc(v.note || '') +
        '</p><div class="version-actions"><button class="view-version">Read version</button><button class="restore-version">Use as revision</button><button class="pin-version" ' +
        (v.pinned || v.queued ? 'disabled' : '') +
        '>' +
        (v.pinned ? 'Permanently pinned' : v.queued ? 'Pin queued' : 'Pin this version') +
        '</button></div><div class="version-content" hidden></div>';
      row.querySelector('.view-version').onclick = () => {
        const box = row.querySelector('.version-content');
        box.hidden = !box.hidden;
        if (!box.hidden) {
          box.innerHTML =
            '<iframe sandbox="" title="Historical version" class="preview-frame"></iframe>';
          box.firstChild.srcdoc =
            '<meta charset="utf-8"><base href="' +
            location.origin +
            '/preview/">' +
            localImages(v.html);
        }
      };
      row.querySelector('.restore-version').onclick = () =>
        run(async () => {
          if (
            !confirm(
              'Replace the current draft with this historical content? The published page stays unchanged.',
            )
          )
            return;
          const updated = await api('revise', {
            name: page.name,
            version: v.version,
            note: $('revisionNote').value || 'Restore content from version ' + v.version,
          });
          $('dialog').close();
          await updatePublicationState();
          await openPage(updated.name);
          status('Historical content copied into a new revision draft.');
        });
      row.querySelector('.pin-version').onclick = () =>
        run(async () => {
          if (
            !confirm(
              'Queue a permanent public pin of version ' +
                v.version +
                '? Once published, its exact content must remain publicly available.',
            )
          )
            return;
          const r = await api('pin', { name: page.name, version: v.version });
          await updatePublicationState();
          status(r.message);
          row.querySelector('.pin-version').disabled = true;
          row.querySelector('.pin-version').textContent = 'Pin queued';
        });
      $('versionRows').append(row);
    }
  });
$('quote').onclick = () => run(openQuotePicker);

$('fragment').onmousedown = (e) => e.preventDefault();
$('fragment').onclick = () => {
  if (!page || mode !== 'visual') return;
  if (page.name === 'openers.html') {
    status(
      'Each dated Opener is already a fragment. Use New opener to add one; save and publish when ready.',
    );
    return;
  }
  capture();
  $('editor').focus();
  if (selection) {
    getSelection().removeAllRanges();
    getSelection().addRange(selection);
  }
  fragmentEditor.addDivider();
  capture();
};
$('removeFragment').onclick = () => {
  if (!page || mode !== 'visual') return;
  $('editor').focus();
  if (selection) {
    getSelection().removeAllRanges();
    getSelection().addRange(selection);
  }
  fragmentEditor.removeDivider();
  capture();
};

$('newOpener').onclick = () => {
  if (mode !== 'visual') {
    status('Return to Write to add an Opener.');
    return;
  }
  modal(
    'New opener',
    '<p>' +
      esc(fragmentEditor.openerDate()) +
      ' · Same-day entries are numbered I, II, III… automatically.</p><label>Opener<textarea id="openerText" placeholder="What crossed your mind?"></textarea></label><label class="pin-choice"><input id="openerPin" type="checkbox" checked> Pin this version when published</label><p class="hint">Added at the top and saved as a local draft. Publishing is a separate step.</p><div class="dialog-actions"><button id="cancelOpener">Cancel</button><button id="addOpener">Add opener</button></div>',
  );
  $('openerText').focus();
  $('cancelOpener').onclick = () => $('dialog').close();
  $('addOpener').onclick = () =>
    run(async () => {
      const text = $('openerText').value;
      if (!text.trim()) {
        $('openerText').focus();
        return;
      }
      if (fragmentEditor.newOpener(text, { pin_on_publish: $('openerPin').checked })) {
        $('dialog').close();
        capture();
        await save();
        status('Opener added and saved locally. Nothing published.');
      }
    });
};

let readerActive = false,
  publishing = false,
  readerSubscriptions = [];
function setPublishBusy(busy, label = 'Preparing…') {
  $('publish').textContent = busy ? label : '↑ Review & publish';
  $('publish').setAttribute('aria-busy', String(busy));
  syncPublishButton();
}
async function publicationTask(fn) {
  if (publishing) return;
  publishing = true;
  setPublishBusy(true);
  status('Preparing publication…');
  try {
    await fn();
  } catch (e) {
    error(e);
  } finally {
    publishing = false;
    setPublishBusy(false);
  }
}
$('mainFragment').onmousedown = (e) => e.preventDefault();
$('mainFragment').onclick = () => {
  if (!page || mode !== 'visual' || readerActive || page.kind === 'page') return;
  $('editor').focus();
  if (selection && $('editor').contains(selection.startContainer)) {
    getSelection().removeAllRanges();
    getSelection().addRange(selection);
  }
  fragmentEditor.addDivider();
  capture();
};
function setWorkspaceChrome(name, wide = false) {
  currentWorkspace = name;
  for (const button of document.querySelectorAll('.workspace-tabs button'))
    button.classList.toggle('active', button.dataset.workspace === name);
  $('workspace').className = 'workspace theme-' + name + (wide ? ' wide' : '');
  $('authorToolbar').hidden = ['images', 'reader', 'saved'].includes(name);
  $('new').hidden = name !== 'posts';
  $('newPage').hidden = name !== 'pages';
  $('newOpener').hidden = name !== 'openers';
  for (const id of [
    'versions',
    'mainFragment',
    'quote',
    'tk',
    'fragment',
    'removeFragment',
  ])
    $(id).hidden = name !== 'posts';
  $('libraryTitle').textContent = name === 'posts' ? 'POSTS' : 'PAGES';
  $('search').placeholder = name === 'posts' ? 'Search posts…' : 'Search pages…';
  $('search').setAttribute('aria-label', $('search').placeholder);
  $('postSort').hidden = name !== 'posts';
  renderPages();
}
function showWriting() {
  readerActive = false;
  if (['images', 'reader', 'saved'].includes(currentWorkspace) && page)
    currentWorkspace = workspaceForPage(page);
  $('newOpener').hidden = page?.name !== 'openers.html';
  $('readerView').hidden = true;
  $('imagesView').hidden = true;
  $('documentView').hidden = false;
  setWorkspaceChrome(currentWorkspace, currentWorkspace === 'openers');
  const unavailable = !!page?.deleted,
    nonPost = page && page.kind !== 'post';
  for (const id of ['save', 'queue', 'preview', 'images']) $(id).disabled = unavailable;
  $('tk').disabled = unavailable || nonPost;
  for (const id of ['versions', 'mainFragment', 'quote', 'fragment'])
    $(id).disabled = unavailable || nonPost;
}
function readerMessage(text) {
  $('readerStatus').textContent = text;
}
let savedView = 'saved';
async function showReader(sync = true) {
  capture();
  readerActive = true;
  $('newOpener').hidden = true;
  $('documentView').hidden = true;
  $('imagesView').hidden = true;
  $('readerView').hidden = false;
  setWorkspaceChrome(currentWorkspace, true);
  $('readerActions').hidden = currentWorkspace === 'saved';
  $('savedViews').hidden = currentWorkspace !== 'saved';
  $('readerViewFilter').hidden = currentWorkspace === 'saved';
  for (const id of ['save', 'queue', 'preview', 'images', 'versions', 'tk', 'mainFragment'])
    $(id).disabled = true;
  $('readerItems').replaceChildren();
  readerMessage(
    currentWorkspace === 'saved'
      ? savedView === 'activity'
        ? 'Loading private activity…'
        : 'Loading saved posts…'
      : 'Loading Reader…',
  );
  await loadReader();
  if (sync) await readerOperation('reader-sync', { subscription: null });
}
$('readerBack').onclick = showWriting;
async function showImagesWorkspace() {
  capture();
  readerActive = false;
  $('documentView').hidden = true;
  $('readerView').hidden = true;
  $('imagesView').hidden = false;
  setWorkspaceChrome('images', true);
  const images = await api('images'),
    grid = $('imageLibrary');
  grid.replaceChildren();
  for (const image of images) {
    const card = document.createElement('article');
    card.className = 'asset-card';
    const dimensions = image.dimensions ? image.dimensions.join(' × ') : 'Size unavailable',
      uses = image.used_in?.length ? image.used_in.join(', ') : 'Not used by an HTML page';
    card.innerHTML =
      '<img src="/preview' +
      esc(image.url) +
      '" alt=""><b>' +
      esc(image.name) +
      '</b><small>' +
      esc(dimensions) +
      '</small><small>' +
      esc(uses) +
      '</small>';
    grid.append(card);
  }
  $('imageStatus').textContent =
    images.length + ' image files · existing files are never changed here.';
}
function workspaceForPage(value) {
  if (value?.name === 'openers.html') return 'openers';
  return value?.kind === 'post' ? 'posts' : 'pages';
}
async function switchWorkspace(name) {
  if (name === 'images') {
    await showImagesWorkspace();
    return;
  }
  if (name === 'reader' || name === 'saved') {
    currentWorkspace = name;
    $('readerViewFilter').value = name === 'saved' ? 'saved' : 'all';
    $('readerHeading').textContent = name === 'saved' ? 'Saved' : 'Reader';
    $('readerEyebrow').textContent =
      name === 'saved' ? 'YOUR READING SHELF' : 'LOCAL READING DESK';
    await showReader(name === 'reader');
    return;
  }
  const eligible = pages.filter((p) =>
    name === 'posts'
      ? !p.main && p.kind === 'post'
      : name === 'pages'
        ? p.kind === 'page' || (p.main && p.name !== 'openers.html')
        : p.name === 'openers.html',
  );
  const current = eligible.find((p) => p.name === page?.name),
    target = current || eligible[0];
  if (target) await openPage(target.name);
}
for (const button of document.querySelectorAll('.workspace-tabs button'))
  button.onclick = () => run(() => switchWorkspace(button.dataset.workspace));
for (const button of document.querySelectorAll('[data-saved-view]'))
  button.onclick = () =>
    run(async () => {
      savedView = button.dataset.savedView;
      for (const choice of document.querySelectorAll('[data-saved-view]'))
        choice.classList.toggle('active', choice === button);
      await loadReader();
    });
$('imageAddToDraft').onclick = () => {
  if (!page) {
    status('Open a post, Opener, or page before inserting an image.');
    return;
  }
  currentWorkspace = workspaceForPage(page);
  showWriting();
  $('images').click();
};
$('imageUpload').onclick = () => $('imageUploadFile').click();
$('imageUploadFile').onchange = () =>
  run(async () => {
    const input = $('imageUploadFile'),
      file = input.files[0];
    if (!file) return;
    const alt = prompt('Image description (optional)') || '';
    status('Uploading image…');
    await api('upload', { data: await imageFileData(file), name: file.name, alt });
    input.value = '';
    await showImagesWorkspace();
    status('Image uploaded. It will be included with your next publication.');
  });
async function loadReader() {
  const request = ++readerLoadRevision,
    workspace = currentWorkspace,
    source = $('readerSource').value,
    q = $('readerSearch').value;
  if (workspace === 'saved' && savedView === 'activity') {
    const d = await api('interactions?q=' + encodeURIComponent(q));
    if (
      request !== readerLoadRevision ||
      workspace !== currentWorkspace ||
      savedView !== 'activity'
    )
      return;
    $('readerSource').hidden = true;
    readerMessage(
      d.items.length + ' private ' + (d.items.length === 1 ? 'action.' : 'actions.'),
    );
    BlyngerReaderUI.renderActivity($('readerItems'), d.items, esc);
    return;
  }
  $('readerSource').hidden = false;
  const view = workspace === 'saved' ? 'saved' : $('readerViewFilter').value;
  const d = await api(
    'reader?subscription=' +
      encodeURIComponent(source) +
      '&q=' +
      encodeURIComponent(q) +
      '&view=' +
      encodeURIComponent(view),
  );
  if (request !== readerLoadRevision || workspace !== currentWorkspace) return;
  readerSubscriptions = d.subscriptions;
  $('readerSource').replaceChildren(new Option('All subscriptions', ''));
  for (const s of d.subscriptions) $('readerSource').append(new Option(s.title, s.id));
  $('readerSource').value = source;
  const selected = d.subscriptions.find((s) => s.id === source),
    blog = $('readerBlogroll');
  blog.hidden = workspace === 'saved' || !selected || selected.type === 'web';
  if (selected)
    blog.textContent = selected.blogroll ? 'Remove from blogroll' : 'Show on blogroll';
  const scoped = d.subscriptions.filter((s) => !source || s.id === source),
    errors = scoped.flatMap((s) =>
      [
        s.error ? (s.error_kind ? '[' + s.error_kind + '] ' : '') + s.error : '',
        s.warning,
        ...(s.warnings || []),
      ]
        .filter(Boolean)
        .map((e) => s.title + ': ' + e),
    ),
    completed = scoped
      .map((s) => s.last_sync)
      .filter(Boolean)
      .sort(),
    syncMessage = completed.length
      ? 'Last sync: ' + BlyngerReaderUI.syncTime(completed.at(-1))
      : d.subscriptions.length
        ? 'Not synced yet.'
        : 'Add a Blyg URL to begin reading.';
  readerMessage(
    workspace === 'saved'
      ? d.items.length + ' saved ' + (d.items.length === 1 ? 'post.' : 'posts.')
      : [...errors, syncMessage].filter(Boolean).join('\n'),
  );
  $('readerItems').replaceChildren();
  if (!d.items.length)
    $('readerItems').textContent =
      currentWorkspace === 'saved' ? 'No saved posts yet.' : 'No matching Reader posts.';
  BlyngerReaderUI.renderItems($('readerItems'), d.items, esc, {
    read: (item) => run(() => readItem(item)),
    quote: (item) =>
      run(() => chooseQuote({ source: 'remote', key: item.key, title: item.title }, true)),
    save: (item) =>
      run(async () => {
        await api('reader-mark', { key: item.key, field: 'saved', value: !item.saved });
        await loadReader();
      }),
    like: (item) =>
      run(async () => {
        await api('reader-mark', { key: item.key, field: 'liked', value: !item.liked });
        await loadReader();
      }),
    react: (item, emoji) =>
      run(async () => {
        await api('reader-react', { key: item.key, reaction: emoji });
        await loadReader();
      }),
  });
}
$('readerSource').onchange = () => run(loadReader);
$('readerViewFilter').onchange = () => run(loadReader);
let readerSearchTimer;
$('readerSearch').oninput = () => {
  clearTimeout(readerSearchTimer);
  readerSearchTimer = setTimeout(() => run(loadReader), 180);
};
$('readerBlogroll').onclick = () =>
  run(async () => {
    const sub = readerSubscriptions.find((s) => s.id === $('readerSource').value);
    if (!sub) return;
    await api('reader-blogroll', { subscription: sub.id, value: !sub.blogroll });
    await loadReader();
    status('Blogroll choice saved. It will affect future posts only.');
  });
function openSubscriptionManager() {
  modal(
    'Manage subscriptions',
    '<p class="hint">Choose which subscriptions appear in the static blogroll on future posts, or remove a subscription. Saved and Liked posts are kept when a subscription is removed.</p><div id="subscriptionRows" class="subscription-rows"></div><div class="dialog-actions"><button id="closeSubscriptions">Done</button></div>',
  );
  const rows = $('subscriptionRows');
  const eligible = readerSubscriptions.filter((s) => s.type !== 'web');
  if (!eligible.length) rows.textContent = 'No feed subscriptions yet.';
  for (const sub of eligible) {
    const row = document.createElement('div');
    row.className = 'subscription-row';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = !!sub.blogroll;
    check.setAttribute('aria-label', 'Show ' + sub.title + ' on blogroll');
    const words = document.createElement('span');
    const title = document.createElement('b');
    title.textContent = sub.title;
    const address = document.createElement('small');
    address.textContent = sub.origin;
    words.append(title, address);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove-subscription';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', 'Remove subscription to ' + sub.title);
    row.append(check, words, remove);
    check.onchange = () =>
      run(async () => {
        check.disabled = true;
        try {
          await api('reader-blogroll', { subscription: sub.id, value: check.checked });
          sub.blogroll = check.checked;
          await loadReader();
          status('Blogroll choice saved. It will affect future posts only.');
        } catch (e) {
          check.checked = !check.checked;
          throw e;
        } finally {
          check.disabled = false;
        }
      });
    remove.onclick = () => {
      if (
        !confirm(
          'Remove subscription to ' +
            sub.title +
            '? Saved and Liked posts will stay on this Mac.',
        )
      )
        return;
      run(async () => {
        remove.disabled = true;
        const result = await api('reader-unsubscribe', { subscription: sub.id });
        await loadReader();
        openSubscriptionManager();
        status(result.message);
      });
    };
    rows.append(row);
  }
  $('closeSubscriptions').onclick = () => $('dialog').close();
}
$('readerManage').onclick = openSubscriptionManager;
let readerBusy = false;
async function readerOperation(path, data) {
  if (readerBusy) return;
  readerBusy = true;
  $('readerAdd').disabled = true;
  $('readerOpen').disabled = true;
  $('readerSync').disabled = true;
  $('readerSync').textContent = 'Syncing…';
  if (currentWorkspace === 'reader') readerMessage('Checking subscriptions…');
  try {
    const result = await api(path, data);
    if (path === 'reader-subscribe' || path === 'reader-open') $('dialog').close();
    await loadReader();
    if (result.selected) {
      const items = (await api('reader')).items;
      const item = items.find((i) => i.key === result.selected);
      if (item) await readItem(item);
    }
  } catch (e) {
    if (currentWorkspace === 'reader') readerMessage(e.message);
    if ($('subscribeError')) $('subscribeError').textContent = e.message;
  } finally {
    readerBusy = false;
    if ($('confirmSubscribe')) {
      $('confirmSubscribe').disabled = false;
      $('confirmSubscribe').textContent = 'Subscribe';
    }
    $('readerAdd').disabled = false;
    $('readerOpen').disabled = false;
    $('readerSync').disabled = false;
    $('readerSync').textContent = 'Refresh / Sync';
  }
}
$('readerAdd').onclick = () => {
  modal(
    'Add Blyg',
    '<label>Blyg, website, RSS/Atom, or item URL<input id="readerURL" type="url" placeholder="https://…" aria-label="Blyg URL"></label><p class="hint">Blynger discovers Blyg data or an ordinary RSS/Atom feed and downloads writing for offline reading.</p><p id="subscribeError" class="error" role="alert"></p><div class="dialog-actions"><button id="confirmSubscribe">Subscribe</button></div>',
  );
  $('readerURL').focus();
  $('confirmSubscribe').onclick = () => {
    if (readerBusy) return;
    $('confirmSubscribe').disabled = true;
    $('confirmSubscribe').textContent = 'Discovering…';
    readerOperation('reader-subscribe', { url: $('readerURL').value.trim() });
  };
  $('readerURL').onkeydown = (e) => {
    if (e.key === 'Enter') $('confirmSubscribe').click();
  };
};
$('readerSync').onclick = () =>
  readerOperation('reader-sync', { subscription: $('readerSource').value || null });
$('readerOpen').onclick = () => {
  modal(
    'Open in Reader',
    '<label>Web address<input id="readerURL" type="url" placeholder="https://…"></label><p class="hint">Blyg, RSS, and ordinary web pages open in the same reading desk.</p><p id="subscribeError" class="error"></p><div class="dialog-actions"><button id="confirmSubscribe">Open</button></div>',
  );
  $('readerURL').focus();
  $('confirmSubscribe').onclick = () =>
    readerOperation('reader-open', {
      url: $('readerURL').value.trim(),
      allow_subscription: true,
    });
};
async function readItem(item) {
  const d = await api('reader-item?key=' + item.key);
  let choice = { mode: 'whole' },
    active = null;
  const opened = BlyngerReaderUI.openedItem(item, d, esc, shortDate),
    native = opened.native,
    pins = opened.pins;
  modal(item.title, opened.html);
  const frame = $('readerFrame'),
    button = $('quoteReading');
  button.onmousedown = (e) => e.preventDefault();
  const update = (data) => {
    choice =
      data.mode === 'excerpt'
        ? { mode: 'excerpt', text: data.text }
        : data.mode === 'fragment'
          ? { mode: 'fragment', fragment: data.fragment }
          : { mode: 'whole' };
    active = choice.mode === 'fragment' ? choice.fragment : null;
    button.disabled = false;
    button.textContent =
      choice.mode === 'excerpt'
        ? 'Quote selection'
        : choice.mode === 'fragment'
          ? 'Quote fragment'
          : 'Quote';
    for (const b of document.querySelectorAll('.reader-fragment-choice'))
      b.classList.toggle('active', Number(b.dataset.fragment) === active);
  };
  const bridge = BlyngerReaderFrame.connect(frame, {
    selection: update,
    link: (data) => {
      if (/^(https?:|mailto:|tel:)/i.test(data.href))
        run(() => api('open-external', { url: data.href }));
    },
  });
  $('dialog').addEventListener('close', () => bridge.close(), { once: true });
  const choices = $('readerFragmentChoices');
  for (const f of d.fragments || []) {
    if (!choices) break;
    const pick = document.createElement('button');
    pick.className = 'reader-fragment-choice';
    pick.dataset.fragment = String(f.index);
    pick.textContent = 'Fragment ' + (f.index + 1) + (f.label ? ' — ' + f.label : '');
    pick.onclick = () => bridge.selectFragment(f.index);
    choices.append(pick);
  }
  frame.srcdoc = BlyngerReaderFrame.documentHTML(
    d.html,
    native,
    bridge.channel,
    location.origin,
  );
  button.onclick = () =>
    run(async () => {
      if (!choice) return;
      button.disabled = true;
      try {
        const prepared = await api('quote-item', {
          source: 'remote',
          key: item.key,
          selection: { ...choice, fingerprint: d.fingerprint },
        });
        await chooseQuote(
          { source: 'remote', key: item.key, title: item.title, prepared },
          true,
        );
      } finally {
        button.disabled = false;
      }
    });
  $('stubReading').onclick = () =>
    run(async () => {
      const prepared = await api('quote-item', {
        source: 'remote',
        key: item.key,
        selection: { mode: 'whole', fingerprint: d.fingerprint, transclude: true },
      });
      chooseStub(item, prepared);
    });
  $('openOriginal').onclick = () =>
    run(() => api('open-external', { url: d.original_url }));
  const followConversation = (link) =>
    run(async () => {
      if (link.key) {
        const target = (await api('reader')).items.find(
          (candidate) => candidate.key === link.key,
        );
        if (target) {
          await readItem(target);
          return;
        }
      }
      await api('open-external', { url: link.url });
    });
  if ($('readerConversationBack'))
    $('readerConversationBack').onclick = () => followConversation(d.conversation.backward);
  for (const button of document.querySelectorAll('.reader-conversation-forward'))
    button.onclick = () =>
      followConversation(d.conversation.forward[Number(button.dataset.forward)]);
  if ($('forkReading'))
    $('forkReading').onclick = () => {
      modal(
        'Fork pinned version',
        '<p>A fork is an editable copy with permanent lineage, not a quotation.</p><div id="forkVersions"></div>',
      );
      for (const version of pins) {
        const b = document.createElement('button');
        b.textContent = 'Fork version ' + version;
        b.onclick = () =>
          run(async () => {
            b.disabled = true;
            const forked = await api('reader-fork', {
              key: item.key,
              version,
              title: 'Fork of ' + item.title,
            });
            $('dialog').close();
            await refresh();
            await openPage(forked.name);
            status(
              'Pinned writing copied into a new independent draft with its lineage preserved.',
            );
          });
        $('forkVersions').append(b);
      }
    };
}
async function openQuotePicker() {
  capture();
  const choices = await api('quote-choices');
  modal(
    'Quote post',
    '<p class="hint">Quote your published fragments or threads, or cached writing from another Blyg. New reader quotes preserve the content you selected without fetching the remote site.</p><input id="quoteSearch" placeholder="Search title or author" aria-label="Search quotes"><div id="quoteRows"></div>',
  );
  const render = () => {
    const q = $('quoteSearch').value.toLowerCase(),
      groups = new Map();
    for (const item of choices) {
      if (
        !(item.title + ' ' + (item.author || '') + ' ' + item.origin)
          .toLowerCase()
          .includes(q)
      )
        continue;
      const group =
        item.source === 'local'
          ? 'MY BLYG'
          : (item.site || item.author || item.origin) + ' — ' + item.origin;
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(item);
    }
    $('quoteRows').replaceChildren();
    for (const [name, items] of groups) {
      const h = document.createElement('h3');
      h.textContent = name;
      $('quoteRows').append(h);
      for (const item of items) {
        const b = document.createElement('button');
        b.className = 'quote-option';
        b.textContent =
          item.title +
          ' · ' +
          (item.source_type === 'l0' ? 'RSS / Atom' : item.kind + ' · v' + item.version);
        b.onclick = () =>
          run(() => chooseQuote({ ...item, key: item.key || item.id }, readerActive));
        $('quoteRows').append(b);
      }
    }
    if (!groups.size) $('quoteRows').textContent = 'No matching cached or published items.';
  };
  $('quoteSearch').oninput = render;
  render();
}
async function chooseQuote(item, newPost) {
  const quoted =
    item.prepared ||
    (await api('quote-item', {
      source: item.source,
      key: item.key,
      ...(item.source === 'remote'
        ? { selection: item.selection || { mode: 'whole' } }
        : {}),
    }));
  const sameTarget =
    page?.kind === 'post' &&
    page.stub_of &&
    quoted.stub_of &&
    page.stub_of.id === quoted.stub_of.id &&
    page.stub_of.origin === quoted.stub_of.origin;
  const addQuote = async () => {
    showWriting();
    if (quoted.snapshot) quotes[quoted.snapshot.token] = quoted.snapshot;
    insert('<p><br></p>' + quoted.html + '<p><br></p>');
    status('Quote added. Save the draft when ready.');
  };
  if (newPost) {
    modal(
      'New post with quotation',
      '<label>Post title<input id="quoteTitle" value="' +
        esc('Quoting ' + item.title) +
        '"></label><p class="hint">Starts an ordinary post containing this quotation. It is not a response stub.</p><div class="dialog-actions">' +
        (sameTarget ? '<button id="addQuotedPost">Add to current response</button>' : '') +
        '<button id="createQuotedPost">Create draft</button></div>',
    );
    if (sameTarget)
      $('addQuotedPost').onclick = () =>
        run(async () => {
          $('dialog').close();
          await addQuote();
        });
    $('createQuotedPost').onclick = () =>
      run(async () => {
        if (dirty) await save();
        const p = await api('new', { title: $('quoteTitle').value });
        $('dialog').close();
        await refresh();
        await openPage(p.name);
        const first = $('editor').querySelector('p');
        if (!first) throw Error('New post body is missing.');
        const holder = document.createElement('div');
        holder.innerHTML = localImages('<p><br></p>' + quoted.html + '<p><br></p>');
        first.replaceWith(...holder.childNodes);
        if (quoted.snapshot) quotes[quoted.snapshot.token] = quoted.snapshot;
        selection = null;
        mark();
        await save();
      });
    return;
  }
  $('dialog').close();
  await addQuote();
}
function chooseStub(item, quoted) {
  const native = !quoted.stub_of.url,
    context = native ? quoted.stub_label_html + quoted.html : quoted.stub_html;
  modal(
    'Stub — response to ' + item.title,
    '<p class="hint">A Stub keeps one permanent response target. For a Blyg item, its complete verified snapshot starts the draft as a protected quotation; delete the whole quotation if you do not want it. The response remains a Stub either way.</p><label>Post headline<input id="stubTitle" value="' +
      esc('Response to ' + item.title) +
      '"></label><label>Quick Opener response<textarea id="stubOpener" placeholder="Your brief response…"></textarea></label><div class="dialog-actions"><button id="stubToOpener">Stub to Opener</button><button id="stubToPost">Stub to post</button></div>',
  );
  $('stubToPost').onclick = () =>
    run(async () => {
      if (dirty) await save();
      const p = await api('new', { title: $('stubTitle').value, stub_of: quoted.stub_of });
      $('dialog').close();
      await refresh();
      await openPage(p.name);
      const first = $('editor').querySelector('p');
      if (!first) throw Error('New post body is missing.');
      const holder = document.createElement('div');
      holder.innerHTML = localImages('<p><br></p>' + context + '<p><br></p>');
      first.replaceWith(...holder.childNodes);
      if (native && quoted.snapshot) quotes[quoted.snapshot.token] = quoted.snapshot;
      fragmentEditor.lockTransclusions();
      selection = null;
      mark();
      await save();
      status('Response stub saved as a post draft.');
    });
  $('stubToOpener').onclick = () =>
    run(async () => {
      const text = $('stubOpener').value.trim();
      if (!text) {
        $('stubOpener').focus();
        return;
      }
      if (dirty) await save();
      $('dialog').close();
      await openPage('openers.html');
      const opener = fragmentEditor.newOpener(text, {
        stub_of: quoted.stub_of,
        stub_html: localImages(context),
        pin_on_publish: true,
      });
      if (!opener) throw Error('Could not add the response Opener.');
      if (native && quoted.snapshot) quotes[quoted.snapshot.token] = quoted.snapshot;
      fragmentEditor.lockTransclusions();
      capture();
      await save();
      status('Response stub saved as a new Opener draft.');
    });
}

$('editHeadline').onclick = () => {
  if (!page) return;
  if (mode !== 'visual') {
    status('Return to Write to edit the headline.');
    return;
  }
  const noun = page.kind === 'page' ? 'page title' : 'post headline';
  modal(
    'Edit ' + noun,
    '<label>' +
      esc(noun[0].toUpperCase() + noun.slice(1)) +
      '<input id="headlineText" value="' +
      esc($('editor').querySelector('h1')?.textContent || page.title) +
      '"></label><p class="hint">Changes the title shown on this ' +
      (page.kind === 'page'
        ? 'page.'
        : 'post. Quoted writing keeps its original identity and content.') +
      '</p><div class="dialog-actions"><button id="saveHeadline">Save headline</button></div>',
  );
  $('headlineText').focus();
  $('saveHeadline').onclick = () =>
    run(async () => {
      const title = $('headlineText').value.trim();
      if (!title) return;
      let h = $('editor').querySelector('h1');
      if (!h) {
        h = document.createElement('h1');
        $('editor').prepend(h);
      }
      h.textContent = title;
      page.prefix = page.prefix.replace(
        /<title\b[^>]*>[\s\S]*?<\/title>/i,
        () => '<title>' + esc(title) + '</title>',
      );
      page.title = title;
      $('heading').textContent = title;
      mark();
      $('dialog').close();
      await save();
    });
};

$('deletePost').onclick = () => {
  if (!page) return;
  const restore = !!page.deleted;
  modal(
    restore ? 'Restore post' : 'Delete post',
    '<p>' +
      esc(page.title) +
      '</p><p>' +
      (restore
        ? 'Restore the saved writing as a draft. Publish when you want it back on the website.'
        : 'Keep a recoverable local copy and remove this post from the homepage on your next publication. Published Blyg items receive a withdrawal record; pinned versions and reusable fragments remain available.') +
      '</p><div class="dialog-actions"><button id="cancelDelete">Cancel</button><button id="confirmDelete">' +
      (restore ? 'Restore post' : 'Delete post') +
      '</button></div>',
  );
  $('cancelDelete').onclick = () => $('dialog').close();
  $('confirmDelete').onclick = () =>
    run(async () => {
      const b = $('confirmDelete');
      b.disabled = true;
      try {
        if (dirty && !restore) await save();
        const name = page.name,
          r = await api(restore ? 'restore-post' : 'delete-post', { name });
        dirty = false;
        $('dialog').close();
        await refresh();
        await openPage(name);
        status(r.message);
      } finally {
        b.disabled = false;
      }
    });
};
$('about').onclick = () =>
  modal(
    'About Blynger',
    '<div class="about-blynger"><img src="/static/blynger-logo.png" alt="Blynger"><div><h2>Blynger</h2><p>Blynger is a static personal website manager with Blygger interoperability built in.</p><p class="hint">' +
      esc(document.querySelector('.title-details').textContent.trim()) +
      '</p></div></div><div class="dialog-actions"><button id="closeAbout">OK</button></div>',
  );
$('help').onclick = () =>
  modal(
    'Blynger Help',
    '<div class="help-grid"><section><h3>Write</h3><p><b>Posts</b> holds published writing and drafts, with search, versions, fragments, quotations, and TK. <b>Openers</b> is the running Opener editor. <b>Pages</b> holds permanent site pages.</p></section><section><h3>Files and reading</h3><p><b>Images</b> shows site images and where they are used. <b>Reader</b> contains subscriptions and Likes. <b>Saved</b> is the permanent reading shelf.</p></section><section><h3>Save and publish</h3><p><b>Save draft</b> keeps work private. <b>Queue</b> saves it for a later publication. <b>Review &amp; publish</b> shows the exact website files before anything is sent.</p></section><section><h3>Application menu</h3><p>Settings and About are in the <b>Blynger</b> menu. The rare <b>Rebuild Blyg archive</b> repair action is under <b>Help</b>.</p></section></div><div class="dialog-actions"><button id="closeHelp">OK</button></div>',
  );
document.addEventListener('click', (event) => {
  if (event.target.id === 'closeAbout') $('dialog').close();
});
document.addEventListener('click', (event) => {
  if (event.target.id === 'closeHelp') $('dialog').close();
});
run(async () => {
  await refresh();
  setWorkspaceChrome('openers', true);
  await openPage('openers.html');
});
