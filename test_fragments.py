import copy, json, re, subprocess, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
from core import Studio, new_page, digest, region, FragmentFileConflict, FragmentStateError
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
        raw=s.state['drafts']['1.html']['raw']
        self.assertIn('data-blynger-block="b2"',raw)
        self.assertIn('data-blynger-fragment="first"',raw)
        self.assertIn('data-blynger-break=""',raw)

    def test_durable_markers_recover_a_missing_private_map(self):
        d=self.draft();self.studio.save_draft(d)
        self.studio.state['drafts']['1.html']['fragments']=None
        self.studio.save_state()
        reopened=Studio(self.root,self.base/'private').page('1.html')
        self.assertEqual(reopened['fragments']['ranges'],d['fragments']['ranges'])
        self.assertEqual([b['id'] for b in reopened['fragments']['blocks']],[f'b{i}' for i in range(7)])

    def test_atomic_transclusion_refresh_preserves_durable_block_marker(self):
        d=self.studio.page('1.html')
        token='quote-token'
        quote='<blockquote class="blyg-transclusion" data-blynger-quote="'+token+'" data-blyg-id="00000000000000000000000000" data-blyg-version="1"><p>Exact source words.</p></blockquote>'
        blocks=['<h1>Test title</h1>','<p>Introduction.</p>',quote,'<p>Authored response.</p>','<p>—Example Author<br>September 26, 2026</p>']
        meta={'version':1,'blocks':[{'id':f'q{i}','html':block} for i,block in enumerate(blocks)],'dividers':['q3'],'ranges':[{'key':'response','start':'q3','end':'q4'}]}
        marked=fragments.embed(meta,''.join(blocks))
        raw=new_page('Test title','<p>Temporary.</p>')
        start,end=region(raw)
        d['raw']=raw[:start]+marked+raw[end:]
        d['fragments']=meta
        d['quotes']={token:{'visible_html':quote,'token':token}}
        self.studio.save_draft(d)
        saved=self.studio.state['drafts']['1.html']['raw']
        soup=BeautifulSoup(saved,'html.parser')
        protected=soup.select_one('blockquote[data-blynger-quote="'+token+'"]')
        self.assertEqual(protected['data-blynger-block'],'q2')
        self.assertEqual(self.studio.page('1.html')['fragments']['ranges'],meta['ranges'])

    def test_whole_fragment_movement_keeps_its_identity(self):
        d=self.draft();self.studio.save_draft(d)
        raw=self.studio.state['drafts']['1.html']['raw'];a,b=region(raw)
        soup=BeautifulSoup(raw[a:b],'html.parser');nodes=[node for node in soup.contents if getattr(node,'name',None)]
        first=nodes[2:4]
        for node in first:node.extract()
        nodes[1].insert_before(*first)
        moved=raw[:a]+str(soup)+raw[b:]
        self.studio.state['drafts']['1.html']['raw']=moved
        recovered=self.studio.page('1.html')['fragments']
        item=next(item for item in recovered['ranges'] if item['key']=='first')
        self.assertEqual((item['start'],item['end']),('b2','b1'))
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
            self.assertNotIn('data-blynger-',doc['content_html'])
        human=(self.root/'1.html').read_text()
        self.assertIn('data-blynger-block=',human);self.assertIn('data-blynger-fragment=',human)
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
    def test_fragment_can_begin_with_a_managed_image_during_publication(self):
        image=b'fragment-cover';filename=digest(image)+'.jpg'
        folder=self.root/'images'/'blynger';folder.mkdir(parents=True,exist_ok=True)
        (folder/filename).write_bytes(image)
        d=self.studio.page('1.html')
        blocks=['<h1>Test title</h1>','<p class="blynger-image blynger-image-standard"><img alt="Cover" src="/images/blynger/'+filename+'"></p>','<p>Fragment prose.</p>','<p>—Example Author<br>October 16, 2026</p>']
        meta={'version':1,'blocks':[{'id':f'i{i}','html':block} for i,block in enumerate(blocks)],'dividers':['i1'],'ranges':[{'key':'image-fragment','start':'i1','end':'i3'}]}
        marked=fragments.embed(meta,''.join(blocks));raw=new_page('Test title','<p>Temporary.</p>');a,b=region(raw)
        d['raw']=raw[:a]+marked+raw[b:];d['fragments']=meta
        self.studio.save_draft(d);self.studio.prepare()
        iid=self.studio.state['fragment_ids']['1.html']['image-fragment']
        doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertIn('/blyg/media/'+filename,doc['content_html'])
        self.assertIn('data-blynger-fragment="image-fragment"',(self.root/'1.html').read_text())
    def test_internal_link_absolutizing_does_not_delete_fragment_boundary(self):
        blocks=['<h1>Title</h1>','<p>First section.</p>','<p>Read <a href="/25.html">Biting the Sun</a>.</p>','<p>—Example Author<br>October 16, 2026</p>']
        meta={'version':1,'blocks':[{'id':f'link{i}','html':block} for i,block in enumerate(blocks)],'dividers':['link1'],'ranges':[{'key':'first','start':'link1','end':'link2'},{'key':'second','start':'link2','end':'link3'}]}
        public=''.join(blocks).replace('href="/25.html"','href="https://example.com/25.html"')
        rebased=fragments.rebase_managed(meta,public,'https://example.com/')
        self.assertEqual([(r['key'],r['start'],r['end']) for r in rebased['ranges']],[('first','link1','link2'),('second','link2','link3')])
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
    def test_public_local_urls_and_identical_media_are_safe_differences(self):
        filename = 'a' * 64 + '.jpg'
        original = self.root / 'images' / 'blynger' / filename
        mirror = self.root / 'blyg' / 'media' / filename
        original.parent.mkdir(parents=True)
        mirror.parent.mkdir(parents=True)
        original.write_bytes(b'exact same image')
        mirror.write_bytes(original.read_bytes())
        private = new_page('Title', '<p><a href="/2.html">Next</a><img src="/images/blynger/' + filename + '"></p>')
        public = private.replace('href="/2.html"', 'href="https://example.com/2.html"').replace('/images/blynger/', 'https://example.com/blyg/media/')
        self.assertEqual(self.studio.fragment_file_signature(private), self.studio.fragment_file_signature(public))
        mirror.write_bytes(b'different image')
        self.assertNotEqual(self.studio.fragment_file_signature(private), self.studio.fragment_file_signature(public))
        self.assertNotEqual(self.studio.fragment_file_signature(private), self.studio.fragment_file_signature(private.replace('/2.html', 'https://elsewhere.example/2.html')))
        self.assertNotEqual(self.studio.fragment_file_signature(private), self.studio.fragment_file_signature(private.replace('/2.html', '/3.html')))

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
        self.assertNotIn('data-blynger-',self.studio.state['drafts']['1.html']['raw'])

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
        self.assertIn('repairBrokenFragments',script)
        self.assertIn('Rebuildfragmentmarkersandsavedraft',script)
        self.assertIn('affected===page?.name',script)
    def test_generation_provenance_belongs_to_each_fragment(self):
        d=self.draft();m=d['fragments'];m['blocks'][2]['html']='<div class="blyg-tk-gen"><h1>A generated heading</h1><p>First generated thought.</p></div>'
        d['raw']=new_page('Test title',''.join(b['html'] for b in m['blocks'][1:]))
        d['generated']=[{'sources':[],'model':'first-model'},{'sources':[],'model':'second-model'}]
        self.studio.save_draft(d);self.studio.prepare();ids=self.studio.state['fragment_ids']['1.html']
        for key,model in [('first','first-model'),('tk','second-model')]:
            doc=json.loads((self.root/f'blyg/items/{ids[key]}.json').read_text())
            self.assertEqual(doc['generated'],[{'sources':[],'model':model}])

    def test_new_post_with_tk_and_manual_boundaries_saves_and_prepares(self):
        d=self.studio.page('1.html')
        blocks=[
            '<h1>Test title</h1>',
            '<p>Before TK.</p>',
            '<div class="blyg-tk-gen"><p>Generated thought.</p></div>',
            '<p>After TK.</p>',
            '<p>Manually separated thought.</p>',
            '<p>—Example Author<br>October 16, 2026</p>',
        ]
        meta={
            'version':1,
            'blocks':[{'id':f't{i}','html':block} for i,block in enumerate(blocks)],
            'dividers':['t1','t2','t3','t4'],
            'ranges':[
                {'key':'before','start':'t1','end':'t2'},
                {'key':'generated','start':'t2','end':'t3'},
                {'key':'after','start':'t3','end':'t4'},
                {'key':'manual','start':'t4','end':'t5'},
            ],
        }
        marked=fragments.embed(meta,''.join(blocks))
        raw=new_page('Test title','<p>Temporary.</p>');a,b=region(raw)
        d['raw']=raw[:a]+marked+raw[b:]
        d['fragments']=copy.deepcopy(meta)
        d['generated']=[{'sources':[],'model':'test-model'}]
        self.studio.save_draft(d)
        saved=self.studio.page('1.html')
        self.assertEqual(saved['fragments']['ranges'],meta['ranges'])
        self.studio.prepare()
        ids=self.studio.state['fragment_ids']['1.html']
        self.assertEqual(set(ids),{'before','generated','after','manual'})
        generated=json.loads((self.root/f"blyg/items/{ids['generated']}.json").read_text())
        self.assertIn('Generated thought.',generated['content_html'])
        self.assertEqual(generated['generated'],[{'sources':[],'model':'test-model'}])

def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(FragmentTests)
