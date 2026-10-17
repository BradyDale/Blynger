const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.setContent(
      '<section><div id="editor" contenteditable="true"><h1>Title</h1><p>First fragment.</p><p>Second fragment.</p><p>Last paragraph.</p><p>—Example Author<br>October 2, 2026</p></div></section>',
    );
    await page.addScriptTag({ content: 'function publicImages(s){return s;}' });
    await page.addScriptTag({ path: path.join(__dirname, 'static/fragments.js') });
    const result = await page.evaluate(() => {
      const notices = [],
        editor = document.getElementById('editor');
      const f = new FragmentEditor(
        editor,
        () => {},
        (message) => notices.push(message),
      );
      const at = (el) => {
        const r = document.createRange();
        r.selectNodeContents(el);
        r.collapse(true);
        getSelection().removeAllRanges();
        getSelection().addRange(r);
      };
      at(editor.children[2]);
      f.designate();
      const before = f.snapshot(),
        lost = before.ranges[0].start,
        oldKey = before.ranges[0].key;
      editor.querySelector('[data-fragment-block="' + lost + '"]').remove();
      editor.dispatchEvent(
        new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }),
      );
      const after = f.snapshot(),
        ids = new Set(after.blocks.map((block) => block.id));
      return {
        after,
        lost,
        oldKey,
        notices,
        allRangesLive: after.ranges.every(
          (range) => ids.has(range.start) && (range.end === null || ids.has(range.end)),
        ),
      };
    });
    if (!result.allRangesLive) throw Error('Deleted fragment boundary was not repaired');
    if (!result.after.ranges.some((range) => range.key === result.oldKey))
      throw Error('Repair lost fragment identity');
    if (!result.notices.some((message) => message.includes('repaired')))
      throw Error('Repair was not explained');
    const headings = await page.evaluate(() => {
      const editor = document.getElementById('editor'),
        notices = [];
      editor.innerHTML =
        '<h1>Title</h1><p>Introduction.</p><p><ul><li>List thought.</li></ul><h2>Second thought</h2><p>Body two.</p><h2>Third thought</h2><p>Body three.</p></p>';
      const meta = {
        version: 1,
        blocks: [
          { id: 'title', html: '<h1>Title</h1>' },
          { id: 'intro', html: '<p>Introduction.</p>' },
          {
            id: 'legacy',
            html: '<p><ul><li>List thought.</li></ul><h2>Second thought</h2><p>Body two.</p><h2>Third thought</h2><p>Body three.</p></p>',
          },
        ],
        dividers: ['intro', 'legacy'],
        ranges: [
          { key: 'intro-key', start: 'intro', end: 'legacy' },
          { key: 'legacy-key', start: 'legacy', end: null },
        ],
      };
      let dirty = 0;
      const f = new FragmentEditor(
        editor,
        () => dirty++,
        (message) => notices.push(message),
      );
      f.load(meta);
      const after = f.snapshot();
      const h2 = [...editor.querySelectorAll(':scope > h2')].map(
        (el) => el.dataset.fragmentBlock,
      );
      return { after, h2, dirty, notices, text: editor.innerText };
    });
    if (headings.h2.some((id) => headings.after.dividers.includes(id)))
      throw Error('H2 headings silently became fragment boundaries');
    if (!headings.after.ranges.some((range) => range.key === 'legacy-key'))
      throw Error('Expanded legacy block lost fragment identity');
    if (
      headings.dirty !== 1 ||
      !headings.notices.some((message) => message.includes('repaired'))
    )
      throw Error('Automatic structural repair was not surfaced as an unsaved change');
    if (!headings.text.includes('List thought.') || !headings.text.includes('Body three.'))
      throw Error('Structural repair lost authored prose');
    const tkSave = await page.evaluate(() => {
      const editor = document.getElementById('editor');
      editor.innerHTML =
        '<h1>New post</h1><p>Before TK.</p><div class="blyg-tk-gen"><p>Generated thought.</p></div><p>After TK.</p><p>More prose.</p><p>—Example Author<br>October 16, 2026</p>';
      const f = new FragmentEditor(editor, () => {}, () => {}),
        at = (el) => {
          const range = document.createRange();
          range.selectNodeContents(el);
          range.collapse(true);
          getSelection().removeAllRanges();
          getSelection().addRange(range);
        };
      at(editor.children[4]);
      f.designate();
      const beforeTK = f.snapshot().ranges.length;
      f.tk();
      // Reproduce a DOM edit which lands immediately before Save, after the
      // last input event. serialize() must reconcile once and return matching
      // HTML and metadata even with TK's automatic neighboring boundaries.
      editor.children[3].remove();
      const saved = f.serialize(),
        holder = document.createElement('div');
      holder.innerHTML = saved.html;
      const elements = [...holder.children],
        ids = elements.map((el) => el.dataset.blyngerBlock),
        markerKeys = elements.map((el) => el.dataset.blyngerFragment || null);
      return {
        saved,
        ids,
        markerKeys,
        blockIds: saved.fragments.blocks.map((block) => block.id),
        beforeTK,
      };
    });
    if (tkSave.ids.join() !== tkSave.blockIds.join())
      throw Error('Atomic save returned different HTML and metadata blocks');
    if (tkSave.saved.fragments.ranges.length !== tkSave.beforeTK)
      throw Error('TK created additional reusable fragments');
    for (const range of tkSave.saved.fragments.ranges) {
      const start = tkSave.ids.indexOf(range.start),
        end = range.end ? tkSave.ids.indexOf(range.end) : tkSave.ids.length;
      if (start < 0 || end <= start)
        throw Error('TK/manual fragment range was not repaired before save');
      if (tkSave.markerKeys.slice(start, end).some((key) => key !== range.key))
        throw Error('Durable HTML markers disagree with atomic fragment metadata');
    }
    console.log(
      'Browser checks passed: deleted boundaries self-repair, malformed blocks expand safely, H2 stays structural, and TK does not create feed items.',
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
