(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.BlyngerEditorSafety = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  class SerialQueue {
    constructor() {
      this.tail = Promise.resolve();
    }
    enqueue(task) {
      const run = this.tail.then(task);
      this.tail = run.catch(() => {});
      return run;
    }
  }
  class LatestRequest {
    constructor() {
      this.number = 0;
    }
    begin(editRevision) {
      return { number: ++this.number, editRevision };
    }
    accepts(ticket, editRevision) {
      return ticket.number === this.number && ticket.editRevision === editRevision;
    }
    invalidate() {
      this.number += 1;
    }
  }
  return { SerialQueue, LatestRequest };
});
