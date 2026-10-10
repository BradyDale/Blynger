'use strict';
const assert = require('node:assert/strict');
const { SerialQueue, LatestRequest } = require('./static/editor-safety.js');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function tick() {
  await Promise.resolve();
  await Promise.resolve();
}

async function testSerialAndOutOfOrderSaves() {
  const queue = new SerialQueue(),
    first = deferred(),
    calls = [];
  let text = 'older',
    revision = 1,
    savedRevision = 0;
  const save = () =>
    queue.enqueue(async () => {
      const snapshot = { text, revision };
      calls.push(snapshot);
      if (calls.length === 1) await first.promise;
      savedRevision = snapshot.revision;
      return snapshot;
    });
  const old = save();
  await tick();
  text = 'newer';
  revision = 2;
  const newer = save();
  await tick();
  assert.deepEqual(
    calls,
    [{ text: 'older', revision: 1 }],
    'the second save must not overtake the first',
  );
  first.resolve();
  await old;
  await newer;
  assert.deepEqual(calls, [
    { text: 'older', revision: 1 },
    { text: 'newer', revision: 2 },
  ]);
  assert.equal(savedRevision, 2);
}

async function testFailureCanRetryWithoutChangingPayload() {
  const queue = new SerialQueue(),
    payload = { raw: 'words', fragments: [{ id: 'f1' }], quotes: { q1: { version: 3 } } };
  let attempts = 0,
    writes = [];
  const save = () =>
    queue.enqueue(async () => {
      attempts += 1;
      const copy = JSON.parse(JSON.stringify(payload));
      if (attempts === 1) throw Error('offline');
      writes.push(copy);
      return copy;
    });
  await assert.rejects(save(), /offline/);
  await save();
  assert.deepEqual(writes, [payload]);
}

function testDelayedPageLoadsAndPendingTyping() {
  const gate = new LatestRequest();
  let edits = 4;
  const first = gate.begin(edits),
    second = gate.begin(edits);
  assert.equal(gate.accepts(first, edits), false, 'an older page response must be ignored');
  assert.equal(gate.accepts(second, edits), true);
  const pending = gate.begin(edits);
  edits += 1;
  assert.equal(
    gate.accepts(pending, edits),
    false,
    'typing after navigation begins must preserve the newer edit',
  );
}

(async () => {
  await testSerialAndOutOfOrderSaves();
  await testFailureCanRetryWithoutChangingPayload();
  testDelayedPageLoadsAndPendingTyping();
  console.log('editor safety tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
