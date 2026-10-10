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
assert.match(ui.savedTime(null), /before date tracking/);

console.log('reader UI tests passed');
