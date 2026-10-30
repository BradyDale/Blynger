// One start-then-poll loop for work that can outlast a single WebKit request.
// A dropped response is the browser message "Load failed". The server job may
// still be running, so the next poll decides what happened.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.BlyngerBackgroundJob = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function dropped(error) {
    return !!error && error.message === 'Load failed';
  }

  async function followBackgroundJob(options) {
    const interval = options.interval == null ? 1000 : options.interval;
    const startAttempts = options.startAttempts || 3;
    const unseenMissLimit = options.unseenMissLimit || 3;
    const job = {
      previousId: null,
      baselineKnown: false,
      currentId: null,
    };
    let sawRunning = false;
    let missed = 0;
    let startMisses = 0;

    if (options.baseline) {
      try {
        const previous = await options.baseline();
        job.previousId = (previous && previous.id) || null;
        job.baselineKnown = true;
      } catch (error) {
        if (!dropped(error)) throw error;
      }
    }

    async function start() {
      try {
        const started = await options.start();
        job.currentId = (started && started.id) || job.currentId;
        if (started && started.state === 'running') sawRunning = true;
        startMisses = 0;
        return started;
      } catch (error) {
        if (!dropped(error)) throw error;
        startMisses += 1;
        if (startMisses >= startAttempts) {
          throw Error(options.startFailureMessage || 'Could not start the background job.');
        }
        return null;
      }
    }

    await start();
    while (true) {
      let state;
      try {
        state = await options.status();
        missed = 0;
      } catch (error) {
        if (!dropped(error)) throw error;
        missed += 1;
        if (!sawRunning && missed >= unseenMissLimit) throw error;
        await delay(interval);
        continue;
      }
      if (!state || !state.state || state.state === 'idle') {
        if (options.restartWhenIdle) {
          await start();
          continue;
        }
      } else if (state.state === 'running') {
        if (state.id) {
          if (
            options.runningId === 'require' &&
            job.currentId &&
            state.id !== job.currentId
          ) {
            throw Error(options.identityMessage || 'Background job changed.');
          }
          job.currentId = state.id;
        }
        sawRunning = true;
        if (options.onRunning) options.onRunning(state, job);
        await delay(interval);
        continue;
      }
      const decision = options.settle(state || {}, job);
      if (decision.action === 'return') return decision.value;
      if (decision.action === 'restart') {
        await start();
        if (decision.delay) await delay(decision.delay);
        continue;
      }
      if (decision.action === 'throw') throw decision.error;
      throw Error('Background job returned an unknown result.');
    }
  }

  return { followBackgroundJob };
});
