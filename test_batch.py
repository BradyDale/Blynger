import json, re, tempfile, threading, time, unittest
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

from core import Studio
from reader import Reader, digest
import test_core
from test_reader import Net, ORIGIN, IID, doc


class ConditionalNet(Net):
    def __call__(self,url,headers=None,limit=None):
        self.calls.append(url)
        if url not in self.urls:raise ValueError('HTTP 404 from '+url)
        if headers and headers.get('If-None-Match')=='"same"':return url,b'',{'ETag':'"same"'},304
        value,mime=self.urls[url];body=json.dumps(value).encode() if isinstance(value,dict) else value.encode() if isinstance(value,str) else value
        return url,body,{'Content-Type':mime,'ETag':'"same"'},200

class ConcurrentNet(Net):
    def __init__(self):super().__init__();self.guard=threading.Lock();self.active=0;self.high_water=0
    def __call__(self,url,headers=None,limit=None):
        if url.endswith('feed.xml'):
            with self.guard:self.active+=1;self.high_water=max(self.high_water,self.active)
            try:time.sleep(.04);return super().__call__(url,headers,limit)
            finally:
                with self.guard:self.active-=1
        return super().__call__(url,headers,limit)


class ReaderBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_unchanged_blyg_feed_stops_after_304(self):
        net=ConditionalNet();net.add();reader=Reader(self.data,net,lambda:'2026-01-02T00:00:00Z');sid=reader.subscribe(ORIGIN)['subscriptions'][0]['id']
        net.calls=[];result=reader.sync(sid)
        self.assertEqual(net.calls,[ORIGIN+'feed.xml']);self.assertIn('0 changed items',result['message']);self.assertEqual(reader.state['subscriptions'][sid]['last_result'],'unchanged')
    def test_unchanged_blyg_feed_without_validators_skips_recent_items(self):
        net=Net();net.add();reader=Reader(self.data,net,lambda:'2026-01-02T00:00:00Z');sid=reader.subscribe(ORIGIN)['subscriptions'][0]['id'];net.calls=[]
        result=reader.sync(sid)
        self.assertEqual(net.calls,[ORIGIN+'feed.xml']);self.assertIn('0 changed items',result['message']);self.assertEqual(reader.state['subscriptions'][sid]['last_result'],'unchanged')
    def test_unchanged_plain_feed_stops_after_identical_200(self):
        net=Net();url='https://feed.example/rss.xml';net.urls[url]=('<rss><channel><title>Feed</title><item><guid>one</guid><title>One</title><description>Text</description></item></channel></rss>','application/rss+xml');reader=Reader(self.data,net);sid=reader.subscribe(url)['subscriptions'][0]['id'];net.calls=[]
        result=reader.sync(sid)
        self.assertEqual(net.calls,[url]);self.assertIn('0 changed items',result['message']);self.assertEqual(reader.state['subscriptions'][sid]['last_result'],'unchanged')
        self.assertIn('hash',reader.state['subscriptions'][sid]['feed_cache']);self.assertNotIn('body',reader.state['subscriptions'][sid]['feed_cache'])
    def test_plain_feed_wrapper_change_does_not_reimport_unchanged_entries(self):
        net=Net();url='https://feed.example/rss.xml';item='<item><guid>one</guid><title>One</title><description>Text</description></item>'
        net.urls[url]=('<rss><channel><title>Feed</title><lastBuildDate>one</lastBuildDate>'+item+'</channel></rss>','application/rss+xml')
        clock=['2026-01-02T00:00:00Z'];reader=Reader(self.data,net,lambda:clock[0]);sid=reader.subscribe(url)['subscriptions'][0]['id'];key=reader.key(url,'one');before=json.loads(json.dumps(reader.state['items'][key]))
        net.urls[url]=('<rss><channel><title>Feed</title><lastBuildDate>two</lastBuildDate>'+item+'</channel></rss>','application/rss+xml');clock[0]='2026-01-03T00:00:00Z';result=reader.sync(sid)
        self.assertIn('0 changed items',result['message']);self.assertEqual(reader.state['items'][key],before);self.assertEqual(reader.state['subscriptions'][sid]['last_downloaded'],0)
    def test_plain_feed_xml_reformat_with_same_meaning_is_not_changed(self):
        net=Net();url='https://feed.example/rss.xml';net.urls[url]=('<rss><channel><title>Feed</title><item><guid>one</guid><title>One</title><description>Text</description></item></channel></rss>','application/rss+xml');reader=Reader(self.data,net);sid=reader.subscribe(url)['subscriptions'][0]['id'];key=reader.key(url,'one');before=reader.state['items'][key]['observed_at']
        net.urls[url]=('<rss><channel><title>Feed</title><item>\n<guid>one</guid><title>One</title><description>Text</description>\n</item></channel></rss>','application/rss+xml');result=reader.sync(sid)
        self.assertIn('0 changed items',result['message']);self.assertEqual(reader.state['items'][key]['observed_at'],before)
    def test_distinct_subscriptions_check_concurrently(self):
        net=ConcurrentNet();other='https://other.example/';net.add();net.add(other,[doc(iid='0'*25+'2',origin=other)]);reader=Reader(self.data,net);reader.subscribe(ORIGIN);reader.subscribe(other);net.high_water=0
        reader.sync()
        self.assertGreaterEqual(net.high_water,2)
    def test_overlap_is_refused_without_network(self):
        net=Net();net.add();reader=Reader(self.data,net);reader._sync_lock.acquire();net.calls=[]
        try:self.assertTrue(reader.sync()['already_running']);self.assertEqual(net.calls,[])
        finally:reader._sync_lock.release()
    def test_failed_subscription_does_not_abort_another(self):
        net=Net();net.add();other='https://other.example/';net.add(other,[doc(iid='0'*25+'2',origin=other)]);reader=Reader(self.data,net);reader.subscribe(ORIGIN);reader.subscribe(other);del net.urls[ORIGIN+'feed.xml'];del net.urls[ORIGIN+'items/index.json'];reader.sync()
        self.assertTrue(reader.state['subscriptions'][digest(ORIGIN)]['error']);self.assertFalse(reader.state['subscriptions'][digest(other)]['error']);self.assertIn(reader.key(other,'0'*25+'2'),reader.state['items'])
    def test_three_year_retention_saved_and_liked_are_private(self):
        net=Net();net.add();reader=Reader(self.data,net,lambda:'2026-01-02T00:00:00Z');reader.subscribe(ORIGIN);key=reader.key(ORIGIN,IID)
        reader.mark(key,'saved',True);reader.mark(key,'liked',True);reader.clock=lambda:'2030-01-03T00:00:00Z';reader.cleanup()
        self.assertIn(key,reader.state['items']);self.assertEqual(reader.listing(view='saved')[0]['key'],key);self.assertEqual(reader.listing(view='saved')[0]['saved_at'],'2026-01-02T00:00:00Z');self.assertEqual(reader.listing(view='liked')[0]['key'],key)
        reader.mark(key,'saved',False);reader.cleanup();self.assertNotIn(key,reader.state['items'])
    def test_saved_timestamp_survives_source_refresh(self):
        net=Net();net.add();clock=['2026-01-02T10:30:00Z'];reader=Reader(self.data,net,lambda:clock[0]);sid=reader.subscribe(ORIGIN)['subscriptions'][0]['id'];key=reader.key(ORIGIN,IID);reader.mark(key,'saved',True);clock[0]='2026-01-03T10:30:00Z';net.add(items=[doc(version=2,text='Changed')]);reader.sync(sid)
        self.assertTrue(reader.item(key)['saved']);self.assertEqual(reader.listing(view='saved')[0]['saved_at'],'2026-01-02T10:30:00Z')
    def test_plain_web_open_has_no_blyg_identity(self):
        net=Net();url='https://plain.example/story';net.urls[url]=('<html><head><title>Plain story</title></head><body><main><p>Readable words.</p><script>bad()</script></main></body></html>','text/html')
        reader=Reader(self.data,net);result=reader.open_url(url);item=reader.item(result['selected'])
        self.assertEqual(item['source_type'],'web');self.assertEqual(item['doc']['url'],url);self.assertFalse({'id','version','kind'} & item['doc'].keys());self.assertNotIn('script',reader.rendered(item['key']))
    def test_pinned_fork_source_and_unpinned_refusal(self):
        net=Net();source=doc(kind='thread');source['changelog'][0]['pinned']=True;source['content_html']='<script>steal()</script><p onclick="steal()"><a href="javascript:steal()">Remote words</a></p>';net.add(items=[source]);reader=Reader(self.data,net);reader.subscribe(ORIGIN);fork=reader.fork_source(reader.key(ORIGIN,IID),1)
        self.assertEqual(fork['forked_from'],{'id':IID,'version':1,'origin':ORIGIN});self.assertIn('Remote words',fork['html'])
        self.assertNotIn('script',fork['html']);self.assertNotIn('onclick',fork['html']);self.assertNotIn('javascript:',fork['html'])
        reader.state['items'][reader.key(ORIGIN,IID)]['doc']['changelog'][0].pop('pinned')
        with self.assertRaisesRegex(ValueError,'not pinned'):reader.fork_source(reader.key(ORIGIN,IID),1)
    def test_fork_flattens_inherited_transclusion_and_generation_disclosure(self):
        net=Net();source=doc(kind='thread');source['changelog'][0]['pinned']=True
        source['content_html']='<p>Own prose.</p><blockquote class="blyg-transclusion blyg-partial" data-blyg-origin="https://quoted.example/blyg/" data-blyg-id="'+'0'*25+'2'+'" data-blyg-version="3"><p>Quoted words.</p></blockquote><div class="blyg-tk-gen">Generated words.</div>'
        source['generated']=[{'sources':[{'origin':'https://quoted.example/blyg/','id':'0'*25+'2','version':3}],'model':'example-model','at':'2026-01-01T00:00:00Z'}]
        net.add(items=[source]);reader=Reader(self.data,net);reader.subscribe(ORIGIN);fork=reader.fork_source(reader.key(ORIGIN,IID),1)
        self.assertNotIn('blyg-transclusion',fork['html']);self.assertNotIn('blyg-partial',fork['html']);self.assertNotIn('data-blyg-',fork['html']);self.assertIn('Quoted from quoted.example',fork['html'])
        self.assertEqual(fork['generated'],[{'sources':[],'model':'example-model','at':'2026-01-01T00:00:00Z'}])

    def test_fork_makes_remote_addresses_absolute_without_changing_absolute_ones(self):
        net=Net();source=doc(kind='thread');source['changelog'][0]['pinned']=True
        source['content_html']='<p><img src="media/a.png"><img src="/media/b.png"><img src="https://images.example/c.png"><a href="story">Story</a><a href="#part">Part</a></p>';source['media']=[{'url':'media/a.png','mime':'image/png'},{'url':'media/declared.png','mime':'image/png','alt':'Declared'}]
        net.add(items=[source]);reader=Reader(self.data,net);reader.subscribe(ORIGIN);fork=reader.fork_source(reader.key(ORIGIN,IID),1);soup=BeautifulSoup(fork['html'],'html.parser')
        self.assertEqual([n['src'] for n in soup.find_all('img')],[ORIGIN+'media/a.png','https://remote.example/media/b.png','https://images.example/c.png',ORIGIN+'media/declared.png'])
        self.assertEqual(soup.find('img',src=ORIGIN+'media/declared.png')['alt'],'Declared')
        self.assertEqual([n['href'] for n in soup.find_all('a')],[ORIGIN+'story','#part'])

    def test_fork_uses_exact_historical_pinned_markup_and_addresses(self):
        net=Net();current=doc(version=2,kind='thread',text='New words');current['changelog']=[{'version':1,'at':'2025-01-01T00:00:00Z','url':'items/'+IID+'/v1.json','pinned':True},{'version':2,'at':'2026-01-01T00:00:00Z','url':'items/'+IID+'/v2.json','pinned':True}];current['content_html']='<p><img src="new.png">New words</p>'
        old=doc(version=1,kind='thread',text='Old words');old['pinned']=True;old['content_html']='<p><img src="old.png">Old words</p>';old['media']=[{'url':'old-extra.png','mime':'image/png'}];current['media']=[{'url':'new-extra.png','mime':'image/png'}]
        net.add(items=[current]);net.urls[ORIGIN+'items/'+IID+'/v1.json']=(old,'application/json');reader=Reader(self.data,net);reader.subscribe(ORIGIN);fork=reader.fork_source(reader.key(ORIGIN,IID),1)
        self.assertIn(ORIGIN+'old.png',fork['html']);self.assertIn(ORIGIN+'old-extra.png',fork['html']);self.assertIn('Old words',fork['html']);self.assertNotIn('new.png',fork['html']);self.assertNotIn('new-extra.png',fork['html']);self.assertEqual(fork['forked_from']['version'],1)

    def test_reader_uses_item_page_and_stable_publication_order(self):
        net=Net();older=doc();older['page']='t/'+older['id']+'/';older['updated']='2026-12-01T00:00:00Z'
        newer=doc(iid='0'*25+'2',text='Newer');newer['created']='2026-02-01T00:00:00Z';newer['updated']=newer['created'];newer['changelog'][0]['at']=newer['created'];newer['page']='t/'+newer['id']+'/'
        net.add(items=[older,newer]);reader=Reader(self.data,net,lambda:'2026-12-02T00:00:00Z');reader.subscribe(ORIGIN);items=reader.listing()
        self.assertEqual([i['id'] for i in items],[newer['id'],older['id']]);self.assertEqual(items[1]['url'],ORIGIN+'t/'+older['id']+'/')

    def test_remove_subscription_keeps_only_saved_or_liked_items(self):
        net=Net();second=doc(iid='0'*25+'2',text='Second');net.add(items=[doc(),second]);reader=Reader(self.data,net);sid=reader.subscribe(ORIGIN)['subscriptions'][0]['id'];reader.mark(reader.key(ORIGIN,IID),'saved',True)
        result=reader.unsubscribe(sid)
        self.assertIn('Saved and Liked',result['message']);self.assertFalse(reader.state['subscriptions'][sid]['active']);self.assertEqual(reader.listing(),[]);self.assertEqual([i['id'] for i in reader.listing(view='saved')],[IID]);self.assertNotIn(reader.key(ORIGIN,second['id']),reader.state['items'])


class StudioBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.StudioTests();self.fixture.setUp();self.s=self.fixture.studio
    def tearDown(self):self.fixture.tearDown()
    def test_fork_lineage_is_immutable_and_not_a_transclusion(self):
        lineage={'id':IID,'version':1,'origin':ORIGIN};page=self.s.create('Fork',body='<p>Copied and edited.</p>',forked_from=lineage);self.s.prepare();iid=self.s.state['ids'][page['name']];out=json.loads((self.s.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(out['forked_from'],lineage);self.assertFalse(out.get('transclusions'))
        saved=self.s.page(page['name']);saved['forked_from']={**lineage,'version':2}
        with self.assertRaisesRegex(ValueError,'cannot be changed'):self.s.save_draft(saved)
    def test_fork_preserves_remote_images_through_publication(self):
        lineage={'id':IID,'version':1,'origin':ORIGIN};body='<p><img src="https://remote.example/media/a.png"><a href="https://remote.example/story">Story</a></p>';page=self.s.create('Fork media',body=body,forked_from=lineage);self.s.prepare();iid=self.s.state['ids'][page['name']];out=json.loads((self.s.root/f'blyg/items/{iid}.json').read_text());published=(self.s.root/page['name']).read_text()
        self.assertIn('https://remote.example/media/a.png',out['content_html']);self.assertIn('https://remote.example/media/a.png',published);self.assertIn('https://remote.example/story',published)
    def test_retried_save_is_idempotent_for_editor_metadata(self):
        page=self.s.create('Retry save',body='<p>First.</p><p>Second.</p>');draft=self.s.page(page['name']);nodes=[str(n) for n in BeautifulSoup(draft['body'],'html.parser').contents if str(n).strip()];blocks=[{'id':'b'+str(i),'html':node} for i,node in enumerate(nodes)];draft['fragments']={'version':1,'blocks':blocks,'dividers':[],'ranges':[]};draft['generated']=[{'sources':[{'url':'https://source.example/'}]}];draft['quotes']={'q1':{'html':'<p>Quoted.</p>','origin':'https://source.example/'}}
        self.s.save_draft(draft);first=json.loads(json.dumps(self.s.state['drafts'][page['name']]));self.s.save_draft(draft)
        self.assertEqual(self.s.state['drafts'][page['name']],first)
    def test_blogroll_opml_and_frozen_new_post_snapshot(self):
        sid='sub';self.s.reader.state['subscriptions'][sid]={'id':sid,'origin':'https://friend.example/blyg/','title':'Friend','type':'blyg','manifest':{'site':'https://friend.example/'},'blogroll':True,'added_at':'2026-01-01T00:00:00Z'};self.s.reader.save()
        page=self.s.create('With friends');self.s.prepare();manifest=json.loads((self.s.root/'blyg/blyg.json').read_text());self.assertEqual(manifest['blogroll'],'blogroll.opml')
        self.assertIn('<link rel="blogroll" href="blogroll.opml"',(self.s.root/'blyg/index.html').read_text())
        outline=ET.parse(self.s.root/'blyg/blogroll.opml').find('./body/outline');self.assertEqual(outline.attrib['xmlUrl'],'https://friend.example/blyg/feed.xml');self.assertEqual(outline.attrib['htmlUrl'],'https://friend.example/')
        first=(self.s.root/page['name']).read_text();self.assertIn('Friend',first);self.s.reader.state['subscriptions'][sid]['title']='Changed later';self.s.reader.save();self.s.revise(page['name'],'Small edit');draft=self.s.page(page['name']);draft['raw']=draft['raw'].replace('Start writing here.','Changed prose.');self.s.save_draft(draft);self.s.prepare();later=(self.s.root/page['name']).read_text();self.assertIn('Friend',later);self.assertNotIn('Changed later',later)
    def test_blogroll_links_ordinary_feed_to_site_root(self):
        sid='xkcd';self.s.reader.state['subscriptions'][sid]={'id':sid,'origin':'https://xkcd.com/atom.xml','title':'xkcd','type':'l0','blogroll':True,'active':True,'added_at':'2026-01-01T00:00:00Z'}
        entries=self.s.blogroll_entries();self.assertEqual(entries,[{'title':'xkcd','htmlUrl':'https://xkcd.com/','xmlUrl':'https://xkcd.com/atom.xml'}]);rendered=self.s.place_blogroll('<html><head></head><body><article>Post</article></body></html>',entries);self.assertIn('href="https://xkcd.com/"',rendered);self.assertNotIn('href="https://xkcd.com/atom.xml"',rendered)
        frozen=[{'title':'xkcd','htmlUrl':'https://xkcd.com/atom.xml','xmlUrl':'https://xkcd.com/atom.xml'}];old=rendered.replace('href="https://xkcd.com/"','href="https://xkcd.com/atom.xml"');revised=self.s.place_blogroll(old,frozen);self.assertIn('href="https://xkcd.com/"',revised);self.assertNotIn('href="https://xkcd.com/atom.xml"',revised)
    def test_human_date_rss_footer_and_empty_quote_space_cleanup(self):
        page=self.s.create('October post',body='<p><br></p><blockquote class="blynger-citation" cite="https://source.example/"><p>Words</p><cite class="blynger-blockquote-source"><a href="https://source.example/">—source.example</a></cite></blockquote><div class="blyg-tk-gen"><p>Structure</p></div><p><br></p>');self.s.prepare();raw=(self.s.root/page['name']).read_text();iid=self.s.state['ids'][page['name']];doc=json.loads((self.s.root/f'blyg/items/{iid}.json').read_text());today=datetime.now().astimezone()
        self.assertIn(today.strftime('%B ')+str(today.day)+today.strftime(', %Y'),raw);self.assertIn('>RSS</a>',raw);self.assertIn('<blockquote cite="https://source.example/" class="blynger-citation">',doc['content_html']);self.assertIn('<cite class="blynger-blockquote-source">',doc['content_html']);self.assertIn('—source.example',raw);self.assertIn('class="blyg-tk-gen"',doc['content_html']);self.assertNotIn('<p><br/></p>',doc['content_html'])
    def test_local_markers_never_enter_protocol_output(self):
        net=Net();net.add();self.s.reader=Reader(self.s.data,net,lambda:'2026-01-02T00:00:00Z');self.s.reader.subscribe(ORIGIN);key=self.s.reader.key(ORIGIN,IID);self.s.reader.mark(key,'saved',True);self.s.reader.mark(key,'liked',True);self.s.reader.react(key,'🤯');self.s.create('Ordinary');self.s.prepare();public=(self.s.root/'blyg/items/index.json').read_text();self.assertNotIn('"saved"',public);self.assertNotIn('"liked"',public);self.assertNotIn('"reaction"',public);self.assertNotIn('"interactions"',public)
    def test_ui_contains_localized_controls_and_states(self):
        static=Path(__file__).parent/'static';app=(static/'app.js').read_text()+(static/'reader-ui.js').read_text();html=(static/'index.html').read_text();fragments=(static/'fragments.js').read_text()
        compact=re.sub(r'\s+','',app);compact_fragments=re.sub(r'\s+','',fragments)
        def assert_compact(*values):
            for value in values:self.assertIn(re.sub(r'\s+','',value),compact)
        assert_compact('reader-open','Open original','90*60*1000','Posting',"b.textContent='Close'",'sourceFind','visualFind','defaultParagraphSeparator','image-url','reader-unsubscribe','d.original_url','readerFragmentChoices','fragmentEditor.replace','blynger-blockquote-source','pasteQuoteText','aria-pressed','chooseStub','Stub to Opener','Stub to post','stub_label_html','lockTransclusions','pin_on_publish','clearBrokenFragments','Remove all fragments and save draft')
        for identifier in ('readerViewFilter','readerBlogroll','readerManage','removeFragment','blockquote','sourceFindText','queue','pinOnPublish','responseMarker'):self.assertIn('id="'+identifier+'"',html)
        assert_compact("modal('Manage subscriptions'","api('reader-blogroll'",'Saved and Liked posts are kept','saved for the next publication')
        assert_compact("modal('Add link'",'year-2018.html',"$('dialog').close();$('editor').focus();restoreSelection();if(!document.execCommand('createLink'",'reader-source-badge','reader-generated','What the author disclosed','fingerprint:d.fingerprint,transclude:true')
        self.assertNotIn("$('source').readOnly=!!fragmentEditor.meta",app);self.assertIn('addDivider()',fragments);self.assertIn('removeDivider()',fragments);self.assertIn('replace(html)',fragments)
        self.assertIn('this.lockTransclusions();letrepaired=false;if(this.meta)',compact_fragments)
        self.assertIn('editor-safety.js',html);assert_compact('saveQueue.enqueue(()=>saveOnce(clearFragments))','clear_fragments:clearFragments','pageRequests.accepts(ticket,editRevision)','if(requireClean&&dirty)',"const p=await api('new'",'await openPage(p.name)')
        self.assertLess(compact.index('pageRequests.accepts(ticket,editRevision)'),compact.index('currentWorkspace=workspaceForPage(page)'))


if __name__=='__main__':unittest.main()
