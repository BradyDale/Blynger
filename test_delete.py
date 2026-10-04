import json, unittest, subprocess, copy
from test_core import StudioTests
from core import Studio, NS
import xml.etree.ElementTree as ET

class DeleteTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def connect(self):
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);self.studio.git('remote','add','website',str(remote))
    def publish(self):
        r=self.studio.prepare();self.studio.publish(r['signature'])
    def test_draft_delete_restore_reload_and_no_publication(self):
        d=self.studio.create('Keep me');raw=d['raw'];self.studio.delete_post(d['name']);self.assertNotIn(d['name'],self.studio.state['drafts']);self.assertTrue(self.studio.page(d['name'])['deleted']);self.studio.prepare();self.assertFalse(self.studio.path(d['name']).exists())
        self.studio=Studio(self.root,self.studio.data);self.studio.restore_post(d['name']);self.assertEqual(self.studio.page(d['name'])['raw'],raw);self.assertNotEqual(self.studio.create('Next')['name'],d['name'])
    def test_published_withdrawal_and_restore_preserve_id_pins(self):
        self.connect();self.publish();iid=self.studio.state['ids']['1.html'];original=self.studio.page('1.html')['body'];self.studio.pin('1.html',1);self.publish();pin=self.root/f'blyg/items/{iid}/v1.json';pinned=pin.read_bytes()
        self.studio.delete_post('1.html');self.assertIn('Original',self.studio.state['deleted_posts']['1.html']['page']['body']);self.publish();d=self.studio.state['published'][iid];self.assertEqual(d['kind'],'withdrawn');self.assertEqual(d['content_md'],'');self.assertEqual(d['media'],[]);self.assertNotIn('generated',d);self.assertEqual(d['version'],2);self.assertEqual(pin.read_bytes(),pinned);self.assertNotIn('href="/1.html"',(self.root/'index.html').read_text());self.assertNotIn('Original',(self.root/'1.html').read_text());self.assertNotIn('1.html', (self.root/'sitemap.xml').read_text())
        entries=[item for item in ET.parse(self.root/'blyg/feed.xml').findall('./channel/item') if item.find('{'+NS+'}id').text==iid]
        self.assertEqual(len(entries),1);self.assertEqual(entries[0].find('{'+NS+'}version').text,'2');self.assertEqual(entries[0].find('title').text,'withdrawn');self.assertFalse(entries[0].find('description').text)
        self.studio.prepare();self.assertEqual(json.loads((self.root/f'blyg/items/{iid}.json').read_text())['version'],2)
        self.studio.restore_post('1.html');self.publish();self.assertEqual(self.studio.state['ids']['1.html'],iid);self.assertEqual(self.studio.state['published'][iid]['version'],3);self.assertIn('Original',self.studio.state['published'][iid]['content_html']);self.assertIn('href="/1.html"',(self.root/'index.html').read_text());self.assertEqual(pin.read_bytes(),pinned)
    def test_main_pages_protected_and_deleted_post_not_editable(self):
        for n in ['index.html','openers.html','portfolio.html','privacypolicy.html']:
            with self.assertRaises(ValueError):self.studio.delete_post(n)
        d=self.studio.create('Draft');self.studio.delete_post(d['name'])
        with self.assertRaises(ValueError):self.studio.save_draft(d)
    def test_withdraw_thread_empties_references(self):
        self.connect();self.publish();iid=self.studio.state['ids']['1.html'];self.studio.state['published'][iid].update(kind='thread',transclusions=[{'id':'0'*26,'version':1}],generated=[{'sources':[]}]);self.studio.delete_post('1.html');self.publish();d=self.studio.state['published'][iid];self.assertEqual(d['transclusions'],[]);self.assertNotIn('generated',d)

def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(DeleteTests)
