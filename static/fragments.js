/*
 * Stable fragment anchors live on the article's top-level HTML blocks. The
 * editor also uses a separate data-fragment-block attribute internally; that
 * private attribute and the margin overlays never enter saved HTML.
 */
class FragmentEditor {
  constructor(editor, changed, notify) {
    this.editor = editor;
    this.changed = changed;
    this.notify = notify;
    this.meta = null;
    this.order = [];
    this.ends = new Map();
    this.layer = document.createElement('div');
    this.layer.className = 'fragment-dots';
    editor.parentElement.append(this.layer);
    editor.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        e.stopPropagation();
        this.designate();
        return;
      }
      this.removeTransclusionBeforeCaret(e);
    });
    editor.addEventListener('input', () => {
      if (this.meta) {
        this.assign();
        if (this.meta.purpose === 'openers') this.syncOpeners();
        this.draw();
      }
    });
    editor.addEventListener('scroll', () => this.draw());
    new ResizeObserver(() => this.draw()).observe(editor);
  }
  lockTransclusions() {
    for (const quote of this.editor.querySelectorAll(
      'blockquote.blynger-citation.blyg-transclusion',
    ))
      quote.setAttribute('contenteditable', 'false');
  }
  removeTransclusionBeforeCaret(event) {
    if (event.key !== 'Backspace' || event.ctrlKey || event.metaKey || event.altKey)
      return false;
    const selection = getSelection();
    if (!selection.rangeCount || !selection.isCollapsed) return false;
    const block = this.cursor();
    if (!block || block.parentElement !== this.editor) return false;
    const before = document.createRange();
    before.selectNodeContents(block);
    try {
      before.setEnd(selection.anchorNode, selection.anchorOffset);
    } catch {
      return false;
    }
    if (
      before.toString() ||
      before.cloneContents().querySelector?.('img,audio,video')
    )
      return false;
    const quote = block.previousElementSibling;
    if (!quote?.matches('blockquote.blynger-citation.blyg-transclusion')) return false;
    event.preventDefault();
    quote.remove();
    const caret = document.createRange();
    caret.selectNodeContents(block);
    caret.collapse(true);
    selection.removeAllRanges();
    selection.addRange(caret);
    this.assign();
    if (this.meta?.purpose === 'openers') this.syncOpeners();
    this.draw();
    this.changed();
    return true;
  }
  id() {
    return 'b' + crypto.randomUUID().replaceAll('-', '');
  }
  expandMeta(meta, els) {
    const expanded = structuredClone(meta),
      mapping = new Map(),
      meaningful = (el) => el.textContent.trim() || el.querySelector('img,audio,video,br'),
      signature = (el) => publicImages(el.outerHTML).replace(/\s+/g, ' ').trim();
    const actual = els.filter(meaningful),
      plans = [];
    for (const block of expanded.blocks || []) {
      const holder = document.createElement('div');
      holder.innerHTML = block.html;
      plans.push({ id: block.id, children: [...holder.children].filter(meaningful) });
    }
    const expected = plans.flatMap((plan) => plan.children);
    if (
      expected.length !== actual.length ||
      expected.some((el, i) => signature(el) !== signature(actual[i]))
    )
      return null;
    const ids = new Map(),
      used = new Set();
    let cursor = 0;
    for (const plan of plans) {
      const first = actual[cursor];
      if (first) {
        ids.set(first, plan.id);
        used.add(plan.id);
        mapping.set(plan.id, plan.id);
      }
      cursor += plan.children.length;
    }
    const blocks = els.map((el) => {
      let id = ids.get(el);
      if (!id) {
        do {
          id = this.id();
        } while (used.has(id));
        used.add(id);
      }
      return { id, html: publicImages(el.outerHTML) };
    });
    expanded.blocks = blocks;
    expanded.dividers = (expanded.dividers || []).map((id) => mapping.get(id) || id);
    for (const range of expanded.ranges || []) {
      range.start = mapping.get(range.start) || range.start;
      if (range.end !== null) range.end = mapping.get(range.end) || range.end;
    }
    return expanded;
  }
  syncHeadingDividers() {
    if (!this.meta || this.meta.purpose === 'openers') return false;
    let changed = false;
    for (const heading of this.editor.querySelectorAll(':scope > h2')) {
      const id = heading.dataset.fragmentBlock;
      if (id && !this.meta.dividers.includes(id)) {
        this.meta.dividers.push(id);
        changed = true;
      }
    }
    if (changed) {
      const prior = this.meta.ranges || [];
      this.meta.ranges = this.sections().map((range) => ({
        ...range,
        key: prior.find((old) => old.start === range.start)?.key || range.start,
      }));
      this.meta.ordinary = [];
    }
    return changed;
  }
  excluded(el) {
    const t = (el.innerText || el.textContent).trim(),
      author = (
        document.querySelector('meta[name="blynger-author"]')?.content || ''
      ).trim();
    return (
      t.includes('![[') ||
      el.matches('blockquote.blyg-transclusion,blockquote.blynger-citation') ||
      !!el.querySelector('blockquote.blyg-transclusion,blockquote.blynger-citation') ||
      el.matches('.blynger-series-title,.blynger-series-next') ||
      el.matches('h1') ||
      (author &&
        new RegExp(
          '^(?:[—–-]\\s*)?(?:By\\s+)?' +
            author.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') +
            '\\b',
          'i',
        ).test(t)) ||
      /^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}$/.test(
        t,
      )
    );
  }
  assign() {
    // Only opt-in posts acquire anchors; legacy prose remains untouched.
    for (const n of [...this.editor.childNodes])
      if (n.nodeType === 3 && n.textContent.trim()) {
        const p = document.createElement('p');
        n.replaceWith(p);
        p.append(n);
      }
    const seen = new Set();
    for (const el of this.editor.children) {
      let id = el.dataset.fragmentBlock || el.dataset.blyngerBlock;
      if (!id || seen.has(id)) el.dataset.fragmentBlock = id = this.id();
      else el.dataset.fragmentBlock = id;
      seen.add(id);
    }
    const order = [...this.editor.children].map((e) => e.dataset.fragmentBlock);
    let repaired = false;
    if (this.meta) {
      // A contenteditable merge or deletion can remove the paragraph carrying a
      // private boundary. Move that boundary to the next surviving paragraph (or
      // remove it at the end) so an invisible editor anchor can never trap prose.
      const priorOrder = this.order.slice(),
        live = new Set(order),
        next = (id) => {
          const at = priorOrder.indexOf(id);
          if (at < 0) return null;
          for (let i = at + 1; i < priorOrder.length; i++)
            if (live.has(priorOrder[i])) return priorOrder[i];
          return null;
        };
      if (priorOrder.length) {
        const dividers = [];
        for (const id of this.meta.dividers || []) {
          const replacement = live.has(id) ? id : next(id);
          if (replacement !== id) repaired = true;
          const el =
            replacement &&
            [...this.editor.children].find((n) => n.dataset.fragmentBlock === replacement);
          if (el && !this.excluded(el) && !dividers.includes(replacement))
            dividers.push(replacement);
          else if (replacement) repaired = true;
        }
        this.meta.dividers = dividers;
        const ranges = [];
        for (const original of this.meta.ranges || []) {
          let start = original.start,
            end = original.end;
          if (!live.has(start)) {
            start = next(start);
            repaired = true;
          }
          if (end !== null && !live.has(end)) {
            end = next(end);
            repaired = true;
          }
          const a = start ? order.indexOf(start) : -1,
            z = end ? order.indexOf(end) : order.length;
          if (a < 0 || z <= a) {
            repaired = true;
            continue;
          }
          ranges.push({ ...original, start, end });
        }
        this.meta.ranges = ranges;
        if (this.meta.ordinary)
          this.meta.ordinary = [
            ...new Set(
              this.meta.ordinary
                .map((id) => (live.has(id) ? id : next(id)))
                .filter(Boolean),
            ),
          ];
      }
      const oldShared = this.order.filter((id) => order.includes(id)),
        newShared = order.filter((id) => this.order.includes(id));
      if (oldShared.join() !== newShared.join())
        for (const r of this.meta.ranges) {
          const last = this.ends.get(r.key);
          if (last && order.includes(last) && order.indexOf(last) >= order.indexOf(r.start))
            r.end = order[order.indexOf(last) + 1] || null;
        }
      this.ends = new Map(
        this.meta.ranges.map((r) => [
          r.key,
          order[(r.end ? order.indexOf(r.end) : order.length) - 1],
        ]),
      );
      if (repaired)
        this.notify(
          'Blynger repaired a fragment break after its paragraph was removed. Your writing is unchanged.',
        );
    }
    this.order = order;
  }
  writeMarkers() {
    if (!this.meta) return;
    const elements = [...this.editor.children],
      byId = new Map(elements.map((el) => [el.dataset.fragmentBlock, el])),
      ids = elements.map((el) => el.dataset.fragmentBlock);
    for (const el of elements) {
      el.removeAttribute('data-blynger-fragment');
      el.removeAttribute('data-blynger-break');
      el.dataset.blyngerBlock = el.dataset.fragmentBlock;
    }
    for (const range of this.meta.ranges || []) {
      const start = ids.indexOf(range.start),
        end = range.end ? ids.indexOf(range.end) : ids.length;
      if (start < 0 || end <= start) continue;
      for (let i = start; i < end; i++) elements[i].dataset.blyngerFragment = range.key;
    }
    for (const id of this.meta.dividers || [])
      byId.get(id)?.setAttribute('data-blynger-break', '');
  }
  load(meta) {
    this.order = [];
    this.ends = new Map();
    this.meta = meta ? structuredClone(meta) : null;
    this.lockTransclusions();
    let repaired = false;
    if (this.meta) {
      const els = [...this.editor.children];
      if (els.length !== this.meta.blocks.length) {
        const expanded = this.expandMeta(this.meta, els);
        if (expanded) {
          this.meta = expanded;
          repaired = true;
        } else {
          this.notify('Fragment layout changed; review boundaries before saving.');
          return false;
        }
      }
      els.forEach((el, i) => (el.dataset.fragmentBlock = this.meta.blocks[i].id));
      this.assign();
      if (this.meta.purpose === 'openers') this.syncOpeners();
      if (repaired) {
        this.changed();
        this.notify(
          'Blynger repaired the page structure. Your writing and reusable fragment choices are unchanged.',
        );
      }
    }
    this.draw();
    return repaired;
  }
  replace(html) {
    const previous = this.meta?.blocks || [],
      queues = new Map(),
      used = new Set();
    const signature = (value) => publicImages(value).replace(/\s+/g, ' ').trim();
    for (const block of previous) {
      const key = signature(block.html);
      if (!queues.has(key)) queues.set(key, []);
      queues.get(key).push(block.id);
    }
    this.editor.innerHTML = html;
    const els = [...this.editor.children];
    for (const el of els) {
      const queue = queues.get(signature(el.outerHTML));
      if (queue?.length) {
        el.dataset.fragmentBlock = queue.shift();
        used.add(el.dataset.fragmentBlock);
      }
    }
    if (els.length === previous.length)
      els.forEach((el, i) => {
        if (!el.dataset.fragmentBlock && !used.has(previous[i].id)) {
          el.dataset.fragmentBlock = previous[i].id;
          used.add(previous[i].id);
        }
      });
    this.lockTransclusions();
    this.assign();
    if (this.meta?.purpose === 'openers') this.syncOpeners();
    this.draw();
  }
  activate() {
    if (!this.meta) {
      this.assign();
      this.meta = { version: 1, blocks: [], dividers: [], ranges: [] };
    }
    this.assign();
  }
  serialize() {
    if (this.meta) {
      this.assign();
      if (this.meta.purpose === 'openers') this.syncOpeners();
      this.writeMarkers();
    }
    const c = this.editor.cloneNode(true);
    for (const el of c.querySelectorAll('[data-fragment-block]'))
      el.removeAttribute('data-fragment-block');
    for (const el of c.querySelectorAll(
      'blockquote.blynger-citation.blyg-transclusion[contenteditable]',
    ))
      el.removeAttribute('contenteditable');
    if (this.meta)
      this.meta.blocks = [...this.editor.children].map((el) => {
        const block = el.cloneNode(true);
        for (const n of [block, ...block.querySelectorAll('*')]) {
          n.removeAttribute('data-fragment-block');
          n.removeAttribute('data-blynger-block');
          n.removeAttribute('data-blynger-fragment');
          n.removeAttribute('data-blynger-break');
        }
        for (const n of [
          block,
          ...block.querySelectorAll(
            'blockquote.blynger-citation.blyg-transclusion[contenteditable]',
          ),
        ])
          if (n.matches?.('blockquote.blynger-citation.blyg-transclusion'))
            n.removeAttribute('contenteditable');
        return { id: el.dataset.fragmentBlock, html: publicImages(block.outerHTML) };
      });
    return {
      html: publicImages(c.innerHTML),
      fragments: this.meta ? structuredClone(this.meta) : null,
    };
  }
  html() {
    return this.serialize().html;
  }
  snapshot() {
    return this.serialize().fragments;
  }
  clearAll() {
    this.meta = null;
    this.order = [];
    this.ends = new Map();
    for (const el of this.editor.querySelectorAll('*')) {
      el.removeAttribute('data-fragment-block');
      el.removeAttribute('data-blynger-block');
      el.removeAttribute('data-blynger-fragment');
      el.removeAttribute('data-blynger-break');
    }
    this.draw();
    this.changed();
  }
  cursor() {
    const s = getSelection();
    if (!s.rangeCount || !this.editor.contains(s.anchorNode)) return null;
    let n = s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement;
    while (n && n.parentElement !== this.editor && n !== this.editor) n = n.parentElement;
    return n === this.editor ? this.editor.children[s.anchorOffset] || null : n;
  }
  boundary() {
    const s = getSelection();
    if (!s.rangeCount || !s.isCollapsed || !this.editor.contains(s.anchorNode)) return null;
    const r = s.getRangeAt(0);
    if (r.startContainer === this.editor)
      return this.editor.children[r.startOffset] || null;
    const el = this.cursor();
    if (!el) return null;
    const before = r.cloneRange();
    before.selectNodeContents(el);
    before.setEnd(r.startContainer, r.startOffset);
    const after = r.cloneRange();
    after.selectNodeContents(el);
    after.setStart(r.startContainer, r.startOffset);
    if (
      !before.toString().trim() &&
      !before.cloneContents().querySelector('img,video,audio')
    )
      return el;
    if (!after.toString().trim() && !after.cloneContents().querySelector('img,video,audio'))
      return el.nextElementSibling;
    return null;
  }
  addDivider() {
    if (this.meta?.purpose === 'openers') {
      this.notify(
        'Each dated Opener is already a fragment. Use New opener to begin another.',
      );
      return;
    }
    const el = this.cursor();
    if (!el || this.excluded(el)) {
      this.notify(
        'Place the cursor in a body paragraph. Titles, signatures, and dates are excluded.',
      );
      return;
    }
    this.activate();
    const id = el.dataset.fragmentBlock;
    const i = this.meta.dividers.indexOf(id);
    if (i >= 0) {
      this.notify('This paragraph already starts a fragment.');
      return;
    }
    const ids = [...this.editor.children].map((e) => e.dataset.fragmentBlock),
      pos = ids.indexOf(id);
    const containing = this.meta.ranges.find(
      (r) => ids.indexOf(r.start) < pos && (r.end ? ids.indexOf(r.end) : ids.length) > pos,
    );
    this.meta.dividers.push(id);
    if (containing) {
      const end = containing.end;
      containing.end = id;
      this.meta.ranges.push({ key: id, start: id, end });
    }
    const prior = this.meta.ranges;
    this.meta.ranges = this.sections().map((r) => ({
      ...r,
      key: prior.find((x) => x.start === r.start)?.key || r.start,
    }));
    this.meta.ordinary = [];
    this.changed();
    this.draw();
    this.notify('Fragment added. These sections are reusable fragments.');
  }
  removeDivider() {
    if (this.meta?.purpose === 'openers') {
      this.notify('Opener fragments are automatic.');
      return;
    }
    const el = this.cursor();
    if (!el || !this.meta) {
      this.notify('Place the cursor in a paragraph that starts a fragment.');
      return;
    }
    this.assign();
    const id = el.dataset.fragmentBlock,
      i = this.meta.dividers.indexOf(id);
    if (i < 0) {
      this.notify('This paragraph does not start a fragment.');
      return;
    }
    this.meta.dividers.splice(i, 1);
    const left = this.meta.ranges.find((r) => r.end === id),
      right = this.meta.ranges.find((r) => r.start === id);
    if (left && right) {
      left.end = right.end;
      this.meta.ranges = this.meta.ranges.filter((r) => r !== right);
    }
    const prior = this.meta.ranges;
    this.meta.ranges = this.sections().map((r) => ({
      ...r,
      key: prior.find((x) => x.start === r.start)?.key || r.start,
    }));
    this.changed();
    this.draw();
    this.notify('Fragment removed. Adjacent sections merged.');
  }
  toggleDivider() {
    this.addDivider();
  }
  sections() {
    const els = [...this.editor.children];
    const out = [];
    let start = null;
    for (let i = 0; i <= els.length; i++) {
      const el = els[i];
      if (
        i === els.length ||
        this.excluded(el) ||
        el?.matches('h2') ||
        this.meta.dividers.includes(el.dataset.fragmentBlock)
      ) {
        if (start !== null)
          out.push({
            start: els[start].dataset.fragmentBlock,
            end: el?.dataset.fragmentBlock || null,
          });
        start = null;
      }
      if (el && !this.excluded(el) && start === null) start = i;
    }
    return out;
  }
  designate() {
    if (this.meta?.purpose === 'openers') {
      this.notify('Every Opener is automatically a fragment.');
      return;
    }
    const el = this.cursor();
    if (!el || this.excluded(el)) {
      this.notify('Place the cursor in body prose. Titles and signatures are excluded.');
      return;
    }
    this.activate();
    const ids = [...this.editor.children].map((e) => e.dataset.fragmentBlock),
      i = ids.indexOf(el.dataset.fragmentBlock);
    const r = this.meta.ranges.find(
      (r) => ids.indexOf(r.start) <= i && (r.end ? ids.indexOf(r.end) : ids.length) > i,
    );
    if (r) {
      this.meta.ranges = this.meta.ranges.filter((x) => x !== r);
      this.meta.ordinary = [...new Set([...(this.meta.ordinary || []), r.start])];
      this.notify('Section is ordinary prose. Any published fragment remains available.');
    } else {
      const section = this.sections().find(
        (r) => ids.indexOf(r.start) <= i && (r.end ? ids.indexOf(r.end) : ids.length) > i,
      );
      if (!section) return;
      this.meta.ranges.push({ key: section.start, ...section });
      this.meta.ordinary = (this.meta.ordinary || []).filter((id) => id !== section.start);
      this.notify('Section designated as a reusable fragment.');
    }
    this.changed();
    this.draw();
  }
  removeDesignation() {
    if (this.meta?.purpose === 'openers') {
      this.notify('Opener fragments are automatic.');
      return;
    }
    const el = this.cursor();
    if (!el || !this.meta) {
      this.notify('Place the cursor in a reusable fragment.');
      return;
    }
    this.assign();
    const ids = [...this.editor.children].map((node) => node.dataset.fragmentBlock),
      position = ids.indexOf(el.dataset.fragmentBlock),
      range = this.meta.ranges.find(
        (candidate) =>
          ids.indexOf(candidate.start) <= position &&
          (candidate.end ? ids.indexOf(candidate.end) : ids.length) > position,
      );
    if (!range) {
      this.notify('This section is already ordinary prose.');
      return;
    }
    this.meta.ranges = this.meta.ranges.filter((candidate) => candidate !== range);
    this.meta.ordinary = [...new Set([...(this.meta.ordinary || []), range.start])];
    this.changed();
    this.draw();
    this.notify('Section is ordinary prose. Any previously published fragment remains available.');
  }
  insertTK(content, selected) {
    const e = this.editor;
    e.focus();
    const selection = getSelection();
    let r =
      selected && e.contains(selected.startContainer) && e.contains(selected.endContainer)
        ? selected.cloneRange()
        : null;
    if (!r) {
      r = document.createRange();
      r.selectNodeContents(e);
      r.collapse(false);
    }
    const top = (n) => {
      if (n.nodeType !== 1) n = n.parentElement;
      while (n && n !== e && n.parentElement !== e) n = n.parentElement;
      return n === e ? null : n;
    };
    const first = top(r.startContainer),
      last = top(r.endContainer);
    if ((first && this.excluded(first)) || (last && this.excluded(last))) {
      this.notify('Insert TK in the post body, outside the title and signature.');
      return false;
    }
    r.deleteContents();
    let block = top(r.startContainer);
    const holder = document.createElement('div');
    holder.innerHTML = content;
    const generated = holder.firstElementChild;
    if (block) {
      const tailRange = r.cloneRange();
      tailRange.setEndAfter(block.lastChild || block);
      const tail = block.cloneNode(false);
      tail.removeAttribute('data-fragment-block');
      tail.removeAttribute('data-blynger-block');
      tail.removeAttribute('data-blynger-fragment');
      tail.removeAttribute('data-blynger-break');
      tail.append(tailRange.extractContents());
      block.after(generated);
      if (tail.textContent.trim() || tail.querySelector('img,video,audio'))
        generated.after(tail);
      if (!block.textContent.trim() && !block.querySelector('img,video,audio')) {
        if (tail.isConnected) tail.dataset.fragmentBlock = block.dataset.fragmentBlock;
        block.remove();
      }
    } else r.insertNode(generated);
    this.assign();
    const caret = document.createRange();
    caret.selectNodeContents(generated);
    caret.collapse(false);
    selection.removeAllRanges();
    selection.addRange(caret);
    this.tk();
    return generated;
  }
  tk() {
    if (this.meta?.purpose === 'openers') {
      this.assign();
      this.syncOpeners();
      this.changed();
      this.draw();
      this.notify('TK added to this Opener. Its fragment identity is preserved.');
      return;
    }
    if (this.meta) this.assign();
    this.changed();
    this.draw();
    this.notify('TK added inside this thread. It does not create additional feed items.');
  }
  isOpenerHeading(el) {
    return el.matches('h3') || (el.matches('strong') && this.excluded(el));
  }
  syncOpeners() {
    const els = [...this.editor.children],
      headings = els
        .map((el, i) => (this.isOpenerHeading(el) ? i : -1))
        .filter((i) => i >= 0),
      prior = this.meta.ranges;
    this.meta.ranges = headings.flatMap((i, pos) => {
      const end = headings[pos + 1] ?? els.length;
      if (i + 1 === end) return [];
      const heading = els[i].dataset.fragmentBlock;
      const old = prior.find((r) => r.heading === heading) || {};
      return [
        {
          ...old,
          key: old.key || heading,
          heading,
          start: els[i + 1].dataset.fragmentBlock,
          end: els[end]?.dataset.fragmentBlock || null,
          date_label: els[i].textContent.trim(),
          legacy_anchor: els[i].getAttribute('id'),
        },
      ];
    });
    this.meta.dividers = headings.map((i) => els[i].dataset.fragmentBlock);
  }
  roman(number) {
    let out = '';
    for (const [n, r] of [
      [1000, 'M'],
      [900, 'CM'],
      [500, 'D'],
      [400, 'CD'],
      [100, 'C'],
      [90, 'XC'],
      [50, 'L'],
      [40, 'XL'],
      [10, 'X'],
      [9, 'IX'],
      [5, 'V'],
      [4, 'IV'],
      [1, 'I'],
    ])
      while (number >= n) {
        out += r;
        number -= n;
      }
    return out;
  }
  openerDate() {
    return new Date().toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }
  dayKey(text) {
    const m = text
      .trim()
      .match(/^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})(?:[\s,]+[IVXLCDM]+)?$/i);
    return m ? m[3] + '-' + m[1].toLowerCase() + '-' + Number(m[2]) : null;
  }
  newOpener(text, options = {}) {
    if (this.meta?.purpose !== 'openers' || !text.trim()) return false;
    const date = this.openerDate(),
      day = this.dayKey(date),
      heads = [...this.editor.children].filter((el) => this.isOpenerHeading(el));
    const sameDay = heads.filter((el) => this.dayKey(el.textContent) === day);
    // Oldest entry is I. Public anchors and shared fragment keys remain unchanged.
    sameDay
      .slice()
      .reverse()
      .forEach((el, i) => (el.textContent = date + ', ' + this.roman(i + 1)));
    const h = document.createElement('h3');
    h.id = 'opener-' + crypto.randomUUID();
    h.textContent = date + (sameDay.length ? ', ' + this.roman(sameDay.length + 1) : '');
    const paragraphs = text
      .trim()
      .split(/\n\s*\n/)
      .map((part) => {
        const p = document.createElement('p');
        part.split('\n').forEach((line, i) => {
          if (i) p.append(document.createElement('br'));
          p.append(document.createTextNode(line));
        });
        return p;
      });
    const context = [];
    if (options.stub_html) {
      const holder = document.createElement('div');
      holder.innerHTML = options.stub_html;
      context.push(...holder.children);
    }
    const first = heads[0],
      content = [...context, ...paragraphs];
    if (first) first.before(h, ...content);
    else this.editor.append(h, ...content);
    this.assign();
    this.syncOpeners();
    const opener = this.meta.ranges.find(
      (range) => range.heading === h.dataset.fragmentBlock,
    );
    if (opener && options.stub_of) opener.stub_of = structuredClone(options.stub_of);
    if (opener && options.pin_on_publish) opener.pin_on_publish = true;
    this.editor.focus();
    const r = document.createRange();
    r.selectNodeContents(paragraphs[0]);
    r.collapse(false);
    getSelection().removeAllRanges();
    getSelection().addRange(r);
    h.scrollIntoView({ block: 'nearest' });
    this.changed();
    this.draw();
    return opener || true;
  }
  draw() {
    this.layer.replaceChildren();
    if (!this.meta || this.editor.hidden) return;
    const box = this.editor.getBoundingClientRect(),
      parent = this.editor.parentElement.getBoundingClientRect();
    const ids = new Set(this.meta.dividers);
    for (const el of this.editor.children) {
      if (!ids.has(el.dataset.fragmentBlock)) continue;
      const y = el.getBoundingClientRect().top;
      if (y < box.top || y > box.bottom) continue;
      const dot = document.createElement('span');
      dot.className = 'fragment-dot';
      const label = this.meta.purpose === 'openers' ? 'Fragment' : 'Fragment divider';
      dot.title = label;
      dot.setAttribute('aria-label', label);
      dot.style.top = y - parent.top + 'px';
      dot.style.left = box.right - parent.left - 15 + 'px';
      this.layer.append(dot);
    }
  }
}
