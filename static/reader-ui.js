(function (global) {
  'use strict';

  function syncTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? ''
      : date.toLocaleString(undefined, {
          year: '2-digit',
          month: 'numeric',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
        });
  }

  function savedTime(value) {
    if (!value) return 'Saved before date tracking';
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? 'Saved before date tracking'
      : 'Saved: ' +
          date.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
          });
  }

  function renderActivity(container, items, esc) {
    container.replaceChildren();
    if (!items.length) {
      container.textContent = 'No matching private activity yet.';
      return;
    }
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'reader-row interaction-row';
      const response = item.reaction
        ? ' <b class="activity-reaction">' + esc(item.reaction) + '</b>'
        : '';
      row.innerHTML =
        '<small>' +
        esc(item.at ? new Date(item.at).toLocaleString() : 'Earlier record') +
        (item.backfilled ? ' · from earlier records' : '') +
        '</small><h2>' +
        esc(item.label || item.remote_id) +
        '</h2><p>' +
        esc(item.action) +
        response +
        ' · ' +
        esc(item.host) +
        (item.own_item_id ? ' · your item ' + esc(item.own_item_id.slice(0, 8)) : '') +
        '</p>';
      container.append(row);
    }
  }

  function renderItems(container, items, esc, actions) {
    container.replaceChildren();
    for (const item of items) {
      const native = item.source_type !== 'l0' && item.source_type !== 'web';
      const row = document.createElement('div');
      const stub = item.stub_target
        ? '<p class="reader-stub-summary"><b>Stub of:</b> ' +
          esc(item.stub_target.label) +
          '</p>'
        : '';
      const excerpt = item.excerpt ? '<p>' + esc(item.excerpt) + '</p>' : '';
      row.className = 'reader-row ' + (native ? 'reader-native' : 'reader-web');
      row.innerHTML =
        '<small><b class="reader-source-badge">' +
        (native ? 'BLYG' : 'WEB / RSS') +
        '</b> · ' +
        esc(item.author) +
        ' · ' +
        esc(item.site) +
        ' · ' +
        esc(item.date.slice(0, 10)) +
        (native ? ' · ' + esc(item.kind) + ' · v' + item.version : '') +
        '</small><h2>' +
        esc(item.title) +
        '</h2>' +
        stub +
        excerpt +
        '<button class="read-item">Read</button><button class="quote-item">Quote post</button><button class="save-item">' +
        (item.saved ? 'Saved' : 'Save post') +
        '</button><button class="like-item" title="Like" aria-pressed="' +
        item.liked +
        '">👍</button><span class="private-responses" aria-label="Private responses"></span>' +
        (item.saved
          ? '<small class="saved-at">' + esc(savedTime(item.saved_at)) + '</small>'
          : '');
      row.querySelector('.read-item').onclick = () => actions.read(item);
      row.querySelector('.quote-item').onclick = () => actions.quote(item);
      row.querySelector('.save-item').onclick = () => actions.save(item);
      row.querySelector('.like-item').onclick = () => actions.like(item);
      const responses = row.querySelector('.private-responses');
      for (const emoji of ['🤯', '🙄', '👎', '😂', '❓']) {
        const button = document.createElement('button');
        button.className = 'reaction-item' + (item.reaction === emoji ? ' active' : '');
        button.textContent = emoji;
        button.title = 'Private response ' + emoji;
        button.setAttribute('aria-pressed', item.reaction === emoji);
        button.onclick = () => actions.react(item, emoji);
        responses.append(button);
      }
      container.append(row);
    }
  }

  function openedItem(item, data, esc, shortDate) {
    const native = item.source_type !== 'l0' && item.source_type !== 'web';
    const generated = data.doc.generated || [];
    const pins = (data.doc.changelog || [])
      .filter((change) => change.pinned)
      .map((change) => change.version);
    const disclosure = generated.length
      ? '<details class="reader-generated"><summary><span class="tk-robot" aria-hidden="true"></span> What the author disclosed</summary><p>AI-generated text is self-reported, not verified.</p>' +
        generated
          .map(
            (entry) =>
              '<p><b>Model:</b> ' +
              esc(entry.model || 'not stated') +
              (entry.at ? ' · <b>Generated:</b> ' + esc(shortDate(entry.at)) : '') +
              ' · <b>Sources:</b> ' +
              Number((entry.sources || []).length) +
              '</p>',
          )
          .join('') +
        '</details>'
      : '';
    const backward = data.conversation?.backward
      ? '<button id="readerConversationBack" class="reader-conversation-back">← <b>Backward:</b> ' +
        esc(data.conversation.backward.label) +
        '</button>'
      : '';
    const forward = (data.conversation?.forward || [])
      .map(
        (link, index) =>
          '<button class="reader-conversation-forward" data-forward="' +
          index +
          '"><b>Forward:</b> ' +
          esc(link.label) +
          ' →</button>',
      )
      .join('');
    const html =
      '<div class="reader-opened ' +
      (native ? 'reader-native' : 'reader-web') +
      '"><p class="reader-meta"><b class="reader-source-badge">' +
      (native ? 'BLYG' : 'WEB / RSS') +
      '</b> · ' +
      esc(item.author) +
      ' · ' +
      esc(item.origin) +
      ' · ' +
      esc(item.date.slice(0, 10)) +
      (native ? ' · ' + esc(item.kind) + ' · v' + item.version : '') +
      '</p>' +
      backward +
      disclosure +
      '<iframe id="readerFrame" class="preview-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" title="Imported writing"></iframe>' +
      forward +
      '</div>' +
      (data.fragments?.length
        ? '<div class="reader-fragment-picker"><b>Fragments in this thread</b><div id="readerFragmentChoices" class="reader-fragment-choices"></div></div>'
        : '') +
      '<div class="dialog-actions"><button id="openOriginal">Open original</button>' +
      (pins.length ? '<button id="forkReading">Fork pinned version…</button>' : '') +
      '<button id="quoteReading">Quote</button><button id="stubReading">Stub</button></div>';
    return { html, native, pins };
  }

  global.BlyngerReaderUI = { openedItem, renderActivity, renderItems, savedTime, syncTime };
})(window);
