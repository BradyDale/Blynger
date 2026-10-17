const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = { window: {}, Date, Number };
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/reader-ui.js', 'utf8'), context);

const ui = context.window.BlyngerReaderUI;
const esc = (value) => String(value);
const item = {
  author: 'Reader',
  date: '2026-10-09T12:00:00Z',
  kind: 'thread',
  origin: 'https://source.example/',
  site: 'Source',
  source_type: 'blyg',
  title: 'A response',
  version: 2,
};
const opened = ui.openedItem(
  item,
  {
    conversation: {
      backward: { label: 'Earlier thought' },
      forward: [{ label: 'Later thought' }],
    },
    doc: {
      changelog: [{ version: 1, pinned: true }],
      generated: [{ model: 'model', sources: [] }],
    },
    fragments: [{ index: 0 }],
  },
  esc,
  () => 'Oct 9, 2026',
);

assert.strictEqual(opened.native, true);
assert.deepStrictEqual([...opened.pins], [1]);
assert.match(opened.html, /Backward:/);
assert.match(opened.html, /Forward:/);
assert.match(opened.html, /readerFrame/);
assert.match(opened.html, /What the author disclosed/);
assert.match(opened.html, /Fragments in this thread/);
assert.match(opened.html, /Open original/);
assert.match(opened.html, /Fork pinned version/);

const unpinned = ui.openedItem(
  item,
  {
    conversation: { backward: null, forward: [] },
    doc: { changelog: [{ version: 1, pinned: false }] },
    fragments: [],
  },
  esc,
  () => 'Oct 9, 2026',
);
assert.match(unpinned.html, /id="forkReading" class="unavailable" aria-disabled="true"/);
assert.match(unpinned.html, /title="Requires a pinned post"/);
assert.match(ui.savedTime(null), /before date tracking/);

const container = {
  children: [],
  replaceChildren() {
    this.children = [];
  },
  append(value) {
    this.children.push(value);
  },
};
const oldDocument = context.document;
context.document = {
  createElement() {
    return {
      className: '',
      innerHTML: '',
      querySelector() {
        return {
          onclick: null,
          append() {},
          className: '',
          textContent: '',
          title: '',
          setAttribute() {},
        };
      },
      append() {},
      setAttribute() {},
    };
  },
};
ui.renderItems(
  container,
  [
    {
      ...item,
      key: 'one',
      excerpt: 'Words',
      saved: false,
      liked: false,
      reaction: null,
      revision_count: 3,
      pin_count: 2,
      pace_rise: 1,
      pace_warning: 'Malformed; use Newest or skip.',
      updated: '2026-10-12T12:00:00Z',
    },
  ],
  esc,
  { read() {}, quote() {}, stub() {}, save() {}, like() {}, react() {}, isolate() {} },
);
assert.match(container.children[0].className, /reader-revisions-3/);
assert.doesNotMatch(container.children[0].innerHTML, /class="read-item"/);
assert.match(container.children[0].innerHTML, /reader-actions-left/);
assert.match(container.children[0].innerHTML, /Opener Stub/);
assert.match(container.children[0].innerHTML, /Post Stub/);
assert.match(container.children[0].innerHTML, /reader-actions-center/);
assert.match(container.children[0].innerHTML, /reader-actions-right/);
assert.strictEqual(typeof container.children[0].onclick, 'function');
assert.strictEqual(typeof container.children[0].onkeydown, 'function');
assert.match(container.children[0].innerHTML, /REVISED · v2/);
assert.match(container.children[0].innerHTML, /2 pinned versions/);
assert.match(container.children[0].innerHTML, /moved up 1 place/);
assert.match(container.children[0].innerHTML, /Skip this item/);
context.document = oldDocument;

console.log('reader UI tests passed');
