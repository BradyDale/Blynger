(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BlyngerDialogue = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const marker = /^\s*(You(?:\s+said)?|Me|Brady(?:\s+Dale)?|ChatGPT(?:\s+said)?|Assistant|GPT)\s*:\s*(.*)$/i;
  const roleFor = (label) =>
    /^(?:chatgpt|assistant|gpt)/i.test(label.trim()) ? 'assistant' : 'author';

  function parseMarkedText(value) {
    const text = String(value || '').replace(/\r\n?/g, '\n').trim();
    if (!text) return [];
    const turns = [];
    let current = null;
    for (const line of text.split('\n')) {
      const match = marker.exec(line);
      if (match) {
        if (current && current.text.trim()) turns.push(current);
        current = { role: roleFor(match[1]), text: match[2] };
      } else if (current) current.text += (current.text ? '\n' : '') + line;
    }
    if (current && current.text.trim()) turns.push(current);
    if (turns.length) return turns;
    // Paragraph breaks are not speaker boundaries. Never manufacture roles
    // when the clipboard omitted both structural metadata and visible labels.
    return [];
  }

  function parseRichHtml(value) {
    if (!value || typeof DOMParser === 'undefined') return [];
    const doc = new DOMParser().parseFromString(String(value), 'text/html');
    const candidates = [...doc.querySelectorAll('[data-message-author-role]')].filter(
      (node) => !node.parentElement?.closest('[data-message-author-role]'),
    );
    const turns = [];
    for (const node of candidates) {
      const sourceRole = String(node.getAttribute('data-message-author-role') || '');
      if (!['user', 'assistant'].includes(sourceRole)) continue;
      const content =
        node.querySelector('.markdown, .prose, [class*="markdown"]') || node;
      const copy = content.cloneNode(true);
      for (const unwanted of copy.querySelectorAll(
        'button,script,style,form,textarea,input,svg,[aria-hidden="true"]',
      ))
        unwanted.remove();
      const text = [...copy.childNodes]
        .map((child) => child.textContent.trim())
        .filter(Boolean)
        .join('\n\n');
      if (!text) continue;
      turns.push({
        role: sourceRole === 'assistant' ? 'assistant' : 'author',
        html: copy.innerHTML,
        text,
      });
    }
    return turns;
  }

  function parseClipboard(text, rich) {
    const richTurns = parseRichHtml(rich);
    return richTurns.length ? richTurns : parseMarkedText(text);
  }

  function transcript(editor, excluded) {
    const turns = [];
    for (const node of editor?.children || []) {
      if (excluded?.(node)) continue;
      const text = (node.innerText || node.textContent || '').trim();
      if (!text) continue;
      const role = node.classList?.contains('blyg-tk-gen') ? 'assistant' : 'author';
      if (turns.length && turns[turns.length - 1].role === role)
        turns[turns.length - 1].text += '\n\n' + text;
      else turns.push({ role, text });
    }
    return turns
      .map((turn) => (turn.role === 'assistant' ? 'ASSISTANT' : 'AUTHOR') + ':\n' + turn.text)
      .join('\n\n');
  }

  return { parseMarkedText, parseRichHtml, parseClipboard, transcript };
});
