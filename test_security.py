import json, re, tempfile, threading, unittest, urllib.request
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer

from app import Handler
from reader import Reader, clean_reader, fetch, MAX_ASSETS_PER_ITEM, MAX_ASSET_BYTES, MAX_FEED_ENTRIES
from test_reader import Net, ORIGIN, IID, doc

ROOT=Path(__file__).resolve().parent

class ReaderSecurityTests(unittest.TestCase):
    def test_fetch_connects_to_the_exact_address_that_was_validated(self):
        response=(200,b'ok',{'Content-Type':'text/plain'})
        with patch('reader_network.public_url',return_value=(None,['203.0.113.44'])) as resolve, patch('reader_network.request_once',return_value=response) as request:
            final,body,headers,status=fetch('https://remote.example/path')
        resolve.assert_called_once_with('https://remote.example/path')
        request.assert_called_once_with('https://remote.example/path','203.0.113.44',None,4*1024*1024)
        self.assertEqual((final,body,status),('https://remote.example/path',b'ok',200))

    def test_unsafe_xml_entities_are_rejected(self):
        feed='https://feed.example/rss.xml';net=Net();net.urls[feed]=('<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><channel><title>&xxe;</title></channel></rss>','application/rss+xml')
        with tempfile.TemporaryDirectory() as folder:
            reader=Reader(Path(folder),net)
            with self.assertRaisesRegex(ValueError,'unsafe RSS/Atom'):reader.sync_plain({'origin':feed})

    def test_feed_and_media_work_are_bounded(self):
        feed='https://feed.example/rss.xml';net=Net();items=''.join('<item><guid>'+str(i)+'</guid><title>T</title><description>Body</description></item>' for i in range(MAX_FEED_ENTRIES+1));net.urls[feed]=('<rss><channel><title>Feed</title>'+items+'</channel></rss>','application/rss+xml')
        with tempfile.TemporaryDirectory() as folder:
            reader=Reader(Path(folder),net);sid=reader.subscribe(feed)['subscriptions'][0]['id']
            self.assertEqual(len(reader.state['items']),MAX_FEED_ENTRIES);self.assertTrue(any('limited' in w for w in reader.state['subscriptions'][sid]['warnings']))
            urls=''.join('<img src="https://media.example/'+str(i)+'.png">' for i in range(MAX_ASSETS_PER_ITEM+1));limits=[]
            def bounded(url,headers=None,limit=None):limits.append(limit);return url,b'x',{'Content-Type':'image/png'},200
            reader.fetch=bounded;used,visual,warnings=reader.download_assets({'content_html':urls,'media':[]},feed,{})
            self.assertEqual(len(limits),MAX_ASSETS_PER_ITEM);self.assertTrue(all(limit<=MAX_ASSET_BYTES for limit in limits));self.assertTrue(any('limited' in w for w in warnings))

    def test_hostile_reader_markup_loses_active_content_and_ui_names(self):
        hostile='''<style>.publish{position:fixed;inset:0}</style>
        <form action="http://127.0.0.1:18765/api/settings"><button id="publish" class="publish" onclick="top.location='https://evil.test'">Fake publish</button><input name="X-Blynger-Token"></form>
        <script>fetch('/api/settings')</script><iframe src="/api/settings"></iframe>
        <a id="settings" class="dialog-actions" href="javascript:alert(1)">bad</a>
        <div id="readerFrame" class="blyg-tk-gen publish">Generated words</div>'''
        rendered=clean_reader(hostile)
        for forbidden in ('<script','<style','<form','<button','<input','<iframe','onclick','javascript:','id=','publish','dialog-actions','Fake publish'):
            self.assertNotIn(forbidden,rendered)
        self.assertIn('class="blyg-tk-gen"',rendered)
        self.assertIn('Generated words',rendered)

    def test_only_deliberate_blyg_classes_and_transclusion_identity_survive(self):
        markup='<blockquote class="blyg-transclusion blyg-partial publish" id="publish" data-blyg-id="0123456789abcdefghjkmnpq" data-blyg-version="2" data-blyg-origin="https://remote.example/">Words</blockquote>'
        rendered=clean_reader(markup)
        self.assertIn('class="blyg-transclusion blyg-partial"',rendered)
        self.assertIn('data-blyg-id=',rendered);self.assertIn('data-blyg-version="2"',rendered);self.assertIn('data-blyg-origin=',rendered)
        self.assertNotIn('publish',rendered);self.assertNotIn(' id=',rendered)

    def test_malformed_nested_markup_is_inert_but_readable(self):
        rendered=clean_reader('<p>Ordinary <b>valid<div><svg><foreignObject><script>bad()</script></foreignObject></svg><p>Reader text<img src="https://remote.example/a.png" onerror="evil()">')
        self.assertIn('Ordinary',rendered);self.assertIn('Reader text',rendered);self.assertIn('<b>',rendered);self.assertIn('<img',rendered)
        self.assertNotIn('bad()',rendered);self.assertNotIn('onerror',rendered);self.assertNotIn('<svg',rendered)

    def test_reader_frame_is_opaque_and_uses_narrow_message_bridge(self):
        index=(ROOT/'static/index.html').read_text();app=(ROOT/'static/app.js').read_text()+(ROOT/'static/reader-ui.js').read_text();frame=(ROOT/'static/reader-frame.js').read_text();bridge=(ROOT/'static/reader-frame-bridge.js').read_text()
        compact_app=re.sub(r'\s+','',app);compact_frame=re.sub(r'\s+','',frame);compact_bridge=re.sub(r'\s+','',bridge)
        self.assertIn('/static/reader-frame.js',index)
        self.assertIn('sandbox="allow-scripts"',app);self.assertNotIn('allow-same-origin',app);self.assertNotIn('contentDocument',app)
        self.assertIn("connect-src 'none'",frame);self.assertIn("form-action 'none'",frame);self.assertIn("frame-src 'none'",frame);self.assertIn("base-uri 'none'",frame)
        self.assertIn('/static/reader-frame-bridge.js',frame);self.assertIn("event.source!==frame.contentWindow",compact_frame);self.assertIn("event.source!==parent",compact_bridge);self.assertIn("channel",bridge)
        self.assertNotIn("X-Blynger-Token",frame+bridge)
        self.assertIn("api('open-external',{url:data.href})",compact_app)
        self.assertNotIn("link:data=>{if(/^https?:/i.test(data.href))readerOperation('reader-open'",compact_app)

    def test_privileged_ui_has_strong_csp(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.token='test-token';server.studio=SimpleNamespace(config={'site_label':'Test','author_name':'Tester'})
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/') as response:
                csp=response.headers['Content-Security-Policy'];body=response.read().decode()
            self.assertIn("default-src 'none'",csp);self.assertIn("script-src 'self'",csp);self.assertIn("connect-src 'self'",csp);self.assertIn("frame-ancestors 'none'",csp);self.assertIn('test-token',body)
        finally:server.shutdown();server.server_close();thread.join()

    def test_sandbox_sanitization_preserves_quote_stub_fragment_and_fork_sources(self):
        fragment_id='0'*25+'2';source=doc(kind='thread',text='Thread words')
        source['content_html']='<p>Thread words</p><blockquote class="publish blyg-transclusion" id="publish" data-blyg-id="'+fragment_id+'" data-blyg-version="1" data-blyg-origin="'+ORIGIN+'"><p>Fragment words</p></blockquote>'
        source['transclusions']=[{'origin':ORIGIN,'id':fragment_id,'version':1}];source['changelog'][0]['pinned']=True
        fragment=doc(iid=fragment_id,text='Fragment words')
        with tempfile.TemporaryDirectory() as folder:
            net=Net();net.add(items=[source,fragment]);reader=Reader(Path(folder),net);reader.subscribe(ORIGIN);key=reader.key(ORIGIN,IID)
            rendered=reader.rendered(key);self.assertNotIn('publish',rendered);self.assertNotIn(' id=',rendered);self.assertIn('blyg-transclusion',rendered)
            fragments=reader.source_fragments(key);self.assertEqual([(f['id'],f['version']) for f in fragments],[(fragment_id,1)])
            quoted=reader.snapshot(key,{'mode':'whole','transclude':True},SimpleNamespace(data=Path(folder)));self.assertEqual(quoted['stub_of']['id'],IID);self.assertIn('blyg-transclusion',quoted['html'])
            forked=reader.fork_source(key,1);self.assertIn('Thread words',forked['html']);self.assertEqual(forked['forked_from'],{'origin':ORIGIN,'id':IID,'version':1})

if __name__=='__main__':unittest.main()
