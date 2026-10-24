// Run with NODE_PATH pointing to the existing Playwright installation; no app dependency.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.BLYNGER_BROWSER ||
      '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.setContent(
      '<style>#editor{width:600px;height:500px;overflow:auto} .fragment-dots{position:absolute}</style><section><div id="editor" contenteditable="true"><h1>Title</h1><p>Before TK.</p><p>Another paragraph.</p><p>After TK.</p><p>—Example Author<br>September 26, 2026</p></div></section>',
    );
    await page.addScriptTag({ content: 'function publicImages(s){return s;}' });
    await page.addScriptTag({ path: path.join(__dirname, 'static/fragments.js') });
    const result = await page.evaluate(() => {
      let dirty = 0;
      const editor = document.getElementById('editor');
      window.f = new FragmentEditor(
        editor,
        () => dirty++,
        () => {},
      );
      const at = (el, n = 0) => {
        const r = document.createRange();
        r.setStart(el.firstChild || el, n);
        r.collapse(true);
        getSelection().removeAllRanges();
        getSelection().addRange(r);
      };
      at(editor.children[2]);
      const height = editor.scrollHeight;
      const event = new KeyboardEvent('keydown', {
        key: 'F',
        ctrlKey: true,
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      });
      editor.dispatchEvent(event);
      if (!event.defaultPrevented) throw Error('Find not prevented');
      if (f.meta.ranges.length !== 1) throw Error('Designate reusable fragment');
      editor.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'f',
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
      if (f.meta.ranges.length !== 0) throw Error('Fragment shortcut did not toggle designation');
      f.designate();
      if (f.meta.ranges.length !== 1) throw Error('Restore designation failed');
      f.removeDesignation();
      if (f.meta.ranges.length) throw Error('Make ordinary prose failed');
      f.designate();
      at(editor.children[1]);
      if (f.meta.ranges.length !== 1) throw Error('Designate implicit edges');
      const saved = f.snapshot(),
        html = f.html();
      if (/data-fragment-block|fragment-dot/.test(html)) throw Error('Private data leaked');
      if (!/data-blynger-block/.test(html) || !/data-blynger-fragment/.test(html))
        throw Error('Durable fragment markers missing');
      editor.innerHTML = html;
      f.load(saved);
      if (JSON.stringify(f.snapshot()) !== JSON.stringify(saved)) throw Error('Roundtrip');
      if (editor.scrollHeight !== height) throw Error('Layout changed');
      at(editor.children[2], 8);
      f.insertTK(
        '<div class="blyg-tk-gen"><p>Generated prose.</p></div>',
        getSelection().getRangeAt(0),
      );
      const tk = f.snapshot();
      if (tk.ranges.length !== 1) throw Error('TK created extra feed items');
      if (!f.html().includes('Another ') || !f.html().includes('paragraph.'))
        throw Error('Mid-paragraph TK lost prose');
      const keys = tk.ranges.map((r) => r.key);
      const after = tk.ranges[0];
      const moving = [...editor.children].filter((el) => {
        const ids = tk.blocks.map((b) => b.id),
          i = ids.indexOf(el.dataset.fragmentBlock);
        return i >= ids.indexOf(after.start) && i < ids.indexOf(after.end);
      });
      const anchor = editor.children[1];
      for (const el of moving) editor.insertBefore(el, anchor);
      f.assign();
      const reordered = f.snapshot();
      if (reordered.ranges.map((r) => r.key).join() !== keys.join())
        throw Error('Reorder lost identities');
      const marked = f.html();
      for (const key of keys)
        if (!marked.includes(`data-blynger-fragment="${key}"`))
          throw Error('Moved fragment lost its durable identity');
      editor.innerHTML = '<h3>October 23, 2026, 2:35 PM</h3><p>Earlier opener.</p>';
      f.meta = { purpose: 'openers', blocks: [], ranges: [], dividers: [], ordinary: [] };
      f.assign();
      f.syncOpeners();
      if (!f.newOpener('New opener.')) throw Error('New opener was not added');
      if (editor.firstElementChild.textContent === 'October 23, 2026, 2:35 PM')
        throw Error('New opener was not inserted at the top');
      return {
        saved,
        tk: reordered,
        html: reordered.blocks.map((b) => b.html).join(''),
        dirty,
        children: [...editor.children].map((e) => e.outerHTML),
      };
    });
    fs.writeFileSync(
      '/private/tmp/blynger-fragment-browser-result.json',
      JSON.stringify(result, null, 2),
    );
    assert.equal(result.tk.ranges.length, 1);
    assert.ok(!result.tk.ranges.some((r) => r.start === result.tk.blocks[0].id));
    console.log(
      'Browser checks passed: explicit reusable-fragment designation, removal, persistence, TK containment, no layout shift or metadata leakage.',
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
