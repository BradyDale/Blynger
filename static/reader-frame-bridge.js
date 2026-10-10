(() => {
  'use strict';
  const channel = document.body.dataset.channel;
  const content = document.getElementById('readerContent');
  const send = (type, detail = {}) =>
    parent.postMessage({ source: 'blynger-reader', channel, type, ...detail }, '*');
  const blocks = [
    ...content.querySelectorAll('blockquote.blyg-transclusion[data-blyg-id]'),
  ];
  let active = null;
  const normalize = (value) => value.replace(/\s+/g, ' ').trim();
  const showActive = () =>
    blocks.forEach((node, index) =>
      node.classList.toggle('reader-selected', index === active),
    );
  const reportSelection = () => {
    const selection = getSelection();
    if (selection && selection.rangeCount && !selection.isCollapsed) {
      const range = selection.getRangeAt(0);
      if (content.contains(range.startContainer) && content.contains(range.endContainer)) {
        const text = selection.toString();
        if (text.trim()) {
          const index = blocks.findIndex(
            (node) =>
              node.contains(range.startContainer) &&
              node.contains(range.endContainer) &&
              normalize(text) === normalize(node.innerText),
          );
          active = null;
          showActive();
          send(
            'selection',
            index >= 0 ? { mode: 'fragment', fragment: index } : { mode: 'excerpt', text },
          );
          return;
        }
      }
    }
    send(
      'selection',
      active === null ? { mode: 'whole' } : { mode: 'fragment', fragment: active },
    );
  };
  for (const [index, node] of blocks.entries()) {
    node.classList.add('reader-source-fragment');
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'reader-fragment-dot';
    dot.title = 'Select source fragment';
    dot.setAttribute('aria-label', 'Select source fragment');
    dot.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      getSelection().removeAllRanges();
      active = index;
      showActive();
      reportSelection();
    });
    node.append(dot);
  }
  content.addEventListener('click', (event) => {
    const link = event.target.closest('a[href]');
    if (link) {
      event.preventDefault();
      send('link', { href: link.href });
      return;
    }
    if (!event.target.closest('.reader-fragment-dot') && getSelection().isCollapsed) {
      active = null;
      showActive();
      reportSelection();
    }
  });
  document.addEventListener('selectionchange', reportSelection);
  document.addEventListener('mouseup', reportSelection);
  document.addEventListener('keyup', reportSelection);
  addEventListener('message', (event) => {
    const data = event.data || {};
    if (
      event.source !== parent ||
      data.source !== 'blynger-app' ||
      data.channel !== channel
    )
      return;
    if (data.type === 'select-fragment') {
      getSelection().removeAllRanges();
      active = Number.isInteger(data.fragment) ? data.fragment : null;
      showActive();
      reportSelection();
      if (active !== null && blocks[active])
        blocks[active].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
  send('ready', { fragments: blocks.length });
  reportSelection();
})();
