'use strict';

const jobs =
  typeof require === 'function'
    ? require('./static/background-job.js')
    : globalThis.BlyngerBackgroundJob;

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(label + ': ' + JSON.stringify(actual) + ' !== ' + JSON.stringify(expected));
  }
}

function dropped() {
  return new Error('Load failed');
}

function scripted(steps) {
  let index = 0;
  return async function call() {
    if (index >= steps.length) throw new Error('script ended at step ' + index);
    const step = steps[index];
    index += 1;
    if (typeof step === 'function') return step();
    return step;
  };
}

async function reviewAdoptsTheNewReadyResult() {
  const calls = scripted([
    { id: 'old', state: 'ready', review: { stale: true } },
    { id: 'new', state: 'running' },
    { id: 'old', state: 'ready', review: { stale: true } },
    { id: 'new', state: 'running' },
    { id: 'new', state: 'ready', review: { current: true } },
  ]);
  const review = await jobs.followBackgroundJob({
    baseline: calls,
    start: calls,
    status: calls,
    interval: 0,
    restartWhenIdle: true,
    settle(state, job) {
      if (state.state !== 'ready') return { action: 'throw', error: new Error(state.state) };
      const previousReviewId = job.previousId;
      const isCurrent = job.currentId && state.id === job.currentId;
      const isNew = job.baselineKnown && state.id && state.id !== previousReviewId;
      if (isCurrent || isNew) return { action: 'return', value: state.review };
      return { action: 'restart', delay: 0 };
    },
  });
  assertEqual(review.current, true, 'review result');
  assertEqual(review.stale, undefined, 'stale review');
}

async function droppedPollKeepsWaiting() {
  let polls = 0;
  const status = async () => {
    polls += 1;
    if (polls === 1) throw dropped();
    if (polls === 2) return { id: 'job', state: 'running' };
    return { id: 'job', state: 'ready', review: { ok: true } };
  };
  const review = await jobs.followBackgroundJob({
    start: async () => ({ id: 'job', state: 'running' }),
    status,
    interval: 0,
    restartWhenIdle: true,
    settle(state) {
      return { action: 'return', value: state.review };
    },
  });
  assertEqual(review.ok, true, 'poll survived Load failed');
}

async function threeDroppedStartsFail() {
  let starts = 0;
  let message = '';
  try {
    await jobs.followBackgroundJob({
      start: async () => {
        starts += 1;
        throw dropped();
      },
      status: async () => ({ state: 'idle' }),
      interval: 0,
      restartWhenIdle: true,
      startFailureMessage: 'Could not start.',
      settle() {
        return { action: 'throw', error: new Error('should have stopped at start') };
      },
    });
  } catch (error) {
    message = error.message;
  }
  assertEqual(starts, 3, 'start attempts');
  assertEqual(message, 'Could not start.', 'start failure');
}

async function readerReturnsItsOwnSuccess() {
  const calls = scripted([
    { id: 'old', state: 'succeeded', message: 'previous' },
    { id: 'new', state: 'running' },
    { id: 'new', state: 'running' },
    { id: 'new', state: 'succeeded', message: 'done' },
  ]);
  const result = await jobs.followBackgroundJob({
    baseline: calls,
    start: calls,
    status: calls,
    interval: 0,
    restartWhenIdle: true,
    runningId: 'require',
    identityMessage: 'Reader refresh changed. Refresh again.',
    settle(state, job) {
      const joined = job.currentId && state.id === job.currentId;
      const fresh = job.baselineKnown && state.id && state.id !== job.previousId;
      if (!joined && !fresh) return { action: 'restart', delay: 0 };
      if (state.state === 'succeeded') return { action: 'return', value: state };
      return { action: 'throw', error: new Error(state.message || 'failed') };
    },
  });
  assertEqual(result.id, 'new', 'reader job');
  assertEqual(result.message, 'done', 'reader message');
}

async function readerRejectsADifferentRunningJob() {
  let message = '';
  try {
    await jobs.followBackgroundJob({
      start: async () => ({ id: 'new', state: 'running' }),
      status: async () => ({ id: 'other', state: 'running' }),
      interval: 0,
      runningId: 'require',
      identityMessage: 'Reader refresh changed. Refresh again.',
      settle() {
        return { action: 'return', value: {} };
      },
    });
  } catch (error) {
    message = error.message;
  }
  assertEqual(message, 'Reader refresh changed. Refresh again.', 'reader identity');
}

async function main() {
  await reviewAdoptsTheNewReadyResult();
  await droppedPollKeepsWaiting();
  await threeDroppedStartsFail();
  await readerReturnsItsOwnSuccess();
  await readerRejectsADifferentRunningJob();
}

const runningDirectly =
  typeof require === 'function' ? require.main === module : typeof globalThis.BlyngerBackgroundJob === 'object';

if (runningDirectly) {
  main().catch((error) => {
    const text = error && error.stack ? error.stack : String(error);
    if (typeof console === 'object') console.error(text);
    else if (typeof debug === 'function') debug(text);
    if (typeof process === 'object' && process.exit) process.exit(1);
    if (typeof quit === 'function') quit(1);
  });
}
