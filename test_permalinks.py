"""Exercise generated rules with real Apache, against disposable publication files."""
import json, shutil, socket, subprocess, time, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from test_core import StudioTests
from core import new_page

class PermalinkTests(StudioTests):
    # Inherit fixture helpers only, not the parent tests (see load_tests below).
    def test_versions_below_post_date_but_not_home(self):
        raw=new_page('Dated','<p>Text</p><p>—Example Author<br>September 25, 2026</p><p>Afterword</p>')
        doc={'version':3,'updated':'2026-09-26T01:00:00Z','changelog':[]}
        rendered=self.studio.place_versions(raw,'43.html',doc)
        self.assertLess(rendered.index('September 25, 2026'),rendered.index('id="blynger-versions"'))
        self.assertLess(rendered.index('id="blynger-versions"'),rendered.index('Afterword'))
        self.assertIn('font:12px',rendered)
        self.assertEqual(rendered,self.studio.place_versions(rendered,'43.html',doc))
        home=self.studio.place_versions(raw,'index.html',doc)
        self.assertGreater(home.index('id="blynger-versions"'),home.index('</article>'))
        before=self.studio.content(raw,'43.html',{})
        after=self.studio.content(rendered,'43.html',{})
        self.assertEqual(before,after)
    def test_fragment_permalink_survives_becoming_a_thread(self):
        self.studio.migrate();iid=self.studio.state['ids']['1.html'];first=json.loads((self.root/f'blyg/items/{iid}.json').read_text());self.assertEqual(first['page'],'f/'+iid+'/')
        self.studio.state['published'][iid]=first;self.studio.remember({iid:first});draft=self.studio.page('1.html');draft['raw']=new_page('Expanded','<p>'+'Longer writing. '*220+'</p>');self.studio.save_draft(draft);self.studio.prepare();current=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(current['kind'],'thread');self.assertEqual(current['page'],'f/'+iid+'/');self.assertIn('RewriteRule ^f/'+iid,(self.root/'blyg/.htaccess').read_text())
        item=next(e for e in ET.parse(self.root/'feed.xml').findall('./channel/item') if e.find('guid').text.endswith('/'+iid+'/'));self.assertEqual(item.find('guid').text,'https://example.com/blyg/f/'+iid+'/')
    def test_apache_published_permalinks(self):
        iid='4cgbkk3zkaazdd0y336xw1b29t'
        self.studio.state['ids']['thread.html']=iid
        fixture=Path(__file__).parent.parent/'blyg/items'/f'{iid}.json'
        body=json.loads(fixture.read_text())['content_html'] if fixture.exists() else '<p>'+'Long text. '*240+'</p>'
        (self.root/'thread.html').write_text(new_page('Thread',body))
        self.studio.migrate_openers()
        self.studio.prepare()
        docs={p.stem:json.loads(p.read_text()) for p in (self.root/'blyg/items').glob('*.json') if p.stem!='index'}
        self.studio.state['published']=docs;self.studio.remember(docs)
        fid=self.studio.state['ids']['1.html']
        self.studio.pin('thread.html',1);self.studio.prepare()
        pin=(self.root/f'blyg/items/{iid}/v1.json').read_bytes()
        expected={p.name:p.read_bytes() for p in (self.root/'blyg/items').glob('*.json')}
        # Rebuilding aliases alone must not change machine records or item IDs.
        files,newdocs=self.studio.build(self.studio.effective_pages())
        for name,raw in expected.items():self.assertEqual(raw,files['blyg/items/'+name].encode())
        try:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        except PermissionError:self.skipTest('Local socket binding is unavailable in this test environment')
        mods='/usr/libexec/apache2'
        conf=self.base/'httpd.conf';conf.write_text(f'''ServerRoot "{self.base}"
ServerName localhost
Listen 127.0.0.1:{port}
PidFile "{self.base}/httpd.pid"
ErrorLog "{self.base}/error.log"
LoadModule mpm_prefork_module {mods}/mod_mpm_prefork.so
LoadModule unixd_module {mods}/mod_unixd.so
LoadModule authz_core_module {mods}/mod_authz_core.so
LoadModule dir_module {mods}/mod_dir.so
LoadModule mime_module {mods}/mod_mime.so
LoadModule rewrite_module {mods}/mod_rewrite.so
TypesConfig /etc/apache2/mime.types
DocumentRoot "{self.root}"
DirectoryIndex index.html
<Directory "{self.root}">
Require all granted
AllowOverride FileInfo
Options FollowSymLinks
</Directory>
''')
        p=subprocess.Popen(['/usr/sbin/httpd','-f',str(conf),'-DFOREGROUND'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
        def fetch(path):
            try:
                with urlopen(f'http://127.0.0.1:{port}'+path,timeout=3) as r:return r.status,r.read()
            except HTTPError as e:
                with e:return e.code,e.read()
        try:
            for _ in range(50):
                if p.poll() is not None:self.fail(p.stderr.read().decode()+(self.base/'error.log').read_text())
                try:fetch('/');break
                except OSError:time.sleep(.1)
            opener_id=next(iter(self.studio.state['fragment_ids']['openers.html'].values()))
            self.assertEqual(fetch(f'/blyg/f/{opener_id}/')[0],200)
            self.assertIn(b'An opening thought.',fetch(f'/blyg/f/{opener_id}/')[1])
            opener=json.loads(fetch(f'/blyg/items/{opener_id}.json')[1])
            self.assertEqual(opener['kind'],'fragment')
            self.assertNotIn('blynger-fragment-marker',opener['content_html'])
            self.assertIn(b'blynger-fragment-marker',fetch('/openers.html')[1])
            self.assertEqual(fetch(f'/blyg/t/{iid}/'),fetch('/thread.html'))
            status,body=fetch(f'/blyg/f/{fid}/');self.assertEqual(status,200)
            self.assertIn(b'Original <a href="/openers.html">words</a>',body)
            for path in [f'/blyg/f/{iid}/',f'/blyg/t/{fid}/','/blyg/t/00000000000000000000000000/','/blyg/f/00000000000000000000000000/']:
                self.assertEqual(fetch(path)[0],404,path)
            self.assertEqual(fetch(f'/blyg/items/{iid}.json')[1],expected[iid+'.json'])
            self.assertEqual(fetch(f'/blyg/t/{iid}/v1/')[0],200)
            draft=self.studio.page('thread.html');draft['raw']=new_page('Thread revision','<p>Updated <a href="/1.html">link</a>.</p><p>![['+fid+']]</p>');self.studio.save_draft(draft);self.studio.prepare()
            status,body=fetch(f'/blyg/t/{iid}/');self.assertEqual(status,200);self.assertIn(b'Thread revision',body)
            self.assertIn(b'Original',body);self.assertNotIn(b'![[',body)
            self.assertNotIn(b'contenteditable',body);self.assertNotIn(b'HTML source',body)
            self.assertEqual(self.studio.state['ids']['thread.html'],iid)
            self.assertEqual(json.loads(fetch(f'/blyg/items/{iid}.json')[1])['version'],2)
            self.assertEqual(fetch(f'/blyg/items/{iid}/v1.json')[1],pin)
            self.assertIn(f'https://example.com/blyg/t/{iid}/'.encode(),fetch('/blyg/feed.xml')[1])
            self.assertFalse((self.root/f'blyg/t/{iid}/index.html').exists())
        finally:
            p.terminate();p.wait(timeout=5);p.stderr.close()

def load_tests(loader,tests,pattern):
    return unittest.TestSuite([PermalinkTests('test_apache_published_permalinks'),PermalinkTests('test_versions_below_post_date_but_not_home'),PermalinkTests('test_fragment_permalink_survives_becoming_a_thread')])
