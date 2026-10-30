(function (root) {
  'use strict';
  const normalize = (value) => value.replace(/\s+/g, ' ').trim();

  function connect(content, handlers = {}) {
    const blocks = [
      ...content.querySelectorAll('blockquote.blyg-transclusion[data-blyg-id]'),
    ];
    let active = null;
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
            handlers.selection?.(
              index >= 0 ? { mode: 'fragment', fragment: index } : { mode: 'excerpt', text },
            );
            return;
          }
        }
      }
      handlers.selection?.(
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
    const click = (event) => {
      const link = event.target.closest('a[href]');
      if (link) {
        event.preventDefault();
        handlers.link?.({ href: link.href });
        return;
      }
      if (!event.target.closest('.reader-fragment-dot') && getSelection().isCollapsed) {
        active = null;
        showActive();
        reportSelection();
      }
    };
    content.addEventListener('click', click);
    document.addEventListener('selectionchange', reportSelection);
    document.addEventListener('mouseup', reportSelection);
    document.addEventListener('keyup', reportSelection);
    reportSelection();
    return {
      selectFragment(fragment) {
        getSelection().removeAllRanges();
        active = Number.isInteger(fragment) ? fragment : null;
        showActive();
        reportSelection();
        if (active !== null && blocks[active])
          blocks[active].scrollIntoView({ behavior: 'smooth', block: 'center' });
      },
      close() {
        content.removeEventListener('click', click);
        document.removeEventListener('selectionchange', reportSelection);
        document.removeEventListener('mouseup', reportSelection);
        document.removeEventListener('keyup', reportSelection);
      },
    };
  }

  root.BlyngerReaderContent = { connect };
})(window);
