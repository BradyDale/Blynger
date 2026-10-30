'use strict';
const assert = require('node:assert/strict');
const dialogue = require('./static/dialogue.js');

const marked = dialogue.parseMarkedText(
  'You said:\nFirst question.\n\nChatGPT said:\nFirst answer.\n\nBrady: Follow-up.\nAssistant: Final answer.',
);
assert.deepEqual(
  marked.map(({ role, text }) => ({ role, text })),
  [
    { role: 'author', text: 'First question.\n' },
    { role: 'assistant', text: 'First answer.\n' },
    { role: 'author', text: 'Follow-up.' },
    { role: 'assistant', text: 'Final answer.' },
  ],
);

const inferred = dialogue.parseMarkedText('Question without labels.\n\nAnswer without labels.');
assert.deepEqual(inferred, []);

const nodes = [
  { innerText: 'Earlier question', classList: { contains: () => false } },
  { innerText: 'Earlier answer', classList: { contains: (name) => name === 'blyg-tk-gen' } },
  { innerText: 'Latest follow-up', classList: { contains: () => false } },
  { innerText: 'Signature', classList: { contains: () => false }, excluded: true },
];
const transcript = dialogue.transcript(
  { children: nodes },
  (node) => !!node.excluded,
);
assert.equal(
  transcript,
  'AUTHOR:\nEarlier question\n\nASSISTANT:\nEarlier answer\n\nAUTHOR:\nLatest follow-up',
);

console.log('dialogue import tests passed');
