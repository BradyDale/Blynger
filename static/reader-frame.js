(function (root) {
  'use strict';
  const esc = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
  const style = `body{font:17px/1.6 Georgia;margin:20px;color:#283129}body.native{background:#edf3ed}body.web{background:#fffdf7}img,video{max-width:100%}a{color:#30615f}blockquote{margin:12px 0;padding-left:16px}.blyg-tk-gen{position:relative;background:#f2f2f2;box-shadow:inset 0 0 0 1px #aaa;border-radius:3px}.blyg-tk-gen:before{content:"";display:inline-block;width:20px;height:20px;margin-right:5px;vertical-align:-5px;background:center/20px 20px no-repeat url("data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2224%22 height=%2224%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23111%22 stroke-width=%221.7%22%3E%3Cpath d=%22M12 8V4H8%22/%3E%3Crect width=%2216%22 height=%2212%22 x=%224%22 y=%228%22 rx=%222%22/%3E%3Cpath d=%22M2 14h2M20 14h2M15 13v2M9 13v2%22/%3E%3C/svg%3E")}div.blyg-tk-gen{padding:8px 11px;margin:12px 0}.reader-source-fragment{position:relative}.reader-source-fragment.reader-selected{outline:1px dashed #555;outline-offset:5px}.reader-fragment-dot{position:absolute;right:-14px;top:4px;width:12px;height:12px;border:0;background:transparent;padding:4px;cursor:pointer}.reader-fragment-dot:after{content:"";display:block;width:4px;height:4px;border-radius:50%;background:#93998e}.reader-fragment-dot:focus{outline:1px dotted #777}`;
  function documentHTML(html, native, channel, origin) {
    const bridge = origin + '/static/reader-frame-bridge.js';
    const csp = `default-src 'none'; script-src ${bridge}; style-src 'unsafe-inline'; img-src ${origin} data:; media-src ${origin}; connect-src 'none'; form-action 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'`;
    return (
      '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' +
      esc(csp) +
      '"><style>' +
      style +
      '</style></head><body class="' +
      (native ? 'native' : 'web') +
      '" data-channel="' +
      esc(channel) +
      '"><main id="readerContent">' +
      html +
      '</main><script src="' +
      esc(bridge) +
      '"><\/script></body></html>'
    );
  }
  function connect(frame, handlers = {}) {
    const channel = Array.from(crypto.getRandomValues(new Uint32Array(4)), (n) =>
      n.toString(16),
    ).join('');
    const listener = (event) => {
      const data = event.data || {};
      if (
        event.source !== frame.contentWindow ||
        data.source !== 'blynger-reader' ||
        data.channel !== channel
      )
        return;
      const handler = handlers[data.type];
      if (handler) handler(data);
    };
    addEventListener('message', listener);
    return {
      channel,
      selectFragment(fragment) {
        frame.contentWindow.postMessage(
          { source: 'blynger-app', channel, type: 'select-fragment', fragment },
          '*',
        );
      },
      close() {
        removeEventListener('message', listener);
      },
    };
  }
  root.BlyngerReaderFrame = { documentHTML, connect };
})(window);
