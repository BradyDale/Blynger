import hashlib, json, re, subprocess, tempfile, unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from core import Studio, new_page, NS

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name); self.root=self.base/'site'; self.root.mkdir(); (self.root/'images').mkdir()
        (self.root/'index.html').write_text(new_page('Home','<h3>Posts</h3><a href="/1.html">Old post</a>'))
        (self.root/'1.html').write_text(new_page('Old post','<p>Original <a href="/openers.html">words</a>.</p>'))
        (self.root/'openers.html').write_text(new_page('Openers','<h3>March 2</h3><p>An opening thought.</p>'))
        subprocess.run(['git','init','-b','master'],cwd=self.root,capture_output=True,check=True)
        for key,value in [('user.name','Test'),('user.email','test@example.invalid')]: subprocess.run(['git','config',key,value],cwd=self.root,check=True)
        subprocess.run(['git','add','.'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','Initial'],cwd=self.root,check=True)
        self.studio=Studio(self.root,self.base/'private')
    def tearDown(self): self.tmp.cleanup()
    def test_migration_preserves_pages_ids_and_protocol(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.html')}; self.studio.migrate(); ids=dict(self.studio.state['ids']); self.studio.migrate()
        self.assertEqual(ids,self.studio.state['ids']); self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.html')})
        index=json.loads((self.root/'blyg/items/index.json').read_text()); self.assertEqual(len(index['items']),1)
        for item in index['items']:
            self.assertRegex(item['id'],r'^[0-7][0-9a-hjkmnp-tv-z]{25}$')
            d=json.loads((self.root/'blyg/items'/f"{item['id']}.json").read_text()); self.assertEqual(d['content_hash'],'sha256:'+hashlib.sha256(d['content_md'].encode()).hexdigest()); self.assertEqual(d['updated'],d['changelog'][-1]['at'])
            self.assertNotIn('title',d);self.assertNotIn('url',d);self.assertEqual(d['page'],'f/'+d['id']+'/')
        self.assertEqual({d['id'] for d in index['items']},{self.studio.state['ids']['1.html']})
        self.assertNotIn('index.html',self.studio.state['ids'])
        rss=ET.parse(self.root/'blyg/feed.xml'); self.assertIsNotNone(rss.find('./channel/{'+NS+'}manifest'))
        self.assertEqual(rss.find('./channel/{'+NS+'}manifest').text,self.studio.origin+'blyg.json')
        links=rss.findall('./channel/{http://www.w3.org/2005/Atom}link'); self.assertEqual(len(links),1)
        self.assertEqual(links[0].attrib,{'href':self.studio.origin+'feed.xml','rel':'self','type':'application/rss+xml'})
        manifest=json.loads((self.root/'blyg/blyg.json').read_text());self.assertEqual(manifest['level'],2);self.assertEqual(manifest['feed'],'feed.xml');self.assertEqual(manifest['items'],'items/index.json');self.assertEqual(manifest['generator_url'],'https://github.com/BradyDale/Blynger')

    def test_blyg_index_uses_configured_favicon(self):
        self.studio.config['favicon']='/images/favicon.png';self.studio.migrate()
        soup=__import__('bs4').BeautifulSoup((self.root/'blyg/index.html').read_text(),'html.parser')
        self.assertEqual([link['href'] for link in soup.find_all('link',rel='icon')],['/images/favicon.png'])
        blyg_home=__import__('bs4').BeautifulSoup((self.root/'blyg/index.html').read_text(),'html.parser');self.assertEqual(blyg_home.find('link',rel='blyg')['href'],'/blyg/');self.assertEqual(blyg_home.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml')

    def test_plain_blyg_id_link_is_a_link_not_a_transclusion(self):
        self.studio.migrate();iid=self.studio.state['ids']['1.html']
        d=self.studio.create('Linking post');d['raw']=d['raw'].replace('Start writing here.','See [['+iid+']] for context.');self.studio.save_draft(d);self.studio.prepare()
        own=self.studio.state['ids'][d['name']];doc=json.loads((self.root/f'blyg/items/{own}.json').read_text())
        self.assertNotIn('transclusions',doc);self.assertIn('href="https://example.com/blyg/f/'+iid+'/"',doc['content_html']);self.assertNotIn('[[',doc['content_html'])

    def test_explicit_version_directive_is_rejected(self):
        d=self.studio.create('Reserved syntax');d['raw']=d['raw'].replace('Start writing here.','![[00000000000000000000000000@v1]]');self.studio.save_draft(d)
        with self.assertRaisesRegex(ValueError,'Explicit-version quote directives'):self.studio.prepare()

    def test_authored_page_discovers_its_item_json_and_calm_feed(self):
        self.studio.migrate();self.studio.state['published']={p.stem:json.loads(p.read_text()) for p in (self.root/'blyg/items').glob('*.json') if p.name!='index.json'};self.studio.remember(self.studio.state['published'])
        d=self.studio.page('1.html');d['raw']=d['raw'].replace('Original','Changed');self.studio.save_draft(d);self.studio.prepare()
        iid=self.studio.state['ids']['1.html'];soup=__import__('bs4').BeautifulSoup((self.root/'1.html').read_text(),'html.parser')
        self.assertEqual(soup.find('link',rel='alternate',type='application/json')['href'],self.studio.origin+'items/'+iid+'.json')
        self.assertEqual(soup.find('link',rel='blyg')['href'],'/blyg/')
        self.assertEqual(soup.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml')
    def test_new_post_and_touched_homepage_have_distinct_idempotent_discovery(self):
        from bs4 import BeautifulSoup
        page=self.studio.create('Discovery post');self.studio.prepare();first={name:(self.root/name).read_bytes() for name in (page['name'],'index.html')};self.studio.prepare()
        for name in (page['name'],'index.html'):
            self.assertEqual((self.root/name).read_bytes(),first[name]);soup=BeautifulSoup(first[name],'html.parser')
            self.assertEqual([link['href'] for link in soup.find_all('link',rel='blyg')],['/blyg/'])
            self.assertEqual([link['href'] for link in soup.find_all('link',rel='alternate',type='application/rss+xml')],['/feed.xml'])
        self.assertIsNotNone(BeautifulSoup(first[page['name']],'html.parser').find('link',rel='alternate',type='application/json'))
        self.assertIsNone(BeautifulSoup(first['index.html'],'html.parser').find('link',rel='alternate',type='application/json'))

    def test_ordinary_feed_keeps_77_entries_while_protocol_feed_keeps_50_events(self):
        from datetime import datetime,timezone,timedelta
        start=datetime(2026,1,1,tzinfo=timezone.utc)
        for n in range(2,82):
            raw=new_page('Post '+str(n),'<p>Words '+str(n)+'</p>')
            at=(start+timedelta(days=n)).isoformat().replace('+00:00','Z')
            raw=raw.replace('</head>','<meta property="article:published_time" content="'+at+'">\n</head>')
            (self.root/f'{n}.html').write_text(raw)
        self.studio.prepare()
        ordinary=ET.parse(self.root/'feed.xml').findall('./channel/item');protocol=ET.parse(self.root/'blyg/feed.xml').findall('./channel/item')
        self.assertEqual(len(ordinary),77);self.assertEqual(len(protocol),50)
        from email.utils import parsedate_to_datetime
        dates=[parsedate_to_datetime(item.find('pubDate').text) for item in ordinary]
        self.assertEqual(dates,sorted(dates,reverse=True));self.assertEqual(len(set(dates)),77)
    def test_draft_does_not_modify_original_and_conflict_blocks(self):
        d=self.studio.page('1.html'); before=(self.root/'1.html').read_bytes(); d['raw']=d['raw'].replace('Original','Edited'); self.studio.save_draft(d); self.assertEqual(before,(self.root/'1.html').read_bytes())
        (self.root/'1.html').write_text('External change')
        with self.assertRaises(ValueError): self.studio.prepare()
    def test_numbered_posts_preserve_existing_and_reserve_drafts(self):
        (self.root/'42.html').write_text(new_page('Existing','Keep me'))
        (self.root/'2026-09-25-new-post.html').write_text(new_page('Recent','Keep this too'))
        self.assertEqual(self.studio.create('Next')['name'],'43.html')
        self.assertEqual(self.studio.create('After that')['name'],'44.html')
        self.assertIn('Keep this too',(self.root/'2026-09-25-new-post.html').read_text())

    def test_standalone_page_does_not_advance_post_sequence(self):
        self.studio.create_page('Archive for 2018','year-2018.html')
        self.assertEqual(self.studio.create('Next post')['name'],'2.html')

    def test_new_post_pin_choice_defaults_off_persists_and_prepares_pin(self):
        d=self.studio.create('Pin choice');self.assertTrue(d['pin_available']);self.assertFalse(d['pin_on_publish'])
        d['pin_on_publish']=True;self.studio.save_draft(d);self.assertTrue(Studio(self.root,self.studio.data).page(d['name'])['pin_on_publish'])
        review=self.studio.prepare();iid=self.studio.state['ids'][d['name']];doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertTrue(doc['changelog'][-1]['pinned']);self.assertTrue((self.root/f'blyg/items/{iid}/v1.json').exists());self.assertEqual(review['planned_pins'],1)

    def test_later_post_revision_can_be_pinned_from_editor(self):
        remote=self.base/'later-pin.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);self.studio.git('remote','add','website',str(remote))
        d=self.studio.create('Later pin');review=self.studio.prepare();self.studio.publish(review['signature']);self.assertTrue(self.studio.page(d['name'])['pin_available'])
        revised=self.studio.revise(d['name'],'Second version');revised['raw']=revised['raw'].replace('Start writing here.','Changed later.');revised['pin_on_publish']=True;self.studio.save_draft(revised)
        review=self.studio.prepare();iid=self.studio.state['ids'][d['name']];doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(doc['version'],2);self.assertTrue(doc['changelog'][-1]['pinned']);self.assertEqual(review['planned_pins'],1)

    def test_authored_quotes_become_ascii_but_quoted_and_forked_text_stays_exact(self):
        d=self.studio.create('Quotes');d['raw']=d['raw'].replace('Start writing here.','“Authored” isn’t curly. <blockquote class="blynger-citation"><p>“Exact source”</p></blockquote>');self.studio.save_draft(d);saved=self.studio.page(d['name'])['raw']
        self.assertIn('"Authored" isn\'t curly.',saved);self.assertIn('“Exact source”',saved)
        fork=self.studio.create('Fork',body='<p>“Exact fork”</p>',forked_from={'origin':'https://remote.example/','id':'0'*25+'1','version':1});self.studio.save_draft(fork);self.assertIn('“Exact fork”',self.studio.page(fork['name'])['raw'])

    def test_fragment_blocks_follow_authored_quote_normalization(self):
        from bs4 import BeautifulSoup
        d=self.studio.create('Curly fragment',body='<p>Andrew’s finding.</p>');nodes=[str(n) for n in BeautifulSoup(d['body'],'html.parser').contents if str(n).strip()];blocks=[{'id':'b'+str(i),'html':node} for i,node in enumerate(nodes)];d['fragments']={'version':1,'blocks':blocks,'dividers':[],'ranges':[]}
        self.studio.save_draft(d);saved=self.studio.page(d['name'])
        self.assertIn("Andrew's finding.",saved['body']);self.assertIn("Andrew's finding.",''.join(b['html'] for b in saved['fragments']['blocks']))

    def test_new_standalone_page_is_ordinary_site_content_only(self):
        from bs4 import BeautifulSoup
        home_before=(self.root/'index.html').read_text()
        page=self.studio.create_page('Posts, 2015–2017','2015-2017.html')
        self.assertEqual(page['kind'],'page');self.assertEqual(page['name'],'2015-2017.html');self.assertTrue(page['draft'])
        self.assertIsNone(page['fragments']);self.assertNotIn('2015-2017.html',self.studio.state['ids'])
        listing={p['name']:p for p in self.studio.pages()};self.assertEqual(listing['2015-2017.html']['kind'],'page')
        soup=BeautifulSoup(page['raw'],'html.parser');self.assertEqual(len(soup.find_all('nav')),2)
        self.assertEqual(soup.find('link',rel='canonical')['href'],'https://example.com/2015-2017.html')
        self.assertIsNone(soup.find('link',rel='blyg'));self.assertIsNone(soup.find('meta',attrs={'name':'blyg:protocol-version'}))
        self.assertEqual(json.loads(soup.find('script',type='application/ld+json').string)['@type'],'WebPage')
        page['raw']=page['raw'].replace('Start writing here.','A freely edited archive page.');self.studio.save_draft(page)
        self.assertIn('freely edited',Studio(self.root,self.studio.data).page('2015-2017.html')['body'])
        self.studio.prepare(review=False)
        home_after=(self.root/'index.html').read_text();self.assertNotIn('2015-2017.html',home_after);self.assertIn('Old post',home_after)
        self.assertIn('2015-2017.html',(self.root/'sitemap.xml').read_text())
        self.assertNotIn('blynger-versions',(self.root/'2015-2017.html').read_text())
        self.assertIsNone(BeautifulSoup((self.root/'2015-2017.html').read_text(),'html.parser').find('link',rel='blyg'))
        index=json.loads((self.root/'blyg/items/index.json').read_text())
        self.assertNotIn('2015-2017.html',json.dumps(index));self.assertNotIn('2015-2017.html',self.studio.state['ids'])
        remote=self.base/'standalone-remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote));review=self.studio.review();self.studio.publish(review['signature'])
        self.assertIn('2015-2017.html',self.studio.git('ls-tree','-r','--name-only','HEAD').splitlines())
        self.assertEqual(self.studio.create('Next post')['name'],'2.html')

    def test_new_page_rejects_unsafe_or_existing_filename(self):
        for name in ('../escape.html','nested/page.html','bad.txt','template.html','1.html','2018.html'):
            with self.subTest(name=name),self.assertRaises(ValueError):self.studio.create_page('Nope',name)

    def test_new_page_ui_and_filename_suggestion_exist(self):
        html=(Path(__file__).parent/'static/index.html').read_text();script=(Path(__file__).parent/'static/app.js').read_text()
        self.assertIn('id="newPage"',html);self.assertIn("$('newPage').onclick",script)
        self.assertIn("return (stem||'new-page')+'.html'",script)

    def test_fragment_dialog_uses_simple_break_language(self):
        script=(Path(__file__).parent/'static/app.js').read_text()
        self.assertIn('fragmentEditor.addDivider()',script)
        self.assertIn('fragmentEditor.removeDivider()',script)
        self.assertNotIn('Use section as fragment / ordinary prose',script)

    def test_new_post_navigation_is_outside_feed_body(self):
        from bs4 import BeautifulSoup
        d=self.studio.create('Navigation test');self.studio.prepare()
        raw=(self.root/d['name']).read_text();soup=BeautifulSoup(raw,'html.parser');navs=soup.find_all('nav');self.assertEqual(len(navs),2)
        for nav in navs:
            self.assertIsNone(nav.find_parent('article'));self.assertEqual(len(nav.find_all('a')),5);self.assertIsNotNone(nav.find('a',href='https://social.example/example'))
        iid=self.studio.state['ids'][d['name']];doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text());self.assertNotIn('home.JPG',doc['content_html']);self.assertNotIn('<nav',doc['content_html'])
        for item in ET.parse(self.root/'blyg/feed.xml').findall('./channel/item'):
            if item.find('{'+NS+'}id').text==iid:self.assertNotIn('home.JPG',item.find('description').text)
        self.studio.prepare();self.assertEqual((self.root/d['name']).read_text(),raw)
    def test_repair_missing_footer_once_and_preserve_manual_layout(self):
        from core import restore_post_navigation,post_navigation
        raw=new_page('Post','Words');raw=raw.replace('</article>'+post_navigation(),'</article>')
        repaired=restore_post_navigation(raw,'46.html');self.assertEqual(repaired.count('<nav'),2);self.assertEqual(restore_post_navigation(repaired,'46.html'),repaired)
        manual='<html><body><a href="/index.html">Home</a>Old text</body></html>';self.assertEqual(restore_post_navigation(manual,'1.html'),manual)
    def test_posts_heading_levels_and_inline_formatting(self):
        from bs4 import BeautifulSoup
        for level in range(1,7):
            with self.subTest(level=level):
                if level>1:self.tearDown();self.setUp()
                home=self.root/'index.html';home.write_text(new_page('Home',f'<h{level} class="section"><span>Posts</span></h{level}><a href="/1.html">Old post</a>'))
                if not self.studio.state['drafts']:self.studio.create('New quote')
                self.studio.prepare();self.studio.prepare()
                soup=BeautifulSoup(home.read_text(),'html.parser');heading=soup.find('h'+str(level),class_='section');self.assertIsNotNone(heading);self.assertEqual(heading.find_next_sibling('a').get_text(),'New quote');self.assertEqual(len(soup.select('a[href="/2.html"]')),1)
    def test_missing_or_ambiguous_posts_heading_preserves_homepage(self):
        for body in ['<h2>Something else</h2>','<h2>Posts</h2><h3>Posts</h3>']:
            home=self.root/'index.html';home.write_text(new_page('Home',body));before=home.read_bytes()
            if not self.studio.state['drafts']:self.studio.create('New quote')
            with self.assertRaises(ValueError):self.studio.prepare()
            self.assertEqual(home.read_bytes(),before)
    def test_new_posts_prepend_once_and_repeated_prepare_no_version_bump(self):
        self.studio.create('First new post'); self.studio.create('Second new post'); self.studio.prepare(); home=(self.root/'index.html').read_text(); self.studio.prepare()
        self.assertEqual(home,(self.root/'index.html').read_text()); self.assertEqual(home.count('First new post'),1)
        for p in (self.root/'blyg/items').glob('*.json'):
            if p.name!='index.json': self.assertEqual(json.loads(p.read_text())['version'],1)
    def test_prepare_can_skip_discarded_review_and_tracks_only_byte_changes(self):
        self.studio.create('New post');self.studio.review=lambda:self.fail('prepare performed an unnecessary review')
        first=self.studio.prepare(review=False);self.assertGreater(first['changed'],0)
        self.studio.state['pending']=[];self.studio.save_state()
        second=self.studio.prepare(review=False);self.assertEqual(second['changed'],0);self.assertEqual(self.studio.state['pending'],[])
    def test_review_ignores_stale_pending_paths_identical_to_baseline(self):
        self.studio.state['pending']=['1.html'];self.studio.save_state()
        self.assertNotIn('1.html',[c['path'] for c in self.studio.review()['changes']])
    def test_review_and_publish_include_explicit_file_removals(self):
        obsolete=self.root/'obsolete.html';obsolete.write_text(new_page('Obsolete','<p>Remove me.</p>'))
        self.studio.git('add','obsolete.html');self.studio.git('commit','-m','Add obsolete fixture')
        obsolete.unlink()
        remote=self.base/'removal-remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote))
        self.assertTrue(self.studio.publication_status()['ready'])
        review=self.studio.review();change=next(c for c in review['changes'] if c['path']=='obsolete.html')
        self.assertTrue(change['deleted']);self.assertEqual(change['bytes'],0);self.assertIn('Removed obsolete.html',review['commit_message'])
        self.studio.publish(review['signature'])
        self.assertNotIn('obsolete.html',self.studio.git('ls-tree','-r','--name-only','HEAD').splitlines())
        self.assertFalse(self.studio.publication_status()['ready'])
    def test_publication_status_only_lights_for_publishable_work(self):
        self.assertFalse(self.studio.publication_status()['ready'])
        d=self.studio.page('1.html');d['raw']=d['raw'].replace('Original','Drafted');self.studio.save_draft(d)
        self.assertTrue(self.studio.publication_status()['ready'])
        self.studio.discard('1.html');self.assertFalse(self.studio.publication_status()['ready'])
        (self.root/'notes.private').write_text('not publishable');self.assertFalse(self.studio.publication_status()['ready'])
        (self.root/'1.html').write_text(new_page('Changed','<p>Changed outside.</p>'));self.assertTrue(self.studio.publication_status()['ready'])
    def test_published_edit_announces_each_protocol_event_but_site_feed_stays_calm(self):
        self.studio.migrate(); self.studio.state['published']={p.stem:json.loads(p.read_text()) for p in (self.root/'blyg/items').glob('*.json') if p.name!='index.json'}; self.studio.remember(self.studio.state['published'])
        d=self.studio.page('1.html'); d['raw']=d['raw'].replace('Original','Revision'); self.studio.save_draft(d); self.studio.prepare(); self.studio.prepare()
        iid=self.studio.state['ids']['1.html']; doc=json.loads((self.root/'blyg/items'/f'{iid}.json').read_text()); self.assertEqual(doc['version'],2)
        events=[e for e in ET.parse(self.root/'blyg/feed.xml').findall('./channel/item') if e.find('{'+NS+'}id').text==iid]
        self.assertEqual([e.find('{'+NS+'}version').text for e in events],['2','1'])
        self.assertTrue(all('Revision' in e.find('description').text for e in events))
        site_events=ET.parse(self.root/'feed.xml').findall('./channel/item')
        self.assertEqual(len(site_events),1);self.assertIn('Revision',site_events[0].find('description').text);self.assertNotIn('Original',site_events[0].find('description').text)
        self.assertEqual(site_events[0].find('pubDate').text,events[-1].find('pubDate').text)
    def test_site_pages_never_enter_rss(self):
        self.studio.migrate()
        rss=ET.parse(self.root/'blyg/feed.xml'); ids={e.find('{'+NS+'}id').text for e in rss.findall('./channel/item')}
        for name in ('index.html','portfolio.html','privacypolicy.html','openers.html'):
            if name in self.studio.state['ids']:self.assertNotIn(self.studio.state['ids'][name],ids)
    def test_tk_instructions_and_paths_rejected(self):
        d=self.studio.page('1.html'); d['raw']=d['raw'].replace('Original','[TK]private prompt[/TK]'); self.studio.save_draft(d)
        with self.assertRaises(ValueError): self.studio.prepare()
        with self.assertRaises(ValueError): self.studio.path('../secret.html')
    def test_publication_commits_only_reviewed_files(self):
        remote=self.base/'remote.git'; subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote)); (self.root/'private.txt').write_text('not for publication')
        self.studio.migrate(); review=self.studio.review()
        reviewed={change['path'] for change in review['changes']}
        self.assertIn('feed.xml',reviewed);self.assertIn('blyg/feed.xml',reviewed)
        self.studio.publish(review['signature'])
        files=self.studio.git('ls-tree','-r','--name-only','HEAD'); self.assertNotIn('private.txt',files); self.assertIn('blyg/feed.xml',files);self.assertIn('feed.xml',files)

    def test_archive_rebuild_is_labeled_as_rare_maintenance(self):
        html=(Path(__file__).parent/'static/index.html').read_text()
        self.assertIn('Rebuild Blyg archive',html)
        self.assertIn('Usually automatic. Use only after a Blynger upgrade or to repair the archive.',html)
    def test_workspace_tabs_post_sort_blockquote_and_image_usage(self):
        from PIL import Image
        html=(Path(__file__).parent/'static/index.html').read_text()
        for label in ('Posts','Openers','Pages','Images','Reader','Saved','Updated','Created','Alphabetical','Deleted'):
            self.assertIn('>'+label+'<',html)
        self.assertIn('Blockquote</button>',html)
        self.assertIn('id="imageUpload"',html)
        self.assertIn('id="imageUploadFile"',html)
        self.assertIn('class="tk-robot"',html)
        self.assertNotIn('✦ TK assistant',html)
        self.assertIn('id="help"',html)
        js=(Path(__file__).parent/'static/app.js').read_text()
        self.assertIn("['versions','mainFragment','quote','tk','fragment','removeFragment']",js)
        self.assertIn("modal('Blynger Help'",js)
        self.assertIn("'Last sync: '+readerSyncTime",js)
        self.assertNotIn("+' took '+",js)
        self.assertIn("workspace==='saved'?'saved'",js)
        self.assertIn('Saved before date tracking',js)
        self.assertIn("savedView==='activity'?'Loading private activity…':'Loading saved posts…'",js)
        self.assertIn("api('reader-react'",js)
        self.assertIn('Private activity</button>',html)
        self.assertIn('request!==readerLoadRevision||workspace!==currentWorkspace',js)
        self.assertIn("if(currentWorkspace==='reader')readerMessage('Checking subscriptions…')",js)
        self.assertIn("workspace==='saved'?(d.items.length+' saved '",js)
        self.assertIn("$('imageUpload').onclick",js)
        self.assertIn("Image uploaded. It will be included with your next publication.",js)
        Image.new('RGB',(7,5),'white').save(self.root/'images'/'used.png')
        (self.root/'1.html').write_text(new_page('Old post','<p>Original.</p><img src="/images/used.png" alt="">'))
        image=next(item for item in self.studio.images() if item['name']=='used.png')
        self.assertEqual(image['dimensions'],[7,5]);self.assertEqual(image['used_in'],['1.html'])
        post=next(item for item in self.studio.pages() if item['name']=='1.html')
        self.assertIn('created',post);self.assertIn('updated',post)
    def test_remote_ahead_keeps_hosted_files_and_accepts_reviewed_changes(self):
        remote=self.base/'remote.git'; subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote)); self.studio.git('push','website','master')
        other=self.base/'other'; subprocess.run(['git','clone',str(remote),str(other)],capture_output=True,check=True)
        for k,v in [('user.name','Test'),('user.email','test@example.invalid')]: subprocess.run(['git','config',k,v],cwd=other,check=True)
        (other/'robots.txt').write_text('User-agent: *\nAllow: /\n')
        subprocess.run(['git','add','.'],cwd=other,check=True); subprocess.run(['git','commit','-qm','Hosted update'],cwd=other,check=True); subprocess.run(['git','push'],cwd=other,capture_output=True,check=True)
        self.studio.migrate(); review=self.studio.refresh_review(); self.studio.publish(review['signature'])
        self.assertEqual((self.root/'robots.txt').read_text(),'User-agent: *\nAllow: /\n')
        self.assertEqual(self.studio.git('diff','--cached','--name-only'),'')
    def test_remote_ahead_existing_page_stops_stale_overwrite(self):
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote));self.studio.git('push','website','master')
        other=self.base/'other';subprocess.run(['git','clone',str(remote),str(other)],capture_output=True,check=True)
        for k,v in [('user.name','Test'),('user.email','test@example.invalid')]:subprocess.run(['git','config',k,v],cwd=other,check=True)
        (other/'1.html').write_text(new_page('Newer hosted post','<p>Do not overwrite me.</p>'));subprocess.run(['git','add','1.html'],cwd=other,check=True);subprocess.run(['git','commit','-qm','Newer hosted writing'],cwd=other,check=True);subprocess.run(['git','push'],cwd=other,capture_output=True,check=True)
        self.studio.create('Unrelated local post');self.studio.prepare(review=False)
        with self.assertRaisesRegex(ValueError,'newer versions'):self.studio.refresh_review()
        hosted=subprocess.run(['git','show','master:1.html'],cwd=other,capture_output=True,text=True,check=True).stdout
        self.assertIn('Do not overwrite me',hosted)
    def test_changed_review_cannot_publish(self):
        self.studio.migrate(); review=self.studio.review()
        (self.root/'1.html').write_text(new_page('New content','<p>Changed after review.</p>'))
        with self.assertRaisesRegex(ValueError,'Files changed'): self.studio.publish(review['signature'])
    def test_failed_push_retries_the_approved_commit(self):
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);self.studio.git('remote','add','website',str(remote));self.studio.migrate();review=self.studio.review()
        hook=remote/'hooks'/'pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o755)
        with self.assertRaises(ValueError):self.studio.publish(review['signature'])
        commit=self.studio.state['pending_publication']['commit'];self.assertEqual(self.studio.git('rev-parse','HEAD'),commit);hook.unlink()
        result=self.studio.publish(review['signature']);self.assertIn('push completed',result['message']);self.assertNotIn('pending_publication',self.studio.state);self.assertEqual(self.studio.git('rev-parse','HEAD'),commit)
    def test_media_immutable(self):
        from PIL import Image
        Image.new('RGB',(2,2),'red').save(self.root/'images/test.png')
        p=self.root/'1.html'; p.write_text(new_page('Image','<img src="/images/test.png" alt="red">')); self.studio.migrate()
        files=list((self.root/'blyg/media').glob('*')); self.assertEqual(len(files),1); old=files[0].read_bytes()
        Image.new('RGB',(2,2),'blue').save(self.root/'images/test.png'); self.studio.migrate(); self.assertEqual(files[0].read_bytes(),old); self.assertEqual(len(list((self.root/'blyg/media').glob('*'))),2)

if __name__=='__main__': unittest.main()

class VersionTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def baseline(self):
        self.studio.migrate()
        self.studio.state['published']={p.stem:json.loads(p.read_text()) for p in (self.root/'blyg/items').glob('*.json') if p.name!='index.json'}
        self.studio.remember(self.studio.state['published']); self.studio.save_state()
    def test_private_history_and_explicit_revision(self):
        self.baseline(); iid=self.studio.state['ids']['1.html']
        self.studio.revise('1.html','Clarify the claim')
        self.studio.prepare(); self.studio.prepare()
        doc=json.loads((self.root/'blyg/items'/f'{iid}.json').read_text())
        self.assertEqual(doc['version'],2); self.assertEqual(doc['changelog'][-1]['note'],'Clarify the claim')
        self.assertFalse((self.root/'blyg/items'/iid/'v1.json').exists())
        self.assertNotIn('/v1/',(self.root/'1.html').read_text())
        self.assertEqual(self.studio.versions('1.html')['current'],1)
    def test_pin_does_not_bump_and_remains_immutable(self):
        self.baseline(); iid=self.studio.state['ids']['1.html']; self.studio.pin('1.html',1)
        self.assertTrue(self.studio.publication_status()['ready'])
        self.studio.prepare(); path=self.root/'blyg/items'/iid/'v1.json'; before=path.read_bytes()
        pin=json.loads(before); self.assertNotIn('media',pin); self.assertTrue(pin['pinned'])
        current=json.loads((self.root/'blyg/items'/f'{iid}.json').read_text()); self.assertEqual(current['version'],1)
        self.assertTrue(current['changelog'][0]['pinned'])
        self.assertIn('/v1/',(self.root/'1.html').read_text())
        self.studio.revise('1.html','New wording'); d=self.studio.page('1.html'); d['raw']=d['raw'].replace('Original','Changed'); self.studio.save_draft(d); self.studio.prepare()
        self.assertEqual(before,path.read_bytes()); self.assertIn('Original',json.loads(before)['content_html'])
    def test_restore_is_private_draft(self):
        self.baseline(); before=(self.root/'1.html').read_bytes()
        self.studio.revise('1.html','Restore earlier wording',1)
        self.assertEqual(before,(self.root/'1.html').read_bytes()); self.assertTrue(self.studio.page('1.html')['draft'])
    def test_version_actions_refresh_publication_button(self):
        script=(Path(__file__).parent/'static/app.js').read_text()
        self.assertRegex(script,r"restore-version.*?api\('revise'.*?await updatePublicationState\(\)")
        self.assertRegex(script,r"pin-version.*?api\('pin'.*?await updatePublicationState\(\)")
    def test_transclusion_snapshot_and_republish(self):
        self.baseline(); iid=self.studio.state['ids']['1.html']
        d=self.studio.create('Quoted post'); d['raw']=d['raw'].replace('Start writing here.','![['+iid+']]'); self.studio.save_draft(d); self.studio.prepare()
        tid=self.studio.state['ids'][d['name']]; path=self.root/'blyg/items'/f'{tid}.json'; doc=json.loads(path.read_text())
        self.assertEqual(doc['kind'],'thread'); self.assertEqual(doc['transclusions'],[{'id':iid,'version':1}]); self.assertIn('![['+iid+']]',doc['content_md']); self.assertIn('blyg-transclusion',doc['content_html'])
        self.studio.state['published'][tid]=doc; self.studio.remember({tid:doc}); self.studio.state['drafts']={}
        src=self.studio.state['published'][iid]; src['version']=2; src['content_html']='<p>Source changed</p>';src['updated']='2026-10-01T00:00:00Z';src['changelog'].append({'version':2,'at':src['updated'],'note':'Changed source'})
        self.studio.prepare(); same=json.loads(path.read_text()); self.assertEqual(same['version'],1); self.assertIn('Original',same['content_html'])
        self.studio.revise(d['name'],'Refresh quoted source'); self.studio.prepare(); updated=json.loads(path.read_text()); self.assertEqual(updated['version'],2); self.assertEqual(updated['transclusions'][0]['version'],2)
    def test_reserved_and_unknown_quotes_rejected(self):
        self.baseline(); iid=self.studio.state['ids']['1.html']; d=self.studio.create('Bad quote'); d['raw']=d['raw'].replace('Start writing here.','![['+iid+'@v1]]'); self.studio.save_draft(d)
        with self.assertRaises(ValueError): self.studio.prepare()
    def test_publication_messages_default_and_custom_commit(self):
        changes=[{'path':'43.html','new':True},{'path':'openers.html','new':False},{'path':'blyg/feed.xml','new':False}]
        self.assertEqual(self.studio.publication_message(changes),'Created 43.html; Changed openers.html')
        remote=self.base/'remote.git'; subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote));self.studio.migrate()
        self.studio.publication_note('Fixed favicons throughout site')
        review=self.studio.review();self.assertEqual(review['commit_message'],'Fixed favicons throughout site')
        self.studio.publish(review['signature'])
        self.assertEqual(self.studio.git('log','-1','--format=%s'),'Fixed favicons throughout site')
        self.assertNotIn('publication_note',self.studio.state)
