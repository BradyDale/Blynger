"""Openers uses the shared fragment model; publication uses a local bare Git remote."""
import copy, json, subprocess, unittest
from bs4 import BeautifulSoup
from core import Studio, new_page, clean, region
from fragments import openers_metadata, ranges
from reader import Reader
from test_core import StudioTests
from test_reader import Net, ORIGIN, IID, doc as remote_doc

class OpenerTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def seed(self):
        raw=new_page('Openers','<p>Introduction stays ordinary.</p><h3 id="same">September 25, 2026</h3><p>First opener.</p><p>Second paragraph.</p><h3 id="same">March 2, 2022</h3><p>Older opener.</p><strong id="20181119">November 19, 2018</strong><p>Oldest opener.</p>')
        (self.root/'openers.html').write_text(raw)
        return raw
    def connect(self):
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote))
    def publish(self):
        review=self.studio.prepare();self.studio.publish(review['signature'])
    def test_additive_idempotent_migration_preserves_page_and_dates(self):
        raw=self.seed();published=copy.deepcopy(self.studio.state['published']);r=self.studio.migrate_openers()
        self.assertEqual(r['count'],3);self.assertTrue(r['changed']);self.assertEqual(raw,(self.root/'openers.html').read_text())
        meta=copy.deepcopy(self.studio.state['fragment_posts']['openers.html']['fragments']);self.assertEqual(meta['version'],1)
        self.assertEqual([r['date_label'] for r in meta['ranges']],['September 25, 2026','March 2, 2022','November 19, 2018'])
        self.assertEqual([r['legacy_anchor'] for r in meta['ranges']],['same','same','20181119'])
        self.assertEqual(len(set(r['key'] for r in meta['ranges'])),3)
        self.assertEqual(self.studio.state['published'],published);self.assertEqual(self.studio.state['fragment_ids'],{})
        self.assertFalse(self.studio.migrate_openers()['changed']);self.assertEqual(meta,self.studio.page('openers.html')['fragments'])
        self.assertTrue((self.studio.data/'migrations/openers-fragments-v1.json').exists())
        bodies=[body for r,a,b,body in ranges(meta)];self.assertIn('Second paragraph.',bodies[0]);self.assertNotIn('Introduction', ''.join(bodies))
    def test_existing_draft_is_preserved_and_reopened(self):
        self.seed();d=self.studio.page('openers.html');d['raw']=d['raw'].replace('First opener.','Unpublished edit.')
        d.pop('fragments');self.studio.save_draft(d)
        s=Studio(self.root,self.studio.data);self.assertIn('Unpublished edit',s.page('openers.html')['body'])
        self.assertEqual(len(s.fragment_objects('openers.html')),3)
        self.assertTrue(all(not r['published'] and r['id'] is None for r in s.fragment_objects('openers.html')))
        self.assertNotIn('Unpublished edit',(self.root/'openers.html').read_text())
    def test_browser_repaired_block_layout_is_reconciled_on_save(self):
        raw=self.seed();self.studio.migrate_openers();d=self.studio.page('openers.html')
        original=copy.deepcopy(d['fragments']);submitted=copy.deepcopy(original)
        submitted['blocks'][1]['html']+=submitted['blocks'][2]['html'];del submitted['blocks'][2]
        d['fragments']=submitted
        self.studio.save_draft(d)
        saved=self.studio.page('openers.html')['fragments']
        self.assertEqual(len(saved['blocks']),len(original['blocks']))
        self.assertEqual([r['key'] for r in saved['ranges']],[r['key'] for r in original['ranges']])
        self.assertEqual(raw,self.studio.state['drafts']['openers.html']['raw'])
    def test_new_opener_is_internal_until_published_and_reuses_services(self):
        self.seed();self.studio.migrate_openers();d=self.studio.page('openers.html');oldkeys=[r['key'] for r in d['fragments']['ranges']]
        d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="new">September 26, 2026</h3><p>New thought.</p><h3 id="same">',1)
        d.pop('fragments');self.studio.save_draft(d);objects=self.studio.fragment_objects('openers.html')
        self.assertEqual(len(objects),4);self.assertEqual([o['reference']['key'] for o in objects[1:]],oldkeys)
        self.assertEqual(objects[0]['kind'],'fragment');self.assertIsNone(objects[0]['version'])
        self.assertFalse((self.root/'blyg/items/index.json').exists())
        self.connect();self.publish();objects=self.studio.fragment_objects('openers.html')
        self.assertTrue(all(o['published'] for o in objects));self.assertEqual(objects[0]['version'],1)
        iid=objects[0]['id'];self.assertRegex(iid,r'^[0-7][0-9a-hjkmnp-tv-z]{25}$')
        self.assertEqual(objects[0]['url'],'https://example.com/blyg/f/'+iid+'/')
        doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text());self.assertEqual(doc['kind'],'fragment');self.assertNotIn('purpose',doc)
        parent=self.studio.state['ids']['openers.html'];published_ids={item['id'] for item in json.loads((self.root/'blyg/items/index.json').read_text())['items']}
        self.assertNotIn(parent,published_ids);self.assertFalse((self.root/f'blyg/items/{parent}.json').exists())
        self.assertEqual(doc['updated'],doc['changelog'][-1]['at']);self.assertIn(iid,[f['id'] for f in self.studio.fragments()])
        self.assertTrue((self.root/f'blyg/f/{iid}/index.html').exists())
        opener_page=BeautifulSoup((self.root/f'blyg/f/{iid}/index.html').read_text(),'html.parser');self.assertEqual(opener_page.find('link',rel='blyg')['href'],'/blyg/');self.assertEqual(opener_page.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml')
        text=(self.root/'openers.html').read_text();self.assertNotIn('data-fragment',text);self.assertNotIn('class="fragment-dot"',text)
        self.assertIsNone(BeautifulSoup(text,'html.parser').find('link',rel='blyg'))
        self.assertEqual(BeautifulSoup(text,'html.parser').find_all(id='same').__len__(),2)

    def test_opener_response_publishes_as_thread_and_keeps_target(self):
        self.seed();self.studio.migrate_openers();d=self.studio.page('openers.html')
        d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="reply">September 27, 2026</h3><p>A concise response.</p><h3 id="same">',1);d.pop('fragments');self.studio.save_draft(d)
        saved=self.studio.page('openers.html');reply=saved['fragments']['ranges'][0];target={'origin':'https://remote.example/','id':'0'*25+'1','version':3,'cited':{'source':'Remote','author':'Other','excerpt':'Words','url':'https://remote.example/t/x/','retrieved':'2026-10-03T00:00:00Z'}};reply['stub_of']=target;saved['fragments']=saved['fragments'];self.studio.save_draft(saved);self.studio.prepare()
        iid=self.studio.state['fragment_ids']['openers.html'][reply['key']];doc=json.loads((self.root/f"blyg/items/{iid}.json").read_text())
        self.assertEqual(doc['kind'],'thread');self.assertEqual(doc['stub_of'],target);self.assertEqual(doc['transclusions'],[])
        self.assertEqual(self.studio.permalink(doc),'https://example.com/blyg/t/'+iid+'/');self.assertTrue((self.root/f"blyg/t/{iid}/index.html").exists())
        changed=self.studio.page('openers.html');changed['fragments']['ranges'][0]['stub_of']={**target,'version':4}
        with self.assertRaisesRegex(ValueError,'cannot be changed'):self.studio.save_draft(changed)

    def test_quick_opener_legacy_ui_path_writes_remote_transclusion_to_final_json(self):
        self.seed();self.studio.migrate_openers();net=Net();net.add(items=[remote_doc(kind='thread')]);self.studio.reader=Reader(self.studio.data,net,lambda:'2026-01-02T00:00:00Z');self.studio.reader.subscribe(ORIGIN)
        quoted=self.studio.reader.snapshot(self.studio.reader.key(ORIGIN,IID),{'mode':'whole'},self.studio);d=self.studio.page('openers.html')
        d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="reply">October 3, 2026, VI</h3>'+quoted['stub_html']+'<p>A concise response.</p><h3 id="same">',1)
        a,b=region(d['raw']);d['fragments']=openers_metadata(clean(d['raw'][a:b]),d['fragments']);d['fragments']['ranges'][0]['stub_of']=quoted['stub_of']
        # The real archive's submitted block map and raw HTML are equivalent,
        # but whitespace/entity serialization makes the range body unequal as
        # a byte string. Conversion must identify the actual block, not replace
        # a manufactured block-map substring.
        d['raw']=d['raw'].replace('</p><blockquote class="blynger-stub-context">','</p>\n<blockquote class="blynger-stub-context">',1)
        self.assertNotIn(next(ranges(d['fragments']))[3],d['raw'])
        self.studio.save_draft(d);saved=self.studio.page('openers.html');reply=saved['fragments']['ranges'][0]
        self.assertNotIn('blynger-stub-context',saved['body']);self.assertIn('data-blynger-quote',saved['body']);self.studio.prepare()
        iid=self.studio.state['fragment_ids']['openers.html'][reply['key']];final=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(final['kind'],'thread');self.assertEqual(final['stub_of'],quoted['stub_of']);self.assertEqual(final['transclusions'],[{'id':IID,'version':1,'origin':ORIGIN}])
        self.assertIn('![['+IID+']]',final['content_md']);self.assertIn('class="blyg-transclusion"',final['content_html']);self.assertIn('RewriteRule ^t/'+iid+'/?$ t/'+iid+'/index.html [END]',(self.root/'blyg/.htaccess').read_text())
        self.assertNotIn('blynger-citation',final['content_html']);self.assertNotIn('data-blynger-quote',final['content_html'])

    def test_untouched_historical_legacy_stub_is_not_silently_republished(self):
        self.seed();self.studio.migrate_openers();d=self.studio.page('openers.html')
        legacy='<blockquote class="blynger-stub-context"><p>Historical copied words.</p></blockquote>'
        d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="reply">October 3, 2026, VI</h3>'+legacy+'<p>Old response.</p><h3 id="same">',1)
        a,b=region(d['raw']);meta=openers_metadata(clean(d['raw'][a:b]),d['fragments']);meta['ranges'][0]['stub_of']={'origin':ORIGIN,'id':IID,'version':1}
        self.assertEqual(self.studio.upgrade_opener_stub_contexts(d['raw'],meta,meta,{}),d['raw'])

    def test_blyg_stub_opener_bakes_genuine_transclusion(self):
        self.seed();self.studio.migrate();self.studio.state['published']={p.stem:json.loads(p.read_text()) for p in (self.root/'blyg/items').glob('*.json') if p.name!='index.json'};self.studio.migrate_openers()
        source_id=self.studio.state['ids']['1.html'];quoted=self.studio.quote_item('local',source_id)
        d=self.studio.page('openers.html')
        source='<p class="blynger-stub-label"><strong>Stub of:</strong> <a href="https://example.com/blyg/f/'+source_id+'/">Old post</a></p>'+quoted['html']
        d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="reply">October 3, 2026, VI</h3>'+source+'<p>A concise response.</p><h3 id="same">',1)
        a,b=region(d['raw']);d['fragments']=openers_metadata(clean(d['raw'][a:b]),d['fragments'])
        d['fragments']['ranges'][0]['stub_of']=quoted['stub_of'];self.studio.save_draft(d);self.studio.prepare()
        reply=d['fragments']['ranges'][0];iid=self.studio.state['fragment_ids']['openers.html'][reply['key']]
        doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(doc['kind'],'thread');self.assertEqual(doc['stub_of'],quoted['stub_of'])
        self.assertEqual(doc['transclusions'],[{'id':source_id,'version':1}])
        self.assertIn('![[%s]]'%source_id,doc['content_md']);self.assertIn('blyg-transclusion',doc['content_html'])

    def test_existing_opener_keeps_its_fragment_permalink_when_it_becomes_a_stub(self):
        self.seed();self.studio.migrate_openers();self.connect();self.publish();d=self.studio.page('openers.html');reply=d['fragments']['ranges'][0];iid=self.studio.state['fragment_ids']['openers.html'][reply['key']]
        reply['stub_of']={'origin':'https://remote.example/','id':'0'*25+'1','version':3};self.studio.save_draft(d);self.studio.prepare();doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(doc['kind'],'thread');self.assertEqual(doc['page'],'f/'+iid+'/')
        page=BeautifulSoup((self.root/'openers.html').read_text(),'html.parser');self.assertEqual(page.select_one('.blynger-fragment-marker a')['href'],'https://example.com/blyg/f/'+iid+'/')

    def test_new_opener_pin_plan_persists_and_prepares_frozen_version(self):
        self.seed();self.studio.migrate_openers();d=self.studio.page('openers.html');d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="pinned">September 27, 2026</h3><p>Pin me.</p><h3 id="same">',1);d.pop('fragments');self.studio.save_draft(d)
        d=self.studio.page('openers.html');d['fragments']['ranges'][0]['pin_on_publish']=True;key=d['fragments']['ranges'][0]['key'];self.studio.save_draft(d);self.studio.prepare();iid=self.studio.state['fragment_ids']['openers.html'][key];doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertTrue(doc['changelog'][-1]['pinned']);self.assertTrue((self.root/f'blyg/items/{iid}/v1.json').exists())
    def test_edit_republish_and_quote_preserve_identity_and_snapshot(self):
        self.seed();self.studio.migrate_openers();self.connect();self.publish()
        old=self.studio.fragment_objects('openers.html')[0];iid=old['id'];parent=self.studio.state['ids']['openers.html']
        d=self.studio.create('Reuse an opener');d['raw']=d['raw'].replace('Start writing here.','![['+iid+']]');self.studio.save_draft(d);self.publish()
        tid=self.studio.state['ids'][d['name']];snapshot=copy.deepcopy(self.studio.state['published'][tid])
        d=self.studio.page('openers.html');d['raw']=d['raw'].replace('First opener.','Revised opener.');d.pop('fragments');self.studio.save_draft(d);self.publish()
        latest=self.studio.fragment_objects('openers.html')[0];self.assertEqual(latest['id'],iid);self.assertEqual(latest['version'],2)
        self.assertEqual(self.studio.state['ids']['openers.html'],parent)
        self.assertEqual(self.studio.state['published'][tid],snapshot)
        self.assertEqual(self.studio.state['published'][iid]['created'],self.studio.state['history'][iid]['1']['created'])
    def test_rss_only_announces_future_openers_and_keeps_archive_endpoints(self):
        import xml.etree.ElementTree as ET
        from core import NS
        self.seed();self.studio.migrate_openers();self.connect();self.publish()
        legacy={o['id'] for o in self.studio.fragment_objects('openers.html')};parent=self.studio.state['ids']['openers.html']
        def protocol_ids():return {n.text for n in ET.parse(self.root/'blyg/feed.xml').findall('.//{'+NS+'}id')}
        def site_links():return {n.text for n in ET.parse(self.root/'feed.xml').findall('./channel/item/link')}
        legacy_links={'https://example.com/blyg/f/'+iid+'/' for iid in legacy}
        self.assertTrue(legacy <= protocol_ids());self.assertNotIn(parent,protocol_ids());self.assertFalse(legacy_links & site_links())
        d=self.studio.page('openers.html');d['raw']=d['raw'].replace('<h3 id="same">','<h3 id="future">September 27, 2026</h3><p>A future thought.</p><h3 id="same">',1);d.pop('fragments');self.studio.save_draft(d)
        self.studio=Studio(self.root,self.studio.data);self.publish();new=self.studio.fragment_objects('openers.html')[0]['id'];new_link='https://example.com/blyg/f/'+new+'/';self.assertIn(new,protocol_ids());self.assertNotIn(parent,protocol_ids());self.assertIn(new_link,site_links());self.assertFalse(legacy_links & site_links());self.assertTrue(all((self.root/f'blyg/items/{i}.json').exists() for i in legacy))
        d=self.studio.page('openers.html');d['raw']=d['raw'].replace('Older opener.','Older opener revised.');d.pop('fragments');self.studio.save_draft(d);self.publish();self.assertTrue(legacy <= protocol_ids());self.assertIn(new,protocol_ids());self.assertIn(new_link,site_links());self.assertFalse(legacy_links & site_links())
    def test_upgrade_baselines_existing_published_opener_keys_once(self):
        self.seed();self.studio.migrate_openers();self.connect();self.publish();self.studio.state.pop('opener_rss_legacy_keys');self.studio.save_state()
        reloaded=Studio(self.root,self.studio.data);self.assertEqual(len(reloaded.state['opener_rss_legacy_keys']),3);self.assertEqual(reloaded.state['fragment_ids'],self.studio.state['fragment_ids'])
    def test_no_automatic_fragmentation_of_posts(self):
        self.seed();self.studio.migrate_openers();self.assertIsNone(self.studio.page('1.html')['fragments'])
    def test_migration_of_actual_archive_is_lossless(self):
        from pathlib import Path
        from configuration import load
        try:settings=load()
        except ValueError:self.skipTest('Private integration settings not present')
        p=(Path(settings['site_root'])/'openers.html').resolve()
        if not p.exists():self.skipTest('Real archive not present')
        raw=p.read_text();a,b=region(raw);body=clean(raw[a:b]);meta=openers_metadata(body)
        self.assertEqual(meta,openers_metadata(body,meta));self.assertGreaterEqual(len(meta['ranges']),119)
        self.assertEqual(''.join(BeautifulSoup(b['html'],'html.parser').get_text() for b in meta['blocks']),''.join(n.get_text() for n in BeautifulSoup(body,'html.parser').contents if str(n).strip()))
        (self.root/'openers.html').write_text(raw);before=(self.root/'openers.html').read_bytes();self.studio.migrate_openers();self.assertEqual(before,(self.root/'openers.html').read_bytes())
    def test_old_dividers_become_fragments_without_changing_prose(self):
        from fragments import designate_sections,validate
        blocks=[{'id':'b'+str(i),'html':h} for i,h in enumerate(['<h1>Title</h1>','<p>First.</p>','<p>Second.</p>','<p>Third.</p>','<p>—Example Author</p>'])]
        meta={'version':1,'blocks':blocks,'dividers':['b2','b3'],'ranges':[]}
        result=designate_sections(meta)
        self.assertEqual(result['blocks'],blocks)
        self.assertEqual(len(result['ranges']),3)
        self.assertEqual(result,designate_sections(result))
        self.assertEqual([body for r,a,b,body in ranges(result)],['<p>First.</p>','<p>Second.</p>','<p>Third.</p>'])

    def test_public_dots_are_presentation_only_and_repeatable(self):
        self.seed();self.studio.migrate_openers();self.connect();self.publish()
        before=(self.root/'openers.html').read_text();self.studio.prepare()
        self.assertEqual(before,(self.root/'openers.html').read_text())
        soup=BeautifulSoup(before,'html.parser');links=soup.select('.blynger-fragment-marker a')
        self.assertEqual(len(links),3)
        self.assertTrue(all(a.get('title')=='Fragment' and not a.get_text() for a in links))
        for d in self.studio.state['published'].values():
            self.assertNotIn('blynger-fragment-marker',d['content_html'])
            self.assertNotIn('blynger-fragment-marker',d['content_md'])
        self.assertNotIn('blynger-fragment-marker',self.studio.page('openers.html')['raw'])

    def test_discovery_is_not_backfilled_into_unchanged_historical_fragment_page(self):
        self.seed();self.studio.migrate_openers();self.connect();self.publish();iid=self.studio.fragment_objects('openers.html')[0]['id'];path=self.root/f'blyg/f/{iid}/index.html';historical=path.read_text().replace('<link rel="blyg" href="/blyg/">\n','').replace('<link rel="alternate" type="application/rss+xml" title="Example Author&#x27;s blyg" href="/feed.xml">\n','');path.write_text(historical);before=path.read_bytes();self.studio.prepare()
        self.assertEqual(path.read_bytes(),before);self.assertIsNone(BeautifulSoup(path.read_text(),'html.parser').find('link',rel='blyg'))


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(OpenerTests)
