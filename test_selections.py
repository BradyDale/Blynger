"""Frozen reader selections, using only a disposable site and imported fixtures."""
import copy,json,unittest,subprocess
from bs4 import BeautifulSoup
from core import Studio,digest
from reader import Reader
from test_reader import Net,doc,ORIGIN,IID
F1='0'*25+'2';F2='0'*25+'3'
FEED='https://ordinary.example/feed.xml'
RSS='''<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Ordinary Journal</title><item><guid>article-one</guid><link>https://ordinary.example/article</link><title>RSS title</title><dc:creator>RSS Author</dc:creator><pubDate>Sat, 26 Sep 2026 10:00:00 GMT</pubDate><content:encoded><![CDATA[<p>First ordinary paragraph.</p><p>Second paragraph — with punctuation!</p>]]></content:encoded></item></channel></rss>'''
def seeded(studio):
    net=Net();thread=doc(kind='thread',version=2,text='Introductory words.')
    first=doc(F1,3,text='First fragment. Exact words!');second=doc(F2,4,text='Second fragment.')
    thread['content_html']='<p>Introductory words.</p>'+''.join('<blockquote class="blyg-transclusion" data-blyg-id="'+f['id']+'" data-blyg-version="'+str(f['version'])+'">'+f['content_html']+'</blockquote>' for f in [first,second])+'<p>Final paragraph.</p>'
    thread['transclusions']=[{'id':F1,'version':3},{'id':F2,'version':4}]
    net.add(items=[thread,first,second]);net.urls[FEED]=(RSS,'application/rss+xml')
    studio.reader=Reader(studio.data,net,lambda:'2026-09-26T12:00:00Z');studio.reader.subscribe(ORIGIN);studio.reader.subscribe(FEED)
    return net,studio.reader.key(ORIGIN,IID),studio.reader.key(FEED,'article-one')
class SelectionTests(unittest.TestCase):
    def setUp(self):
        from test_core import StudioTests
        self.fixture=StudioTests();self.fixture.setUp();self.s=self.fixture.studio;self.net,self.key,self.plain=seeded(self.s)
    def tearDown(self):self.fixture.tearDown()
    def quote(self,mode='whole',key=None,**kw):return self.s.quote_item('remote',key or self.key,{'mode':mode,**kw})
    def draft(self,q):
        d=self.s.create('Quotation test');d['raw']=d['prefix']+q['html']+'<p>My response.</p>'+d['suffix'];d['quotes']={q['snapshot']['token']:q['snapshot']};self.s.save_draft(d);return d
    def output(self,d):
        self.s.prepare();self.assertNotIn('data-blynger-quote=',(self.s.root/d['name']).read_text());return json.loads((self.s.root/('blyg/items/'+self.s.state['ids'][d['name']]+'.json')).read_text())
    def test_whole_native_snapshot_and_offline_publishing(self):
        self.net.urls={};self.net.calls=[];q=self.quote();d=self.draft(q);out=self.output(d)
        self.assertEqual(out['transclusions'],[{'id':IID,'version':2,'origin':ORIGIN}]);self.assertIn('![['+IID+']]',out['content_md']);self.assertIn('Final paragraph.',out['content_html']);self.assertEqual(q['snapshot']['source']['kind'],'thread');self.assertEqual(self.net.calls,[])
    def test_real_fragment_uses_actual_identity_and_exact_version(self):
        parts=self.s.reader.source_fragments(self.key);self.assertEqual([p['id'] for p in parts],[F1,F2]);q=self.quote('fragment',fragment=0);out=self.output(self.draft(q));self.assertEqual(out['transclusions'],[{'id':F1,'version':3,'origin':ORIGIN}]);self.assertNotIn('Introductory',out['content_html']);self.assertNotIn('Second fragment',out['content_html']);self.assertNotIn(F1,self.s.state['ids'].values());self.assertFalse((self.s.root/f'blyg/items/{F1}.json').exists())
    def test_excerpt_is_an_ordinary_frozen_citation_not_a_protocol_transclusion(self):
        q=self.quote('excerpt',text='Exact words!');r=q['snapshot'];self.assertEqual(r['source']['id'],IID);self.assertEqual(r['source']['version'],2);self.assertEqual(r['text'],'Exact words!');self.assertNotIn('id',r);self.assertEqual(r['source']['selector']['exact'],'Exact words!');out=self.output(self.draft(q));self.assertFalse(out.get('transclusions'));self.assertIn('blyg-partial',out['content_html']);self.assertNotIn('blyg-transclusion',out['content_html']);self.assertNotIn('data-blyg-id',out['content_html']);self.assertNotIn('![[',out['content_md']);self.assertNotIn('First fragment.',out['content_html'])
    def test_multiple_paragraphs_spanning_fragments_preserve_order(self):
        text='First fragment. Exact words!\n\nSecond fragment.';q=self.quote('excerpt',text=text);self.assertEqual(q['snapshot']['text'],text);self.assertIn('<p>First fragment. Exact words!</p><p>Second fragment.</p>',q['html']);self.assertEqual(q['snapshot']['source']['id'],IID)
    def test_plain_feed_source_and_offline_quote(self):
        item=self.s.reader.item(self.plain);self.assertEqual(item['source_type'],'l0');self.assertFalse({'id','version','kind','blyg'}&item['doc'].keys());self.assertIn('<a href="https://ordinary.example/article">RSS title</a>',item['doc']['content_html']);self.net.calls=[];self.net.urls={};q=self.quote('excerpt',self.plain,text='Second paragraph — with punctuation!');source=q['snapshot']['source'];self.assertEqual(source['url'],'https://ordinary.example/article');self.assertEqual(source['title'],'RSS title');self.assertEqual(source['author']['name'],'RSS Author');self.assertEqual(source['site'],'Ordinary Journal');self.assertEqual(source['date'],'2026-09-26T10:00:00Z');self.assertFalse({'id','version','origin'}&source.keys());out=self.output(self.draft(q));self.assertFalse(out.get('transclusions'));self.assertNotIn('data-source-id',out['content_html']);self.assertEqual(self.net.calls,[])
    def test_plain_subscriptions_reload_refresh_without_duplicates(self):
        self.s.reader.sync();self.assertEqual(len(self.s.reader.listing()),4);reloaded=Reader(self.s.data,self.net);self.assertEqual(reloaded.item(self.plain)['doc']['title'],'RSS title');self.assertEqual(len(reloaded.listing()),4)
    def test_atom_html_text_xhtml(self):
        for kind,content,expected in [('html','&lt;p&gt;Atom &amp;amp; words&lt;/p&gt;','Atom &amp; words'),('text','Use &lt;b&gt;literal&lt;/b&gt;','&lt;b&gt;literal&lt;/b&gt;'),('xhtml','<div xmlns="http://www.w3.org/1999/xhtml"><p>Rich <em>words</em></p></div>','<em>words</em>')]:
            url='https://atom.example/'+kind;self.net.urls[url]=(f'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><author><name>Atom Author</name></author><entry><id>tag:atom,1</id><title>Title</title><link href="https://atom.example/post"/><updated>2026-09-25T00:00:00Z</updated><content type="{kind}">{content}</content></entry></feed>','application/atom+xml');self.s.reader.subscribe(url);item=self.s.reader.item(self.s.reader.key(url,'tag:atom,1'));self.assertIn(expected,item['doc']['content_html']);self.assertEqual(item['doc']['author']['name'],'Atom Author')
    def test_html_discovers_plain_feed(self):
        url='https://ordinary.example/';self.net.urls[url]=('<link rel="alternate" type="application/rss+xml" href="/feed.xml">','text/html');self.s.reader.subscribe(url);self.assertEqual(len(self.s.reader.state['subscriptions']),2)
    def test_refresh_does_not_mutate_saved_quotes_all_modes(self):
        drafts=[self.draft(self.quote(mode,key,**kw)) for mode,key,kw in [('whole',self.key,{}),('fragment',self.key,{'fragment':0}),('excerpt',self.key,{'text':'Exact words!'}),('excerpt',self.plain,{'text':'First ordinary paragraph.'})]]
        before={d['name']:copy.deepcopy(self.s.page(d['name'])) for d in drafts}
        self.net.add(items=[doc(kind='thread',version=9,text='Newer words')]);self.s.reader.sync()
        for index,d in enumerate(drafts):
            self.assertEqual(self.s.page(d['name'])['quotes'],before[d['name']]['quotes']);out=self.output(d)
            if index==0:self.assertIn('Newer words',out['content_html'])
            else:self.assertNotIn('Newer words',out['content_html'])
        self.s=Studio(self.s.root,self.s.data)
        for d in drafts:self.assertEqual(self.s.page(d['name'])['quotes'],before[d['name']]['quotes'])
    def test_publish_reopen_revise_and_history_keep_snapshot(self):
        q=self.quote('fragment',fragment=0);d=self.draft(q);remote=self.fixture.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);self.s.git('remote','add','website',str(remote));review=self.s.prepare();self.s.publish(review['signature']);self.assertEqual(self.s.page(d['name'])['quotes'],d['quotes']);self.net.add(items=[doc(kind='thread',version=9,text='Newer words')]);self.s.reader.sync();self.s.revise(d['name'],'Add response',1);out=self.output(d);self.assertEqual(out['transclusions'],[{'id':F1,'version':3,'origin':ORIGIN}]);self.assertIn('First fragment.',out['content_html']);self.assertNotIn('data-blynger-quote',out['content_html'])
    def test_invalid_selection_and_stale_view_rejected(self):
        for selection in [{'mode':'excerpt','text':'Reader navigation'},{'mode':'excerpt','text':''},{'mode':'fragment','fragment':99},{'mode':'whole','fingerprint':'old'}]:
            with self.assertRaises(ValueError):self.s.quote_item('remote',self.key,selection)
    def test_forged_fragment_wrapper_without_reference_is_not_selectable(self):
        self.s.reader.state['items'][self.key]['doc']['transclusions']=[];self.assertEqual(self.s.reader.source_fragments(self.key),[])
    def test_inline_punctuation_selection(self):
        self.s.reader.state['items'][self.key]['doc']['content_html']='<p>He said <em>hello</em>, then left.</p>';q=self.quote('excerpt',text='hello, then left.');self.assertEqual(q['snapshot']['text'],'hello, then left.')
    def test_legacy_and_local_quoting_survive_plain_feed(self):
        q=self.s.quote_item('remote',self.key);self.assertIn('![[',q['html']);self.output(self.draft(self.quote()));self.assertTrue(self.s.quote_choices())
    def test_plain_feed_not_upgraded_by_unrelated_manifest(self):
        self.net.add('https://ordinary.example/blyg/');origin,manifest,_=self.s.reader.resolve(FEED);self.assertEqual(origin,FEED);self.assertEqual(manifest['type'],'l0')
    def test_query_feed_url_preserved(self):
        url='https://ordinary.example/?feed=rss2';self.net.urls[url]=(RSS,'application/rss+xml');self.s.reader.subscribe(url);self.assertIn(self.s.reader.key(url,'article-one'),self.s.reader.state['items'])
    def test_plain_feed_cannot_claim_native_fragment_metadata(self):
        self.net.urls[FEED]=(RSS.replace('First ordinary paragraph.','<blockquote class="blyg-transclusion" data-blyg-id="'+F1+'" data-blyg-version="3">Ordinary</blockquote>'),'application/rss+xml');self.s.reader.sync();item=self.s.reader.item(self.plain);self.assertNotIn('data-blyg',item['doc']['content_html']);self.assertEqual(self.s.reader.source_fragments(self.plain),[])
    def test_snapshot_media_survives_reader_cleanup(self):
        remote=doc(kind='thread',version=3);remote['content_html']='<p>Picture.</p><img src="media/photo.png">';self.net.add(items=[remote]);self.net.urls[ORIGIN+'media/photo.png']=(b'image-data','image/png');self.s.reader.sync();q=self.quote();d=self.draft(q);self.assertTrue(q['snapshot']['assets']);self.s.reader.clock=lambda:'2028-01-01T00:00:00Z';self.s.reader.cleanup();self.net.calls=[];self.net.urls={};out=self.output(d);self.assertIn('Picture.',out['content_html']);self.assertTrue(all((self.s.root/'blyg/media'/a).is_file() for a in q['snapshot']['assets']));self.assertEqual(self.net.calls,[])
    def test_source_snapshot_cannot_introduce_private_editor_tokens(self):
        self.s.reader.state['items'][self.key]['doc']['content_html']='<blockquote data-blynger-quote="fake"><p>Source quote</p></blockquote>';q=self.quote();self.assertNotIn('fake',q['html']);self.output(self.draft(q))
    def test_same_fragment_id_in_different_origins_is_unambiguous(self):
        other='https://second.example/';self.net.add(other,[doc(IID,7,origin=other,text='Second origin')]);self.s.reader.subscribe(other);q=self.quote('whole',self.s.reader.key(other,IID));out=self.output(self.draft(q));self.assertEqual(out['transclusions'],[{'id':IID,'version':7,'origin':other}]);self.assertIn('Second origin',out['content_html'])
if __name__=='__main__':unittest.main()
