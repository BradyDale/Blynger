const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = { URL };
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/thicket-ui.js', 'utf8'), context);
const ui = context.BlyngerThicketUI;

assert.strictEqual(ui.safeHttpUrl('javascript:alert(1)'), null);
assert.strictEqual(ui.safeHttpUrl('file:///etc/passwd'), null);
assert.strictEqual(
  ui.safeHttpUrl('https://writer.example/post'),
  'https://writer.example/post',
);
assert.strictEqual(
  ui.incomingType({ relation: 'stub', kind: 'new', status: 'verified' }),
  'STUB',
);
assert.strictEqual(
  ui.incomingType({ relation: null, kind: 'withdrawal', status: 'gone' }),
  'WITHDRAWAL',
);
assert.strictEqual(
  ui.incomingSite({
    source_author: '<img src=x onerror=alert(1)>',
    source_origin: 'https://writer.example/',
  }),
  '<img src=x onerror=alert(1)> · writer.example',
);

const mixed = ui.combined(
  { entries: [{ updated_at: '2026-10-20T12:00:00Z', title: 'Out' }] },
  { activities: [{ at: '2026-10-20T13:00:00Z', title: 'In' }] },
);
assert.deepStrictEqual([...mixed.map((row) => row.direction)], ['IN', 'OUT']);
assert.strictEqual(
  ui.incomingCaption({ availability: 'not_synchronized' }),
  'Not yet synchronized.',
);
assert.strictEqual(
  ui.incomingCaption({ availability: 'unavailable' }),
  'Synchronization unavailable.',
);
assert.strictEqual(
  ui.incomingCaption({ availability: 'current', unread_count: 0, activity_count: 0 }),
  'No incoming mentions.',
);
assert.strictEqual(
  ui.incomingCaption({ availability: 'current', unread_count: 2, activity_count: 2 }),
  '2 unread',
);
assert.strictEqual(
  ui.incomingCaption({ availability: 'stale', unread_count: 1, activity_count: 2 }),
  '1 unread · last-known activity',
);

console.log('thicket UI tests passed');
