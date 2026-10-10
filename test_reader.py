import copy, json, tempfile, unittest
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, timezone, timedelta
from reader import Reader, digest, normalized
from core import Studio

ORIGIN='https://remote.example/notes/'
IID='0' * 25+'1'
def doc(iid=IID,version=1,kind='fragment',text='Remote words',origin=ORIGIN):
    at='2026-01-01T00:00:00Z'
    return {'blyg':'0.3','id':iid,'kind':kind,'origin':origin,'author':{'name':'Other Author'},'title':'Remote title','created':at,'updated':at,'version':version,'content_md':text,'content_html':'<p>'+text+'</p>','content_hash':'sha256:'+digest(text),'changelog':[{'version':version,'at':at}],'media':[],'extra_future_key':True}
class Net:
    def __init__(self):self.urls={};self.calls=[]
    def add(self,origin=ORIGIN,items=None):
        items=items if items is not None else [doc(origin=origin)]
        self.urls[origin+'blyg.json']=({'blyg':'0.3','site':origin,'title':'Remote Blyg','author':{'name':'Other Author'}},'application/json')
        self.urls[origin+'items/index.json']=({'items':[{'id':d['id'],'version':d['version'],'kind':d['kind']} for d in items]},'application/json')
        self.urls[origin+'feed.xml']=('<rss xmlns:blyg="https://blygger.org/ns/0.1"><channel><blyg:manifest>'+origin+'blyg.json</blyg:manifest>'+''.join('<item><blyg:id>'+d['id']+'</blyg:id><blyg:version>'+str(d['version'])+'</blyg:version></item>' for d in items)+'</channel></rss>','application/rss+xml')
        for d in items:self.urls[origin+'items/'+d['id']+'.json']=(d,'application/json')
    def __call__(self,url,headers=None,limit=None):
        self.calls.append(url)
        if url not in self.urls:raise ValueError('HTTP 404 from '+url)
        value,mime=self.urls[url];body=json.dumps(value).encode() if isinstance(value,dict) else value.encode() if isinstance(value,str) else value
        return url,body,{'Content-Type':mime},200
class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.net=Net();self.net.add();self.time='2026-01-02T00:00:00Z';self.r=Reader(self.data,self.net,lambda:self.time)
    def tearDown(self):self.tmp.cleanup()
    def sub(self):self.r.subscribe(ORIGIN);return digest(ORIGIN)
    def item(self):return self.r.state['items'][self.r.key(ORIGIN,IID)]
    def media(self,kind='image'):
        d=doc();ext='png' if kind=='image' else 'mp4';mime='image/png' if kind=='image' else 'video/mp4';u=ORIGIN+'media/test.'+ext
        d['media']=[{'url':u,'mime':mime}];d['content_html']='<img src="'+u+'">' if kind=='image' else '<video src="'+u+'"></video>'
        self.net.add(items=[d]);self.net.urls[u]=(b'fixture-media',mime);self.sub();return self.item()
    def test_zero_subscriptions(self):self.assertEqual(self.r.listing(),[]);self.assertEqual(self.r.sync()['subscriptions'],[])
    def test_valid_subscription_imports_ground_truth(self):
        self.sub();i=self.item();self.assertEqual(i['origin'],ORIGIN);self.assertEqual(i['doc']['id'],IID);self.assertEqual(i['doc']['kind'],'fragment');self.assertEqual(i['doc']['author']['name'],'Other Author');self.assertEqual(self.r.listing()[0]['title'],'Remote words');self.assertIn(ORIGIN+'feed.xml',self.net.calls)
    def test_invalid_url_and_invalid_blyg(self):
        for url in ('file:///tmp/a','https://user:pass@x/a','not a url'):
            with self.assertRaises(ValueError):self.r.subscribe(url)
        with self.assertRaises(ValueError):self.r.subscribe('https://invalid.example/')
        self.assertEqual(self.r.state['subscriptions'],{})
    def test_refresh_keeps_identity_and_first_download_and_updates_version(self):
        sid=self.sub();first=self.item()['first_downloaded_at'];self.time='2026-02-02T00:00:00Z';self.r.sync(sid);self.assertEqual(len(self.r.state['items']),1)
        self.net.add(items=[doc(version=2,text='Changed')]);self.r.sync(sid);self.assertEqual(self.item()['doc']['version'],2);self.assertEqual(self.item()['first_downloaded_at'],first)
        reloaded=Reader(self.data,self.net,lambda:self.time);self.assertEqual(reloaded.item(self.r.key(ORIGIN,IID))['doc']['version'],2)
    def test_multiple_origins_scope_same_id_and_kind(self):
        self.sub();other='https://second.example/';self.net.add(other,[doc(kind='thread',origin=other)]);self.r.subscribe(other);self.assertEqual(len(self.r.listing()),2);self.assertEqual({i['kind'] for i in self.r.listing()},{'fragment','thread'});self.assertEqual(len(self.r.listing(subscription=digest(other))),1);self.assertEqual(len(self.r.listing(query='other author')),2)
    def test_stub_target_uses_cited_excerpt_and_cached_target(self):
        target=doc(kind='thread',text='The complete target words that identify this post')
        stub=doc(iid='0'*25+'2',kind='thread',text='My response')
        stub['stub_of']={'origin':ORIGIN,'id':IID,'version':1,'cited':{'excerpt':'The frozen first words','source':'Other Author'}}
        self.net.add(items=[target,stub]);self.sub()
        row=next(item for item in self.r.listing() if item['id']==stub['id'])
        self.assertEqual(row['stub_target']['label'],'The frozen first words')
        self.assertEqual(row['stub_target']['key'],self.r.key(ORIGIN,IID))
        self.assertEqual(row['stub_target']['url'],ORIGIN+'t/'+IID+'/')
        self.assertEqual(row['stub_target']['version'],1)
        links=self.r.conversation_links(self.r.item(self.r.key(ORIGIN,IID)))
        self.assertIsNone(links['backward'])
        self.assertEqual([link['key'] for link in links['forward']],[self.r.key(ORIGIN,stub['id'])])
        reverse=self.r.conversation_links(self.r.item(self.r.key(ORIGIN,stub['id'])))
        self.assertEqual(reverse['backward']['key'],self.r.key(ORIGIN,IID))
        self.assertEqual(reverse['forward'],[])
    def test_listing_does_not_repeat_derived_headline_in_excerpt(self):
        words='A long opening thought that becomes the Reader headline and then continues into useful preview text.'
        self.net.add(items=[doc(text=words)]);self.sub();row=self.r.listing()[0]
        self.assertFalse(row['excerpt'].startswith(row['title']))
        self.assertNotEqual(row['excerpt'],words)
    def test_stub_target_plain_web_and_uncached_blyg_fallbacks(self):
        item={'doc':{'stub_of':{'url':'https://news.example/story','cited':{'excerpt':'A web headline'}}}}
        self.assertEqual(self.r.stub_target(item),{'version':None,'url':'https://news.example/story','label':'A web headline'})
        item={'doc':{'stub_of':{'origin':'https://missing.example/blyg/','id':'0'*25+'3','version':4,'cited':{'source':'Missing Blyg'}}}}
        self.assertEqual(self.r.stub_target(item),{'version':4,'url':'https://missing.example/blyg/','label':'Missing Blyg'})
    def test_read_uses_cache_and_sanitizes_without_network(self):
        d=doc();d['content_html']='<script>evil()</script><p onclick="evil()">Good</p><img src="https://tracker.example/x"><iframe src="https://evil.example"></iframe>';self.net.add(items=[d]);self.sub();self.net.calls=[];self.net.urls={}
        html=self.r.rendered(self.r.key(ORIGIN,IID));self.assertNotIn('<script',html);self.assertNotIn('onclick',html);self.assertNotIn('tracker',html);self.assertNotIn('iframe',html);self.assertIn('Good',html);self.assertEqual(self.net.calls,[])
    def test_rss_url_discovers_manifest(self):self.r.subscribe(ORIGIN+'feed.xml');self.assertEqual(len(self.r.listing()),1)
    def test_item_url_discovers_origin_and_selects_item(self):
        result=self.r.subscribe(ORIGIN+'items/'+IID+'.json');self.assertEqual(result['selected'],self.r.key(ORIGIN,IID))
    def test_html_rel_blyg_discovery(self):
        url='https://home.example/article';self.net.urls[url]=('<link rel="blyg" href="'+ORIGIN+'">','text/html');self.r.subscribe(url);self.assertEqual(len(self.r.listing()),1)
    def test_html_rss_discovery_within_six_probes(self):
        url='https://home.example/article';self.net.urls[url]=('<link rel="alternate" type="application/rss+xml" href="'+ORIGIN+'feed.xml">','text/html')
        origin,manifest,target=self.r.resolve(url);self.assertEqual(origin,ORIGIN);self.assertLessEqual(len(self.net.calls),6)
    def test_wordpress_comment_metadata_is_not_followed(self):
        feed='https://wordpress.example/feed/';comments='https://wordpress.example/post/comments/feed/'
        xml='''<rss xmlns:wfw="http://wellformedweb.org/CommentAPI/" xmlns:slash="http://purl.org/rss/1.0/modules/slash/"><channel><title>WordPress</title><item><title>One post</title><link>https://wordpress.example/post/</link><comments>https://wordpress.example/post/#comments</comments><wfw:commentRss>'''+comments+'''</wfw:commentRss><slash:comments>12</slash:comments><description>Article body.</description></item></channel></rss>'''
        self.net.urls[feed]=(xml,'application/rss+xml');self.r.subscribe(feed)
        self.assertEqual([item['doc']['title'] for item in self.r.state['items'].values()],['One post'])
        self.assertNotIn(comments,[sub['origin'] for sub in self.r.state['subscriptions'].values()]);self.assertNotIn(comments,self.net.calls)
    def test_html_discovery_skips_comments_feed_link(self):
        page='https://wordpress.example/post/';main='https://wordpress.example/feed/';comments=page+'feed/'
        self.net.urls[page]=('<link rel="alternate" type="application/rss+xml" title="Comments Feed" href="'+comments+'"><link rel="alternate" type="application/rss+xml" title="Posts Feed" href="'+main+'">','text/html')
        self.net.urls[main]=('<rss><channel><title>Posts</title></channel></rss>','application/rss+xml')
        origin,manifest,_=self.r.resolve(page);self.assertEqual(origin,main);self.assertEqual(manifest,{'type':'l0'});self.assertNotIn(comments,self.net.calls)
    def test_explicit_comments_feed_is_allowed_but_reader_link_is_not_subscription(self):
        comments='https://wordpress.example/post/feed/';xml='<rss><channel><title>Comments on: Post</title><item><title>By: Reader</title><link>https://wordpress.example/post/#comment-1</link><description>A comment.</description></item></channel></rss>';self.net.urls[comments]=(xml,'application/rss+xml')
        self.r.subscribe(comments);self.assertEqual(len(self.r.state['subscriptions']),1)
        other=Reader(self.data/'other',self.net,lambda:self.time)
        with self.assertRaisesRegex(ValueError,'do not become subscriptions'):other.open_url(comments,False)
        self.assertEqual(other.state['subscriptions'],{})
    def test_legacy_comment_cleanup_preserves_saved_and_liked(self):
        comments='https://wordpress.example/post/feed/';sid=digest(comments);self.r.state['subscriptions'][sid]={'id':sid,'origin':comments,'title':'Comments on: Post','type':'l0','active':True,'blogroll':True}
        for n,marks in enumerate(({}, {'saved':True}, {'liked':True})):
            key='comment'+str(n);self.r.state['items'][key]={'key':key,'subscription':sid,'origin':comments,'source_type':'l0','doc':{'title':'By: Reader','url':'https://wordpress.example/post/#comment-'+str(n),'content_html':'<p>Comment</p>'},'first_downloaded_at':self.time,**marks}
        self.r.state.pop('comment_feed_cleanup_v1',None);self.r.save();reloaded=Reader(self.data,self.net,lambda:self.time)
        self.assertFalse(reloaded.state['subscriptions'][sid]['active']);self.assertNotIn('comment0',reloaded.state['items']);self.assertIn('comment1',reloaded.state['items']);self.assertIn('comment2',reloaded.state['items'])
    def test_human_item_url_selects_item_via_rel(self):
        url=ORIGIN+'f/'+IID+'/';self.net.urls[url]=('<link rel="blyg" href="'+ORIGIN+'">','text/html')
        self.assertEqual(self.r.subscribe(url)['selected'],self.r.key(ORIGIN,IID))
    def test_major_protocol_version_rejected(self):
        self.net.urls[ORIGIN+'blyg.json'][0]['blyg']='1.0'
        with self.assertRaises(ValueError):self.r.subscribe(ORIGIN+'blyg.json')
    def test_malformed_feed_uses_index(self):
        self.net.urls[ORIGIN+'feed.xml']=('not XML','text/plain');self.sub();self.assertEqual(len(self.r.listing()),1)
    def test_missing_index_uses_feed_with_warning(self):
        del self.net.urls[ORIGIN+'items/index.json'];self.sub();self.assertEqual(len(self.r.listing()),1);self.assertIn('lossy',self.r.state['subscriptions'][digest(ORIGIN)]['warnings'][0])
    def test_same_version_older_timestamp_does_not_regress(self):
        sid=self.sub();d=doc();d['updated']='2025-01-01T00:00:00Z';self.net.add(items=[d]);self.r.sync(sid);self.assertEqual(self.item()['doc']['updated'],'2026-01-01T00:00:00Z')
    def test_declared_media_without_html_is_cached_and_rendered(self):
        d=doc();d['media']=[{'url':'media/a.png','mime':'image/png'}];self.net.add(items=[d]);self.net.urls[ORIGIN+'media/a.png']=(b'image','image/png');self.sub();self.assertTrue(self.item()['has_visual_media']);self.assertIn('/reader-media/',self.r.rendered(self.item()['key']))
    def test_failure_preserves_cached_content(self):
        sid=self.sub();before=copy.deepcopy(self.r.state['items']);self.net.urls={};self.r.sync(sid);self.assertEqual(before,self.r.state['items']);self.assertTrue(self.r.state['subscriptions'][sid]['error'])
    def test_rollback_and_stealth_edit_is_rejected(self):
        self.net.add(items=[doc(version=3)]);sid=self.sub();self.net.add(items=[doc(version=2,text='Rollback')]);self.r.sync(sid);self.assertEqual(self.item()['doc']['version'],3)
        self.net.add(items=[doc(version=3,text='Stealth')]);self.time='2026-02-03T00:00:00Z';self.r.sync(sid);self.assertNotIn('Stealth',self.item()['doc']['content_md']);self.assertTrue(any('Rejected same-version' in w for w in self.r.state['subscriptions'][sid]['warnings']))
    def test_hash_and_origin_mismatches_are_not_stored(self):
        bad_hash=doc();bad_hash['content_hash']='sha256:'+'0'*64;self.net.add(items=[bad_hash]);sid=self.sub();self.assertEqual(self.r.listing(),[]);self.assertTrue(any('content hash mismatch' in w for w in self.r.state['subscriptions'][sid]['warnings']))
        bad_origin=doc(version=2,origin='https://imposter.example/');self.net.add(items=[bad_origin]);self.r.sync(sid);self.assertEqual(self.r.listing(),[]);self.assertTrue(any('origin differs' in w for w in self.r.state['subscriptions'][sid]['warnings']))
    def test_withdrawal_and_return_watermark(self):
        sid=self.sub();self.net.add(items=[doc(version=2,kind='withdrawn',text='')]);self.r.sync(sid);self.assertEqual(self.r.listing(),[]);self.assertEqual(self.r.state['watermarks'][self.r.key(ORIGIN,IID)]['version'],2)
        self.net.add(items=[doc()]);self.r.sync(sid);self.assertEqual(self.r.listing(),[])
        self.net.add(items=[doc(version=3)]);self.r.sync(sid);self.assertEqual(len(self.r.listing()),1)
    def test_unknown_kind_is_ignored_and_author_is_opaque(self):
        d=doc();d['author']=['future','author'];self.net.add(items=[d,doc(iid='0'*25+'2',kind='future')]);self.sub();self.assertEqual(len(self.r.listing()),1)
    def test_old_text_retained(self):
        self.sub();self.time='2028-01-03T00:00:00Z';self.assertEqual(self.r.cleanup(),[]);self.assertEqual(len(self.r.listing()),1)
    def test_old_image_evicted_subscription_and_watermark_retained(self):
        i=self.media();p=self.r.asset_path(next(iter(i['assets'].values())));self.time='2027-01-03T00:00:01Z';calls=list(self.net.calls);self.r.cleanup();self.assertFalse(p.exists());self.assertEqual(len(self.r.listing()),1);self.assertEqual(self.item()['assets'],{});self.assertEqual(len(self.r.state['subscriptions']),1);self.assertEqual(self.net.calls,calls);self.assertEqual(self.r.state['watermarks'][i['key']]['version'],1)
    def test_old_video_evicted_and_young_media_kept(self):
        self.media('video');self.time='2026-12-31T00:00:00Z';self.r.cleanup();self.assertEqual(len(self.r.listing()),1);self.time='2027-01-03T00:00:01Z';self.r.cleanup();self.assertEqual(len(self.r.listing()),1);self.assertEqual(self.item()['assets'],{})
    def test_exact_365_days_kept(self):
        self.media();self.time='2027-01-02T00:00:00Z';self.r.cleanup();self.assertEqual(len(self.r.listing()),1)
    def test_sync_after_media_cleanup_keeps_first_download_clock(self):
        self.media();first=self.item()['first_downloaded_at'];self.time='2027-01-03T00:00:01Z';self.r.cleanup();self.r.sync(digest(ORIGIN));self.assertEqual(self.item()['first_downloaded_at'],first)
    def test_missing_media_and_outside_paths_are_safe(self):
        i=self.media();self.r.asset_path(next(iter(i['assets'].values()))).unlink();outside=self.data/'keep.txt';outside.write_text('keep');i['assets']['evil']='../../keep.txt';self.time='2027-01-03T00:00:01Z';self.r.cleanup();self.assertEqual(outside.read_text(),'keep')
    def test_shared_media_retained_for_young_item(self):
        i=self.media();j=copy.deepcopy(i);j['key']='other';j['first_downloaded_at']='2027-01-02T00:00:00Z';self.r.state['items']['other']=j;p=self.r.asset_path(next(iter(i['assets'].values())));self.time='2027-01-03T00:00:01Z';self.r.cleanup();self.assertTrue(p.exists());self.assertEqual(len(self.r.state['items']),2);self.assertEqual(self.r.state['items'][i['key']]['assets'],{})
    def test_symlink_not_followed(self):
        outside=self.data/'outside';outside.write_bytes(b'keep');name='a'*64+'.png';(self.r.assets/name).symlink_to(outside);self.r.cleanup();self.assertEqual(outside.read_bytes(),b'keep');self.assertTrue((self.r.assets/name).is_symlink())
    def test_avatar_not_meaningful_visual_media(self):
        d=doc();d['content_html']='<img src="media/avatar.png" width="16" height="16" alt="avatar">';self.net.add(items=[d]);self.net.urls[ORIGIN+'media/avatar.png']=(b'icon','image/png');self.sub();self.assertFalse(self.item()['has_visual_media'])
    def test_origin_claim_does_not_replace_fetch_identity(self):
        self.net.urls[ORIGIN+'blyg.json'][0]['site']='https://imposter.example/';self.sub();self.assertEqual(self.item()['origin'],ORIGIN);self.assertTrue(self.r.state['subscriptions'][digest(ORIGIN)]['warning'])
    def test_like_and_private_responses_are_distinct_and_append_only(self):
        self.sub();key=self.r.key(ORIGIN,IID)
        self.r.mark(key,'liked',True);self.r.react(key,'🤯');self.r.react(key,'🙄');self.r.react(key,'🙄')
        item=self.r.item(key);self.assertTrue(item['liked']);self.assertIsNone(item['reaction'])
        rows=self.r.interactions();self.assertEqual([row['kind'] for row in rows],['reaction_clear','reaction','reaction','like'])
        self.assertEqual(rows[1]['reaction'],'🙄');self.assertEqual(rows[2]['reaction'],'🤯')
        reloaded=Reader(self.data,self.net,lambda:self.time);self.assertTrue(reloaded.item(key)['liked']);self.assertIsNone(reloaded.item(key)['reaction']);self.assertEqual(len(reloaded.interactions()),4)
    def test_private_response_allowlist_and_search(self):
        self.sub();key=self.r.key(ORIGIN,IID)
        for reaction in ('🤯','🙄','👎','😂','❓'):self.r.react(key,reaction)
        with self.assertRaisesRegex(ValueError,'Unknown private response'):self.r.react(key,'🔥')
        self.assertEqual(self.r.item(key)['reaction'],'❓');self.assertEqual(len(self.r.interactions('remote words')),5)
    def test_existing_markers_backfill_without_entering_item_document(self):
        self.sub();key=self.r.key(ORIGIN,IID);self.r.state['items'][key].update(saved=True,saved_at=self.time,liked=True,reaction='😂');self.r.state.pop('interaction_marker_backfill_v1',None);self.r.state['interactions']=[];self.r.state['interaction_seq']=0;self.r.save()
        reloaded=Reader(self.data,self.net,lambda:self.time);self.assertEqual({row['kind'] for row in reloaded.interactions()},{'save','like','reaction'});self.assertTrue(all(row['backfilled'] for row in reloaded.interactions()));self.assertNotIn('interactions',reloaded.item(key)['doc'])
    def test_publication_interactions_dedupe_and_ignore_own_origin(self):
        self.sub();own='https://mine.example/blyg/';remote={'origin':ORIGIN,'id':IID,'version':1};local={'origin':own,'id':'0'*25+'2','version':1}
        current={'id':'0'*25+'3','version':1,'created':self.time,'updated':self.time,'transclusions':[remote,local],'stub_of':remote,'forked_from':remote}
        self.r.own_origin=own;self.r.record_publications({}, {current['id']:current});self.r.record_publications({}, {current['id']:current})
        self.assertEqual([row['kind'] for row in reversed(self.r.interactions())],['quote','stub','fork'])
        self.assertTrue(all(row['origin']==ORIGIN for row in self.r.interactions()))

class ReaderPublicationTests(unittest.TestCase):
    def setUp(self):
        from test_core import StudioTests
        self.fixture=StudioTests();self.fixture.setUp();self.s=self.fixture.studio;self.net=Net();self.net.add(items=[doc(kind='thread')]);self.s.reader=Reader(self.s.data,self.net,lambda:'2026-01-02T00:00:00Z');self.s.reader.subscribe(ORIGIN)
    def tearDown(self):self.fixture.tearDown()
    def test_remote_quote_publishes_offline_with_provenance_without_reemission(self):
        self.s.migrate();self.s.state['published']={p.stem:json.loads(p.read_text()) for p in (self.s.root/'blyg/items').glob('*.json') if p.name!='index.json'}
        self.assertTrue(any(c['source']=='local' for c in self.s.quote_choices()));self.assertTrue(any(c['source']=='remote' and c['kind']=='thread' for c in self.s.quote_choices()))
        self.net.urls={};self.net.calls=[];q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));d=self.s.create('Response');d['raw']=d['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(d);self.s.prepare()
        own=self.s.state['ids'][d['name']];published=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(published['transclusions'],[{'id':IID,'version':1,'origin':ORIGIN}]);self.assertIn('data-blyg-origin',published['content_html']);self.assertIn('Remote words',published['content_html']);self.assertFalse((self.s.root/f'blyg/items/{IID}.json').exists());self.assertNotIn(IID,[i['id'] for i in json.loads((self.s.root/'blyg/items/index.json').read_text())['items']]);self.assertEqual(self.net.calls,[])
    def test_unchanged_remote_quote_survives_missing_reader_item(self):
        q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));page=self.s.create('Response');page['raw']=page['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(page);self.s.prepare();own=self.s.state['ids'][page['name']];before=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.s.state['published'][own]=copy.deepcopy(before)
        del self.s.reader.state['items'][self.s.reader.key(ORIGIN,IID)];self.s.reader.save();self.s.state['drafts'].pop(page['name'],None);self.s.create('Unrelated');self.s.prepare();after=json.loads((self.s.root/f'blyg/items/{own}.json').read_text())
        self.assertEqual(after,before)
    def test_response_stub_tracks_the_version_actually_quoted(self):
        q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));page=self.s.create('Response',stub_of=q['stub_of']);page['raw']=page['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(page)
        newer=doc(version=2,text='New source words');newer['changelog']=[{'version':1,'at':'2026-01-01T00:00:00Z'},{'version':2,'at':'2026-01-02T00:00:00Z'}];self.net.add(items=[newer]);self.s.reader.sync();self.s.prepare();out=json.loads((self.s.root/'blyg/items'/f"{self.s.state['ids'][page['name']]}.json").read_text())
        self.assertEqual(out['transclusions'][0]['version'],2);self.assertEqual(out['stub_of'],{'id':IID,'version':2,'origin':ORIGIN})

    def test_remote_stub_real_save_reload_html_roundtrip_writes_canonical_transclusion(self):
        quoted=self.s.reader.snapshot(self.s.reader.key(ORIGIN,IID),{'mode':'whole','transclude':True},self.s)
        page=self.s.create('Real remote response',stub_of=quoted['stub_of'])
        page['raw']=page['raw'].replace('<p>Start writing here.</p>',quoted['stub_label_html']+quoted['html']+'<p>My response—it’s mine.</p>')
        page['quotes']={quoted['snapshot']['token']:quoted['snapshot']};page['preserve_authored_typography']=True;self.s.save_draft(page)
        reopened=self.s.page(page['name']);self.assertIn('blynger-citation blyg-transclusion',reopened['raw'])
        self.assertIn('My response—it’s mine.',reopened['raw'])
        reopened['raw']=reopened['raw'].replace('Remote words','Altered source words');self.s.save_draft(reopened);again=self.s.page(page['name'])
        protected=BeautifulSoup(again['raw'],'html.parser').select_one('blockquote[data-blynger-quote]')
        self.assertIn('Remote words',protected.get_text(' ',strip=True));self.assertNotIn('Altered source words',protected.get_text(' ',strip=True))
        self.s.prepare();own=self.s.state['ids'][page['name']];final=json.loads((self.s.root/f'blyg/items/{own}.json').read_text())
        reference={'id':IID,'version':1,'origin':ORIGIN}
        self.assertEqual(final['kind'],'thread');self.assertEqual(final['stub_of'],quoted['stub_of']);self.assertEqual(final['transclusions'],[reference])
        self.assertIn('![['+IID+']]',final['content_md']);self.assertIn('class="blyg-transclusion"',final['content_html']);self.assertIn('data-blyg-origin="'+ORIGIN+'"',final['content_html'])
        self.assertNotIn('blynger-citation',final['content_html']);self.assertNotIn('data-blynger-quote',final['content_html'])

    def test_legacy_remote_stub_context_is_upgraded_before_final_json(self):
        quoted=self.s.reader.snapshot(self.s.reader.key(ORIGIN,IID),{'mode':'whole','transclude':True},self.s);page=self.s.create('Legacy UI response',stub_of=quoted['stub_of'])
        page['raw']=page['raw'].replace('<p>Start writing here.</p>',quoted['stub_html']+'<p>My response.</p>');self.s.save_draft(page);reopened=self.s.page(page['name'])
        self.assertNotIn('blynger-stub-context',reopened['raw']);self.assertIn('data-blynger-quote',reopened['raw']);self.s.prepare();own=self.s.state['ids'][page['name']]
        final=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(final['transclusions'],[{'id':IID,'version':1,'origin':ORIGIN}])
        self.assertIn('![['+IID+']]',final['content_md']);self.assertIn('blyg-transclusion',final['content_html'])
        self.assertNotIn('blynger-citation',final['content_html']);self.assertNotIn('data-blynger-quote',final['content_html'])

    def test_deleting_protected_stub_source_keeps_only_response_relationship(self):
        quoted=self.s.reader.snapshot(self.s.reader.key(ORIGIN,IID),{'mode':'whole','transclude':True},self.s);page=self.s.create('Response without source block',stub_of=quoted['stub_of'])
        page['raw']=page['raw'].replace('<p>Start writing here.</p>',quoted['stub_label_html']+quoted['html']+'<p>My response.</p>');page['quotes']={quoted['snapshot']['token']:quoted['snapshot']};self.s.save_draft(page)
        reopened=self.s.page(page['name']);soup=BeautifulSoup(reopened['raw'],'html.parser');soup.select_one('blockquote[data-blynger-quote]').decompose();reopened['raw']=str(soup);self.s.save_draft(reopened);self.s.prepare();own=self.s.state['ids'][page['name']]
        final=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(final['kind'],'thread');self.assertEqual(final['stub_of'],quoted['stub_of']);self.assertEqual(final['transclusions'],[]);self.assertNotIn('![['+IID+']]',final['content_md'])

    def test_plain_web_stub_remains_editable_context_without_transclusion(self):
        url='https://plain.example/story';self.net.urls[url]=('<html><head><title>Plain story</title></head><body><main><p>Ordinary web words.</p></main></body></html>','text/html')
        opened=self.s.reader.open_url(url);quoted=self.s.reader.snapshot(opened['selected'],{'mode':'whole'},self.s);page=self.s.create('Web response',stub_of=quoted['stub_of'])
        page['raw']=page['raw'].replace('<p>Start writing here.</p>',quoted['stub_html']+'<p>My response.</p>');self.s.save_draft(page);reopened=self.s.page(page['name'])
        self.assertIn('blynger-stub-context',reopened['raw']);self.assertNotIn('data-blyg-id',reopened['raw']);self.s.prepare();own=self.s.state['ids'][page['name']]
        final=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(final['kind'],'thread');self.assertEqual(final['stub_of']['url'],url);self.assertEqual(final['stub_of']['cited']['url'],url);self.assertTrue(final['stub_of']['cited']['excerpt']);self.assertEqual(final['transclusions'],[]);self.assertNotIn('![[',final['content_md'])

    def test_quote_is_not_implicitly_a_stub_and_response_survives_without_quote(self):
        quoted=self.s.reader.snapshot(self.s.reader.key(ORIGIN,IID),{'mode':'whole'},self.s)
        ordinary=self.s.create('Quotation only');ordinary['raw']=ordinary['raw'].replace('<p>Start writing here.</p>',quoted['html']);ordinary['quotes']={quoted['snapshot']['token']:quoted['snapshot']};self.s.save_draft(ordinary)
        response=self.s.create('Actual response',stub_of=quoted['stub_of']);self.s.save_draft(response);self.s.prepare()
        ordinary_doc=json.loads((self.s.root/'blyg/items'/f"{self.s.state['ids'][ordinary['name']]}.json").read_text())
        response_doc=json.loads((self.s.root/'blyg/items'/f"{self.s.state['ids'][response['name']]}.json").read_text())
        self.assertNotIn('stub_of',ordinary_doc)
        self.assertEqual(response_doc['kind'],'thread');self.assertEqual(response_doc['stub_of'],quoted['stub_of']);self.assertEqual(response_doc['transclusions'],[])

    def test_stub_target_is_exact_and_immutable(self):
        quoted=self.s.reader.snapshot(self.s.reader.key(ORIGIN,IID),{'mode':'whole'},self.s);target=quoted['stub_of']
        self.assertEqual(target['origin'],ORIGIN);self.assertEqual(target['id'],IID);self.assertEqual(target['version'],1);self.assertIn('cited',target)
        self.assertIn('<strong>Stubbing:</strong>',quoted['stub_html'])
        self.assertIn('<strong>Stubbing:</strong>',quoted['stub_label_html'])
        self.assertIn('href="https://remote.example/notes/t/'+IID+'/"',quoted['stub_html'])
        self.assertIn('Remote words',quoted['stub_html'])
        self.assertNotIn('data-blynger-quote',quoted['stub_html'])
        response=self.s.create('Response',stub_of=target);response['stub_of']={**target,'version':2}
        with self.assertRaisesRegex(ValueError,'cannot be changed'):self.s.save_draft(response)
    def test_cleanup_cannot_touch_authored_material(self):
        d=self.s.create('Keep draft');self.s.migrate_openers();before_state=copy.deepcopy(self.s.state);before_files={str(p):p.read_bytes() for p in self.s.root.rglob('*') if p.is_file() and '.git' not in p.parts};r=self.s.reader;i=r.state['items'][r.key(ORIGIN,IID)];i['has_visual_media']=True;r.clock=lambda:'2028-01-01T00:00:00Z';r.cleanup();self.assertEqual(self.s.state,before_state);self.assertEqual(before_files,{str(p):p.read_bytes() for p in self.s.root.rglob('*') if p.is_file() and '.git' not in p.parts})
    def test_ambiguous_remote_id_is_not_silently_selected(self):
        other='https://second.example/';self.net.add(other,[doc(origin=other)]);self.s.reader.subscribe(other)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID))
    def test_local_thread_self_quote_rejected(self):
        self.s.migrate();self.s.state['published']={p.stem:json.loads(p.read_text()) for p in (self.s.root/'blyg/items').glob('*.json') if p.name!='index.json'};iid=self.s.state['ids']['1.html'];d=self.s.page('1.html');d['raw']=d['raw'].replace('Original','![['+iid+']]');d['raw']=d['prefix']+'<p>![['+iid+']]</p>'+d['suffix'];self.s.save_draft(d)
        with self.assertRaisesRegex(ValueError,'cannot quote itself'):self.s.prepare()
    def test_quoted_media_survives_reader_eviction_and_unrelated_publication(self):
        import subprocess
        d=doc(kind='thread');d['content_html']='<p>Picture</p><img src="media/photo.png">';self.net.add(items=[d]);self.net.urls[ORIGIN+'media/photo.png']=(b'picture-data','image/png');self.s.reader.clock=lambda:'2026-01-03T00:00:00Z';self.s.reader.sync()
        q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));page=self.s.create('Picture response');page['raw']=page['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(page)
        remote=self.fixture.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);self.s.git('remote','add','website',str(remote));review=self.s.prepare();self.s.publish(review['signature'])
        iid=self.s.state['ids'][page['name']];before=json.loads((self.s.root/f'blyg/items/{iid}.json').read_text());assets=list((self.s.root/'blyg/media').glob('*'));self.assertTrue(assets)
        quote_actions=[row for row in self.s.reader.interactions() if row['kind']=='quote' and row.get('own_item_id')==iid]
        self.assertEqual(len(quote_actions),1);self.assertEqual(quote_actions[0]['remote_id'],IID)
        self.s.reader.clock=lambda:'2028-01-01T00:00:00Z';self.s.reader.cleanup();self.assertEqual(len(self.s.reader.listing()),1);self.assertTrue(all(p.exists() for p in assets));self.net.calls=[];self.net.urls={}
        self.s.create('Unrelated post');self.s.prepare();after=json.loads((self.s.root/f'blyg/items/{iid}.json').read_text());self.assertEqual(before['content_html'],after['content_html']);self.assertEqual(before['version'],after['version']);self.assertEqual(self.net.calls,[])
    def test_local_thread_reference_and_indirect_cycle(self):
        self.s.migrate();self.s.state['published']={p.stem:json.loads(p.read_text()) for p in (self.s.root/'blyg/items').glob('*.json') if p.name!='index.json'}
        iid=self.s.state['ids']['1.html'];self.s.state['published'][iid]['kind']='thread';self.s.state['published'][iid]['transclusions']=[];q=self.s.quote_item('local',iid);self.assertEqual(q['kind'],'thread');page=self.s.create('Local quote');page['raw']=page['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(page);self.s.prepare();own=self.s.state['ids'][page['name']];output=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(output['transclusions'],[{'id':iid,'version':1}]);self.assertIn('Original',output['content_html'])
        self.s.state['published'][iid]['transclusions']=[{'id':own,'version':1}]
        with self.assertRaisesRegex(ValueError,'cannot quote itself'):self.s.prepare()

    def test_tk_surrounding_fragments_keep_remote_quote_in_parent(self):
        self.net.calls=[];q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));d=self.s.create('Quote plus TK')
        body=q['html']+'<p>My commentary.</p><div class="blyg-tk-gen">Generated commentary.</div>'
        d['raw']=d['prefix']+body+d['suffix'];from bs4 import BeautifulSoup
        blocks=[{'id':'b'+str(i),'html':str(n)} for i,n in enumerate(BeautifulSoup(body,'html.parser').contents)]
        d['fragments']={'version':1,'blocks':blocks,'dividers':['b2'],'ranges':[{'key':'first','start':'b0','end':'b2'},{'key':'tk','start':'b2','end':None}]};d['generated']=[{'sources':[]}]
        self.s.save_draft(d);saved=self.s.page(d['name']);self.assertEqual(saved['raw'],d['raw']);self.assertEqual(saved['fragments']['ranges'][0]['start'],'b1');self.assertEqual(saved['fragments']['ranges'][1]['key'],'tk')
        self.s.prepare();own=self.s.state['ids'][d['name']];out=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertIn({'id':IID,'version':1,'origin':ORIGIN},out['transclusions']);self.assertIn('Remote words',out['content_html']);self.assertIn('Generated commentary.',out['content_html']);self.assertEqual(self.net.calls,[])
        for iid in self.s.state['fragment_ids'][d['name']].values():self.assertNotIn('![[',json.loads((self.s.root/f'blyg/items/{iid}.json').read_text())['content_md'])

    def test_native_quote_publishes_only_the_normative_source_body(self):
        from bs4 import BeautifulSoup
        d=self.s.create('My response');q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));self.assertNotIn('Other Author',q['html']);d['raw']=d['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(d);self.s.prepare()
        soup=BeautifulSoup((self.s.root/d['name']).read_text(),'html.parser');quote=soup.select_one('blockquote[data-blyg-origin]');self.assertIsNone(quote.h4);self.assertNotIn('by Other Author',quote.get_text());self.assertIn('Remote words',quote.get_text());self.assertIsNotNone(soup.find('style',id='blynger-quote-style'))
    def test_untitled_source_opening_stays_inside_quote_without_invented_heading(self):
        from bs4 import BeautifulSoup
        remote=doc(kind='thread');remote.pop('title');remote['content_html']='<p>Opening sentence.</p><div class="blyg-tk-gen"><p>Generated source text.</p></div>';self.net.add(items=[remote]);self.s.reader.clock=lambda:'2026-01-03T00:00:00Z';self.s.reader.sync()
        d=self.s.create('My headline');q=self.s.quote_item('remote',self.s.reader.key(ORIGIN,IID));d['raw']=d['raw'].replace('<p>Start writing here.</p>',q['html']);self.s.save_draft(d);self.s.prepare();soup=BeautifulSoup((self.s.root/d['name']).read_text(),'html.parser');quote=soup.select_one('blockquote[data-blyg-origin]');self.assertIsNone(quote.h4);self.assertIn('Opening sentence.',quote.get_text());self.assertIn('Generated source text.',quote.get_text());quote.decompose();self.assertNotIn('Opening sentence.',soup.get_text())
    def test_heading_formatted_quote_is_resolved_and_inline_code_untouched(self):
        d=self.s.create('Edited initial headline');d['raw']=d['raw'].replace('<p>Start writing here.</p>','<h2><span>![['+IID+']]</span></h2><p>Inline ![['+IID+']] remains text.</p><pre><code>![['+IID+']]</code></pre>');self.s.save_draft(d);self.s.prepare();own=self.s.state['ids'][d['name']];out=json.loads((self.s.root/f'blyg/items/{own}.json').read_text());self.assertEqual(len(out['transclusions']),1);self.assertIn('Remote words',out['content_html']);self.assertNotIn('<h2>',out['content_html']);self.assertIn('Inline ![[',out['content_html']);self.assertIn('<pre><code>![[',out['content_html'])
