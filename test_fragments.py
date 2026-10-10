import copy, json, re, subprocess, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
from core import Studio, new_page, digest, FragmentFileConflict, FragmentStateError
from test_core import StudioTests
import fragments

class FragmentTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def draft(self):
        d=self.studio.page('1.html')
        blocks=['<h1>Test title</h1>','<p>Ordinary introduction.</p>','<p>First thought.</p>','<p>Second paragraph.</p>','<p>Connective prose.</p>','<div class="blyg-tk-gen"><p>Generated thought.</p></div>','<p>—Example Author<br>September 26, 2026</p>']
        d['raw']=new_page('Test title',''.join(blocks[1:]))
        d['fragments']={'version':1,'blocks':[{'id':f'b{i}','html':b} for i,b in enumerate(blocks)],'dividers':['b2','b4','b5','b6'],'ranges':[{'key':'first','start':'b2','end':'b4'},{'key':'tk','start':'b5','end':'b6'}]}
        d['generated']=[{'sources':[],'model':'test-model','at':'2026-09-26T12:00:00Z'}]
        return d
    def connect(self):
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote))
    def publish(self):
        review=self.studio.prepare();self.studio.publish(review['signature'])
    def test_private_persistence_and_no_history_on_save(self):
        d=self.draft();before=(self.root/'1.html').read_bytes();self.studio.save_draft(d)
        s=Studio(self.root,self.base/'private');self.assertEqual(s.page('1.html')['fragments'],d['fragments'])
        self.assertEqual(before,(self.root/'1.html').read_bytes());self.assertEqual(s.state['published'],{});self.assertEqual(s.state['fragment_ids'],{})
    def test_browser_repaired_h2_boundaries_survive_save_reopen_and_prepare(self):
        d=self.studio.page('1.html')
        blocks=['<h1>Test title</h1>','<p>Introduction.</p>','<ul><li>List thought.</li></ul>','<h2>Second thought</h2>','<p>Body two.</p>','<h2>Third thought</h2>','<p>Body three.</p>','<p>—Example Author<br>September 26, 2026</p>']
        d['raw']=new_page('Test title',''.join(blocks[1:]))
        d['fragments']={'version':1,'blocks':[{'id':f'h{i}','html':block} for i,block in enumerate(blocks)],'dividers':['h1','h3','h5','h7'],'ranges':[{'key':'intro','start':'h1','end':'h3'},{'key':'second','start':'h3','end':'h5'},{'key':'third','start':'h5','end':'h7'}]}
        self.studio.save_draft(d)
        reopened=Studio(self.root,self.base/'private');saved=reopened.page('1.html')
        self.assertEqual(saved['fragments'],d['fragments'])
        reopened.prepare()
        identities=reopened.state['fragment_ids']['1.html']
        self.assertIn('second',identities);self.assertIn('third',identities)
        second=json.loads((self.root/f"blyg/items/{identities['second']}.json").read_text())
        third=json.loads((self.root/f"blyg/items/{identities['third']}.json").read_text())
        self.assertIn('Second thought',second['content_html']);self.assertIn('Body two.',second['content_html'])
        self.assertIn('Third thought',third['content_html']);self.assertIn('Body three.',third['content_html'])
    def test_git_publication_reopen_versions_and_provenance(self):
        self.connect();self.studio.config['favicon']='/images/favicon.png';d=self.draft();self.studio.save_draft(d);self.publish()
        ids=self.studio.state['fragment_ids']['1.html'];iid=ids['first'];tid=self.studio.state['ids']['1.html'];docs=self.studio.state['published']
        f=docs[iid];t=docs[tid]
        self.assertEqual(f['kind'],'fragment');self.assertEqual(f['version'],1);self.assertNotIn('transclusions',f)
        self.assertEqual(f['content_hash'],'sha256:'+digest(f['content_md']));self.assertIn('Second paragraph',f['content_md'])
        self.assertNotIn('Test title',f['content_md']);self.assertNotIn('Example Author',f['content_md'])
        self.assertEqual(t['kind'],'thread');self.assertEqual(t['transclusions'],[{'id':iid,'version':1},{'id':ids['tk'],'version':1}])
        self.assertIn('Ordinary introduction',t['content_md']);self.assertIn('![['+iid+']]',t['content_md'])
        self.assertEqual(docs[ids['tk']]['generated'],d['generated'])
        for doc in docs.values():
            self.assertRegex(doc['id'],r'^[0-7][0-9a-hjkmnp-tv-z]{25}$')
            self.assertNotIn('fragment-block',doc['content_html']);self.assertNotIn('fragment-dot',doc['content_md'])
        self.assertTrue((self.root/f'blyg/f/{iid}/index.html').exists())
        page=(self.root/f'blyg/f/{iid}/index.html').read_text()
        discovery=BeautifulSoup(page,'html.parser');self.assertEqual(discovery.find('link',rel='blyg')['href'],'/blyg/');self.assertEqual(discovery.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml');self.assertEqual(discovery.find('link',rel='icon')['href'],'/images/favicon.png')
        self.assertIn('<h1>FROM: Test title</h1>',page)
        self.assertIn('<a href="https://example.com/1.html">Full thread</a>',page)
        self.assertLess(page.index('Full thread'),page.index('id="blynger-versions"'))
        self.assertIn(f'https://example.com/blyg/f/{iid}/',(self.root/'sitemap.xml').read_text())
        feed_ids={n.text for n in ET.parse(self.root/'blyg/feed.xml').findall('.//{https://blygger.org/ns/0.1}id')}
        self.assertIn(tid,feed_ids)
        self.assertTrue(set(ids.values()) <= feed_ids)
        self.assertEqual(len(ET.parse(self.root/'feed.xml').findall('./channel/item')),1)
        s=Studio(self.root,self.base/'private');opened=s.page('1.html');self.assertEqual(opened['fragments'],d['fragments']);self.assertNotIn('![[',opened['body'])
        opened['raw']=opened['raw'].replace('First thought.','Edited thought.')
        opened['fragments']['blocks'][2]['html']='<p>Edited thought.</p>'
        s.save_draft(opened);self.studio=s;self.publish()
        self.assertEqual(s.state['fragment_ids']['1.html'],ids)
        self.assertEqual(s.state['published'][iid]['version'],2)
        self.assertEqual(s.state['published'][ids['tk']]['version'],1)
        self.assertEqual(s.state['published'][tid]['transclusions'][0]['version'],2)
        self.assertEqual(s.state['history'][iid]['1']['content_md'],f['content_md'])
        # Repeated preparation is stable and does not advance fragment history.
        a=s.prepare();first=(self.root/f'blyg/items/{iid}.json').read_bytes();human=(self.root/f'blyg/f/{iid}/index.html').read_text();s.prepare();self.assertEqual(first,(self.root/f'blyg/items/{iid}.json').read_bytes());self.assertEqual(human,(self.root/f'blyg/f/{iid}/index.html').read_text());self.assertEqual(human.count('rel="blyg"'),1)
    def test_outside_article_image_is_not_duplicated_when_fragments_render(self):
        (self.root/'images'/'hero.jpg').write_bytes(b'hero-image')
        d=self.draft();d['raw']=d['raw'].replace('<article>','<center><img src="/images/hero.jpg" alt="Hero"></center><article>',1)
        self.studio.save_draft(d);self.studio.prepare();page=BeautifulSoup((self.root/'1.html').read_text(),'html.parser')
        self.assertEqual(len(page.find_all('img',alt='Hero')),1)
        iid=self.studio.state['ids']['1.html'];item=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertIn('alt="Hero"',item['content_html']);self.assertIn('/blyg/media/',item['content_html'])
    def test_removing_designation_keeps_published_item(self):
        self.connect();d=self.draft();self.studio.save_draft(d);self.publish();ids=self.studio.state['fragment_ids']['1.html']
        d=self.studio.page('1.html');d['fragments']['ranges']=[];self.studio.save_draft(d);self.publish()
        for iid in ids.values():self.assertIn(iid,self.studio.state['published'])
    def test_implicit_edges_and_reordering(self):
        d=self.draft();m=d['fragments'];m['ranges']=[{'key':'edge','start':'b1','end':'b6'}];m['dividers']=[]
        self.studio.save_draft(d);self.studio.prepare();iid=self.studio.state['fragment_ids']['1.html']['edge']
        self.assertIn('Generated thought',json.loads((self.root/f'blyg/items/{iid}.json').read_text())['content_md'])
        # True end of body without a signature is implicit as well.
        m['blocks']=m['blocks'][:-1];m['ranges'][0]['end']=None
        self.assertIsNotNone(fragments.validate(m,''.join(b['html'] for b in m['blocks'])))
    def test_invalid_or_stale_anchors_fail_before_writes(self):
        d=self.draft();d['raw']=d['raw'].replace('First thought','Unexpected source edit')
        with self.assertRaisesRegex(FragmentStateError,'anchors') as problem:self.studio.save_draft(d)
        self.assertEqual(problem.exception.page,'1.html')
        d=self.draft();d['fragments']['ranges'][0]['start']='b0'
        with self.assertRaisesRegex(ValueError,'Titles'):self.studio.save_draft(d)
    def test_orphaned_editor_divider_does_not_trap_draft(self):
        d=self.draft();d['fragments']['dividers'].append('paragraph-the-browser-removed')
        self.studio.save_draft(d)
        self.assertNotIn('paragraph-the-browser-removed',self.studio.page('1.html')['fragments']['dividers'])
    def test_accept_harmless_external_file_change(self):
        d=self.draft();self.studio.save_draft(d)
        saved=copy.deepcopy(self.studio.state['drafts'].pop('1.html'))
        saved['file_hash']=digest((self.root/'1.html').read_bytes())
        self.studio.state['fragment_posts']['1.html']=saved;self.studio.save_state()
        original=saved['raw']
        current=original.replace('</head>','<meta name="historical-design" content="kept"></head>').replace('\n','\r\n')
        (self.root/'1.html').write_bytes(current.encode())
        with self.assertRaises(FragmentFileConflict) as problem:self.studio.page('1.html')
        self.assertTrue(problem.exception.can_accept)
        result=self.studio.accept_fragment_files(['1.html'])
        self.assertIn('preserved',result['message'])
        accepted=self.studio.page('1.html')
        self.assertIn('historical-design',accepted['raw'])
        self.assertIn('First thought.',accepted['raw'])
        self.assertEqual((self.root/'1.html').read_bytes(),current.encode())
        accepted['raw']=accepted['raw'].replace('First thought.','Edited after acceptance.')
        accepted['fragments']['blocks'][2]['html']='<p>Edited after acceptance.</p>'
        self.studio.save_draft(accepted)
        self.studio.prepare()
        prepared=(self.root/'1.html').read_text()
        self.assertIn('historical-design',prepared)
        self.assertIn('Edited after acceptance.',prepared)
    def test_refuse_external_writing_change(self):
        d=self.draft();self.studio.save_draft(d)
        saved=copy.deepcopy(self.studio.state['drafts'].pop('1.html'))
        saved['file_hash']=digest((self.root/'1.html').read_bytes())
        self.studio.state['fragment_posts']['1.html']=saved;self.studio.save_state()
        (self.root/'1.html').write_text(saved['raw'].replace('First thought.','Changed outside.'))
        with self.assertRaises(FragmentFileConflict) as problem:self.studio.page('1.html')
        self.assertFalse(problem.exception.can_accept)
        with self.assertRaises(FragmentFileConflict):self.studio.accept_fragment_files(['1.html'])
    def test_public_quote_expansion_is_a_safe_file_difference(self):
        iid='0123456789abcdefghjkmnpqr'
        private=new_page('Quoted','<p>![[%s]]</p><p>Own writing.</p>'%iid)
        public=private.replace('<p>![[%s]]</p>'%iid,'<blockquote class="blyg-transclusion" data-blyg-id="%s" data-blyg-version="1"><p>Quoted writing.</p></blockquote>'%iid)
        self.assertEqual(self.studio.fragment_file_signature(private),self.studio.fragment_file_signature(public))
    def test_legacy_draft_has_no_fragment_metadata(self):
        d=self.studio.page('1.html');self.assertIsNone(d['fragments']);self.studio.save_draft(d);self.studio.prepare();self.assertEqual(self.studio.state['fragment_ids'],{})

    def test_clear_choices_does_not_restore_private_metadata(self):
        self.connect();d=self.draft();self.studio.save_draft(d);self.publish()
        d=self.studio.page('1.html');d['fragments']=None;self.studio.save_draft(d);self.publish()
        self.assertIsNone(self.studio.page('1.html')['fragments'])

    def test_explicit_recovery_clear_overrides_stale_fragment_source(self):
        d=self.draft();self.studio.save_draft(d)
        saved=copy.deepcopy(self.studio.state['drafts'].pop('1.html'));saved['file_hash']=digest((self.root/'1.html').read_bytes());self.studio.state['fragment_posts']['1.html']=saved;self.studio.save_state()
        reopened=self.studio.page('1.html');reopened['raw']=reopened['raw'].replace('First thought.','Edited without fragments.')
        reopened['fragments']=copy.deepcopy(saved['fragments'])
        reopened['clear_fragments']=True
        self.studio.save_draft(reopened)
        self.assertIsNone(self.studio.state['drafts']['1.html']['fragments'])
        self.assertIsNone(self.studio.page('1.html')['fragments'])

    def test_pages_shed_legacy_fragment_metadata_without_changing_html(self):
        before=(self.root/'index.html').read_bytes();source={'raw':before.decode(),'base':digest(before),'new':False,'fragments':self.draft()['fragments']}
        self.studio.state['drafts']['index.html']=copy.deepcopy(source)
        (self.root/'year-2018.html').write_text(new_page('2018','<p>Archive.</p>'))
        self.studio.state['standalone_pages'].append('year-2018.html')
        self.studio.state['fragment_posts']['year-2018.html']=copy.deepcopy(source)|{'raw':(self.root/'year-2018.html').read_text(),'file_hash':digest((self.root/'year-2018.html').read_bytes())}
        self.studio.save_state();reopened=Studio(self.root,self.base/'private')
        self.assertIsNone(reopened.state['drafts']['index.html']['fragments'])
        self.assertIsNone(reopened.state['fragment_posts']['year-2018.html']['fragments'])
        self.assertEqual((self.root/'index.html').read_bytes(),before)

    def test_page_save_cannot_reintroduce_fragment_metadata(self):
        d=self.studio.page('index.html');d['fragments']=self.draft()['fragments'];self.studio.save_draft(d)
        self.assertIsNone(self.studio.state['drafts']['index.html']['fragments'])

    def test_fragment_dialog_names_the_actual_page(self):
        script=re.sub(r'\s+','',(Path(__file__).parent/'static/app.js').read_text())
        self.assertIn("e.code==='fragment-state'",script)
        self.assertIn('openBrokenFragmentPage',script)
        self.assertIn('affected===page?.name',script)
    def test_generation_provenance_belongs_to_each_fragment(self):
        d=self.draft();m=d['fragments'];m['blocks'][2]['html']='<div class="blyg-tk-gen"><h1>A generated heading</h1><p>First generated thought.</p></div>'
        d['raw']=new_page('Test title',''.join(b['html'] for b in m['blocks'][1:]))
        d['generated']=[{'sources':[],'model':'first-model'},{'sources':[],'model':'second-model'}]
        self.studio.save_draft(d);self.studio.prepare();ids=self.studio.state['fragment_ids']['1.html']
        for key,model in [('first','first-model'),('tk','second-model')]:
            doc=json.loads((self.root/f'blyg/items/{ids[key]}.json').read_text())
            self.assertEqual(doc['generated'],[{'sources':[],'model':model}])

def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(FragmentTests)
