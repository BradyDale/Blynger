"""Private, origin-scoped Blyg reader. Never writes to a publication directory."""
import copy, hashlib, html, json, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from bs4 import BeautifulSoup
import nh3
from core import atomic, clean, digest, now
import interactions as interaction_log
from reader_network import fetch, normalized, public_url, request_once

ID=re.compile(r'^[0-7][0-9a-hjkmnp-tv-z]{25}$')
ASSET=re.compile(r'^[a-f0-9]{64}\.(png|jpg|gif|webp|avif|mp4|webm|ogg|mp3)$')
MIMES={'image/png':'png','image/jpeg':'jpg','image/gif':'gif','image/webp':'webp','image/avif':'avif','video/mp4':'mp4','video/webm':'webm','video/ogg':'ogg','audio/mpeg':'mp3','audio/ogg':'ogg'}
NS='https://blygger.org/ns/0.1'
REACTIONS=('🤯','🙄','👎','😂','❓')
MAX_FEED_ENTRIES=500
MAX_ARCHIVE_ITEMS=2000
MAX_ITEM_FETCHES=100
MAX_ITEM_BYTES=1024*1024
MAX_ASSETS_PER_ITEM=16
MAX_ASSET_BYTES=8*1024*1024
MAX_ASSET_BYTES_PER_SYNC=64*1024*1024
READER_TAGS={'a','abbr','b','blockquote','br','code','em','i','li','ol','strong','ul','p','div','span','hr','h1','h2','h3','h4','h5','h6','img','figure','figcaption','table','thead','tbody','tr','td','th','pre','audio','source','video','s','sub','sup','cite'}
READER_ATTR={'a':{'href','title'},'img':{'src','alt','width','height'},'audio':{'src','controls'},'video':{'src','controls','poster'},'source':{'src','type'},'blockquote':{'cite','data-blyg-id','data-blyg-version','data-blyg-origin'}}
READER_CLASSES={'div':{'blyg-tk-gen'},'p':{'blyg-tk-gen'},'span':{'blyg-tk-gen'},'blockquote':{'blyg-tk-gen','blyg-transclusion','blyg-partial'}}

def clean_reader(text):
    """Sanitize hostile imported markup for the isolated Reader document."""
    return nh3.clean(text,tags=READER_TAGS,attributes=READER_ATTR,allowed_classes=READER_CLASSES,
        clean_content_tags={'script','style','form','button','input','textarea','select','option','iframe','object','embed','svg','math','link','meta','base'},
        url_schemes={'http','https','mailto','tel'},link_rel='noopener noreferrer')
def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,AttributeError,TypeError):raise ValueError('Invalid Blyg timestamp.')
def selection_text(markup):
    """Block boundaries count as whitespace; inline emphasis does not add spaces."""
    soup=BeautifulSoup(markup,'html.parser')
    for node in soup.find_all(['p','div','blockquote','h1','h2','h3','h4','h5','h6','li','br']):
        node.insert_after('\n')
    return soup.get_text()

class Reader:
    def __init__(self,data,fetcher=None,clock=now,own_origin=None):
        self.root=Path(data)/'remote-reader';self.root.mkdir(parents=True,exist_ok=True)
        self.assets=self.root/'assets';self.assets.mkdir(exist_ok=True)
        self.file=self.root/'reader.json';self.clock=clock;self.fetch=fetcher or fetch;self.own_origin=own_origin
        self.state=json.loads(self.file.read_text()) if self.file.exists() else {'subscriptions':{},'items':{},'watermarks':{}}
        self.state.setdefault('subscriptions',{});self.state.setdefault('items',{});self.state.setdefault('watermarks',{})
        self.state.setdefault('interactions',[]);self.state.setdefault('interaction_seq',0)
        self._sync_lock=threading.Lock()
        self.cleanup_legacy_comment_feeds()
        self.backfill_markers()
        self.cleanup()
    def save(self):atomic(self.file,json.dumps(self.state,ensure_ascii=False,indent=2))
    def cleanup_legacy_comment_feeds(self):
        """Undo subscriptions made by the old Reader-link navigation path.

        Old records lack provenance, so only the unmistakable WordPress shape is
        eligible: a comments-channel title plus comment-anchor item links. Saved
        and Liked entries remain available locally.
        """
        if self.state.get('comment_feed_cleanup_v1'):return
        changed=False
        for sid,sub in self.state['subscriptions'].items():
            rows=[item for item in self.state['items'].values() if item.get('subscription')==sid]
            links=[str(item.get('doc',{}).get('url','')) for item in rows]
            unmistakable=str(sub.get('title','')).strip().lower().startswith('comments on:') and bool(links) and sum('#comment-' in link for link in links)>=max(1,len(links)*3//4)
            if not unmistakable:continue
            sub['active']=False;sub['blogroll']=False;sub['removed_reason']='Legacy Reader link opened a WordPress comments feed.';changed=True
            for key,item in list(self.state['items'].items()):
                if item.get('subscription')==sid and not item.get('saved') and not item.get('reaction') and not item.get('liked'):del self.state['items'][key]
        self.state['comment_feed_cleanup_v1']=True
        self.save()
    def key(self,origin,iid):return digest(origin+'\0'+iid)
    def asset_path(self,name):
        if not ASSET.fullmatch(name):raise ValueError('Invalid managed media name.')
        p=self.assets/name
        if p.is_symlink() or self.assets.is_symlink() or p.resolve().parent!=self.assets.resolve():raise ValueError('Unsafe managed media path.')
        return p
    def cleanup(self):
        now_at=timestamp(self.clock());item_cutoff=now_at-timedelta(days=365*3);media_cutoff=now_at-timedelta(days=365);removed=[];changed=False
        for key,item in list(self.state['items'].items()):
            if item.get('saved'):continue
            age=timestamp(item.get('first_downloaded_at',self.clock()))
            if age<item_cutoff:
                removed.append(key);del self.state['items'][key]
            elif age<media_cutoff and item.get('assets'):
                item['assets']={};item['has_visual_media']=False;changed=True
        # Assets are content addressed; retained items share files without ownership ambiguity.
        referenced={name for item in self.state['items'].values() for name in item.get('assets',{}).values()}
        for p in self.assets.iterdir():
            if p.name in referenced or not ASSET.fullmatch(p.name):continue
            try:
                safe=self.asset_path(p.name)
                if safe.is_file():safe.unlink()
            except (ValueError,FileNotFoundError):pass
        if removed or changed:self.save()
        return removed
    def resolve(self,url):
        original=normalized(url);candidate=original.rstrip('/')+'/';tried=[]
        match=re.search(r'/(?:f|t|items)/([0-7][0-9a-hjkmnp-tv-z]{25})(?:/|\.json|$)',original)
        target=match.group(1) if match else None
        def request(u):
            if u in tried or len(tried)>=6:return None
            tried.append(u)
            try:return self.fetch(u)
            except ValueError:return None
        def manifest(u):
            r=request(u)
            if not r:return None
            final,body,_,_=r
            try:m=json.loads(body)
            except (ValueError,UnicodeDecodeError):return None
            if not isinstance(m,dict) or not isinstance(m.get('blyg'),str):return None
            if not re.fullmatch(r'0\.\d+',m['blyg']):raise ValueError('This Blyg requires an unsupported major protocol version.')
            if not final.endswith('/blyg.json'):return None
            return final[:-len('blyg.json')],m
        hit=manifest(candidate+'blyg.json')
        if hit:return *hit,target
        r=request(original);soup=None;legacy=None
        if r:
            final,body,_,_=r
            try:
                tree=ET.fromstring(body)
                if tree.tag in ('rss','{http://www.w3.org/2005/Atom}feed'):legacy=(final,body)
                link=tree.find('.//{'+NS+'}manifest')
                if link is not None and link.text:
                    hit=manifest(urljoin(final,link.text.strip()))
                    if hit:return *hit,target
            except (ET.ParseError,DefusedXmlException):pass
            try:
                item=json.loads(body)
                if isinstance(item,dict) and isinstance(item.get('blyg'),str) and final.endswith('/blyg.json'):
                    if not re.fullmatch(r'0\.\d+',item['blyg']):raise ValueError('Unsupported Blyg major version.')
                    return final[:-len('blyg.json')],item,target
                if isinstance(item,dict) and ID.fullmatch(str(item.get('id',''))):
                    target=item['id']
                    if isinstance(item.get('origin'),str):
                        hit=manifest(normalized(item['origin']).rstrip('/')+'/blyg.json')
                        if hit:return *hit,target
            except (ValueError,UnicodeDecodeError):pass
            soup=BeautifulSoup(body,'html.parser');rel=soup.find('link',rel=lambda v:v and 'blyg' in v)
            if rel and rel.get('href'):
                hit=manifest(urljoin(final,rel['href']).rstrip('/')+'/blyg.json')
                if hit:return *hit,target
        if legacy and not tree.findall('.//{'+NS+'}id'):return legacy[0],{'type':'l0'},None
        u=urlsplit(original);root=urlunsplit((u.scheme,u.netloc,'/','',''))
        for path in ('blyg/blyg.json','blyg.json'):
            hit=manifest(root+path)
            if hit:
                match=re.search(r'/(?:f|t|items)/([0-7][0-9a-hjkmnp-tv-z]{25})(?:/|\.json|$)',original)
                return *hit,target or (match.group(1) if match else None)
        if legacy:return legacy[0],{'type':'l0'},None
        if soup:
            alternate=next((link for link in soup.find_all('link',rel=lambda v:v and 'alternate' in v,type=lambda v:v in ('application/rss+xml','application/atom+xml')) if 'comment' not in str(link.get('title','')).lower()),None)
            if alternate and alternate.get('href'):
                feed=request(urljoin(original,alternate['href']))
                if feed:
                    try:
                        tree=ET.fromstring(feed[1]);link=tree.find('.//{'+NS+'}manifest')
                        if link is not None and link.text:
                            hit=manifest(urljoin(feed[0],link.text.strip()))
                            if hit:return *hit,target
                        if tree.tag in ('rss','{http://www.w3.org/2005/Atom}feed'):return feed[0],{'type':'l0'},None
                    except (ET.ParseError,DefusedXmlException):pass
        raise ValueError('No usable feed found. Enter a Blyg, RSS/Atom feed, or a page linking to a feed. Tried: '+', '.join(tried))
    def subscribe(self,url,added_via='manual'):
        origin,m,target=self.resolve(url);sid=digest(origin)
        if self.own_origin and urlsplit(origin).netloc==urlsplit(self.own_origin).netloc:raise ValueError('Your own Blyg is already available in the writing archive and Quote post.')
        old=self.state['subscriptions'].get(sid,{})
        warning='Manifest site differs from its fetched origin.' if isinstance(m.get('site'),str) and m['site'].rstrip('/')+'/'!=origin else ''
        self.state['subscriptions'][sid]={**old,'id':sid,'origin':origin,'title':m.get('title') if isinstance(m.get('title'),str) else origin,'author':m.get('author'),'manifest':m,'type':'l0' if m.get('type')=='l0' else 'blyg','warning':warning,'added_at':old.get('added_at',self.clock()),'added_via':old.get('added_via',added_via),'blogroll':old.get('blogroll',False),'active':True}
        self.save();result=self.sync(sid)
        if self.state['subscriptions'][sid].get('error') and not old:
            message=self.state['subscriptions'][sid]['error'];del self.state['subscriptions'][sid];self.save();raise ValueError(message)
        result['selected']=self.key(origin,target) if target else None;return result
    def sync_plain(self,sub):
        sync_warnings=[]
        old=sub.get('feed_cache',{});headers={}
        if old.get('etag'):headers['If-None-Match']=old['etag']
        if old.get('modified'):headers['If-Modified-Since']=old['modified']
        final,body,h,status=self.fetch(sub['origin'],headers=headers)
        if status==304:
            sub['_pending_warnings']=sync_warnings
            return 0
        body_hash=digest(body);unchanged=old.get('hash')==body_hash or old.get('body')==body.decode('utf-8')
        # Ordinary feeds do not need their complete response body to interpret a
        # later 304. Keeping only a digest makes the private cache dramatically
        # smaller for large feeds while preserving validator-less comparison.
        sub['feed_cache']={'hash':body_hash,'etag':next((v for k,v in h.items() if k.lower()=='etag'),None),'modified':next((v for k,v in h.items() if k.lower()=='last-modified'),None)}
        if unchanged:
            sub['_pending_warnings']=sync_warnings;return 0
        try:root=ET.fromstring(body)
        except (ET.ParseError,DefusedXmlException):raise ValueError('Invalid or unsafe RSS/Atom feed.')
        atom='{http://www.w3.org/2005/Atom}';is_atom=root.tag==atom+'feed'
        if not is_atom and root.tag!='rss':raise ValueError('Not an RSS or Atom feed.')
        channel=root if is_atom else root.find('channel')
        if channel is None:raise ValueError('RSS channel is missing.')
        def value(node,path):
            el=node.find(path)
            if el is None:return ''
            if len(el):return ''.join(ET.tostring(x,encoding='unicode') for x in el)
            return el.text or ''
        sub['title']=BeautifulSoup(value(channel,atom+'title' if is_atom else 'title'),'html.parser').get_text() or sub['origin']
        count=0
        entries=channel.findall(atom+'entry' if is_atom else 'item')
        if len(entries)>MAX_FEED_ENTRIES:sync_warnings.append(f'Feed limited to {MAX_FEED_ENTRIES} entries.')
        asset_budget={'remaining':MAX_ASSET_BYTES_PER_SYNC}
        for entry in entries[:MAX_FEED_ENTRIES]:
            title=BeautifulSoup(value(entry,atom+'title' if is_atom else 'title'),'html.parser').get_text()
            if is_atom:
                link=next((x.get('href') for x in entry.findall(atom+'link') if x.get('rel','alternate')=='alternate' and x.get('href')),'')
                content=value(entry,atom+'content') or value(entry,atom+'summary')
                element=entry.find(atom+'content')
                if element is None:element=entry.find(atom+'summary')
                if element is not None and element.get('type','text')=='text':content='<p>'+html.escape(content)+'</p>'
                if element is not None and element.get('type')=='xhtml':
                    for node in element.iter():node.tag=node.tag.split('}')[-1]
                    content=''.join(ET.tostring(x,encoding='unicode') for x in element)
                identity=value(entry,atom+'id') or link;date=value(entry,atom+'published') or value(entry,atom+'updated');author=value(entry,atom+'author/'+atom+'name') or value(channel,atom+'author/'+atom+'name')
            else:
                link=value(entry,'link');content=value(entry,'{http://purl.org/rss/1.0/modules/content/}encoded') or value(entry,'description');identity=value(entry,'guid') or link;date=value(entry,'pubDate');author=value(entry,'{http://purl.org/dc/elements/1.1/}creator') or value(entry,'author')
            if not identity:identity=digest(title+'\0'+date+'\0'+content)
            url=urljoin(final,link) if link else final
            if urlsplit(url).scheme not in ('http','https'):url=final
            key=self.key(sub['origin'],identity);previous=self.state['items'].get(key,{})
            entry_hash=digest(ET.tostring(entry,encoding='utf-8'))
            if previous and previous.get('feed_entry_hash')==entry_hash:
                continue
            try:at=timestamp(date).isoformat().replace('+00:00','Z')
            except ValueError:
                try:at=parsedate_to_datetime(date).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
                except (ValueError,TypeError,AttributeError):at=previous.get('doc',{}).get('created',self.clock())
            plain_soup=BeautifulSoup(clean(content),'html.parser')
            for node in plain_soup.find_all(True):
                for attr in list(node.attrs):
                    if attr.startswith('data-'):del node[attr]
                if node.get('class'):node['class']=[c for c in node['class'] if not c.startswith(('blyg','reader-'))]
            content=str(plain_soup)
            text=selection_text(content).strip()
            if len(text)>2000:content='<p>'+html.escape(text[:1999].rstrip())+'…</p>'
            source_label=title.strip() if isinstance(title,str) and title.strip() else url
            content='<p class="reader-l0-source"><a href="'+html.escape(url,quote=True)+'">'+html.escape(source_label)+'</a></p>'+content
            doc={'title':title,'url':url,'author':{'name':author} if author else {},'created':at,'updated':at,'content_html':clean(content),'content_md':BeautifulSoup(content,'html.parser').get_text(' ',strip=True),'media':[]}
            doc_hash=digest(json.dumps(doc,sort_keys=True,ensure_ascii=False))
            previous_hash=previous.get('feed_content_hash')
            if previous and not previous_hash:
                previous_hash=digest(json.dumps(previous.get('doc',{}),sort_keys=True,ensure_ascii=False))
            if previous and previous_hash==doc_hash:
                # A publisher may reformat its XML or change channel metadata
                # without changing this entry. Remember the new wire hash but
                # leave observation time, media and local markers untouched.
                previous['feed_entry_hash']=entry_hash;previous['feed_content_hash']=doc_hash
                continue
            assets,visual,issues=self.download_assets(doc,url,previous,asset_budget)
            sync_warnings.extend(issues)
            self.state['items'][key]={'key':key,'subscription':sub['id'],'origin':sub['origin'],'source_type':'l0','feed_identity':identity,'feed_entry_hash':entry_hash,'feed_content_hash':doc_hash,'doc':doc,'first_downloaded_at':previous.get('first_downloaded_at',self.clock()),'observed_at':self.clock(),'assets':assets,'has_visual_media':visual,'saved':previous.get('saved',False),'saved_at':previous.get('saved_at'),'liked':previous.get('liked',False),'reaction':previous.get('reaction')}
            count+=1
        sub['_pending_warnings']=sync_warnings
        return count
    def download_assets(self,doc,origin,previous,budget=None):
        soup=BeautifulSoup(doc['content_html'],'html.parser');assets=dict(previous.get('assets',{}));used={};visual=False;warnings=[]
        urls={}
        for node in soup.find_all(['img','video','source','audio']):
            for attr in ('src','poster'):
                if not node.get(attr):continue
                url=urljoin(origin,node[attr]);is_visual=node.name in ('img','video') or (node.name=='source' and node.find_parent('video') is not None)
                if node.name=='img':
                    try:
                        if int(node.get('width',100))<=32 and int(node.get('height',100))<=32:is_visual=False
                    except ValueError:pass
                    if re.search(r'(?:avatar|favicon|tracking|site.logo)',node.get('class',[]).__str__()+' '+node.get('alt',''),re.I):is_visual=False
                urls[url]=urls.get(url,False) or is_visual
        for media in doc.get('media',[]):
            if isinstance(media,dict) and isinstance(media.get('url'),str):
                url=urljoin(origin,media['url']);urls[url]=urls.get(url,False) or str(media.get('mime','')).startswith(('image/','video/'))
        if len(urls)>MAX_ASSETS_PER_ITEM:warnings.append(f'Media limited to {MAX_ASSETS_PER_ITEM} files for this item.')
        budget=budget or {'remaining':MAX_ASSET_BYTES_PER_SYNC}
        for url,meaningful in list(urls.items())[:MAX_ASSETS_PER_ITEM]:
            name=assets.get(url)
            try:
                if not name or not self.asset_path(name).is_file():
                    if budget['remaining']<=0:
                        warnings.append('Media download budget reached; remaining files were skipped.');break
                    final,body,headers,status=self.fetch(url,limit=min(MAX_ASSET_BYTES,budget['remaining']))
                    budget['remaining']-=len(body)
                    mime=next((v.split(';')[0].strip() for k,v in headers.items() if k.lower()=='content-type'),'')
                    ext=MIMES.get(mime)
                    if not ext:continue
                    name=digest(body)+'.'+ext;atomic(self.asset_path(name),body)
                if name.endswith(('.png','.jpg','.gif','.webp','.avif')):
                    try:
                        from PIL import Image
                        with Image.open(self.asset_path(name)) as im:
                            if im.width<=32 and im.height<=32:meaningful=False
                    except OSError:pass
                used[url]=name;visual=visual or meaningful
            except ValueError as e:warnings.append(str(e))
        return used,visual,warnings
    def surface(self,sub,path,with_status=False,force=False):
        cache=sub.setdefault('surfaces',{});old=cache.get(path,{});headers={}
        if not force and old.get('etag'):headers['If-None-Match']=old['etag']
        if not force and old.get('modified'):headers['If-Modified-Since']=old['modified']
        final,body,response,status=self.fetch(sub['origin']+path,headers=headers)
        if not final.startswith(sub['origin']):raise ValueError('Subscription moved to a different origin; add the new origin explicitly.')
        if status==304:
            if 'body' not in old:raise ValueError('Unexpected empty conditional response.')
            return (old['body'],False) if with_status else old['body']
        text=body.decode('utf-8');lower={k.lower():v for k,v in response.items()};changed=force or old.get('body')!=text
        cache[path]={'body':text,'etag':lower.get('etag'),'modified':lower.get('last-modified')}
        return (text,changed) if with_status else text
    def _sync_subscription(self,sub):
        sub_started=time.monotonic();origin=sub['origin'];warnings=[];checked=0;downloaded=0
        try:
            if sub.get('type')=='web':
                sub['last_sync']=self.clock();sub['error']='';sub['error_kind']='';sub['last_result']='local page';return 0
            if sub.get('type')=='l0':
                downloaded=self.sync_plain(sub);sub['last_sync']=self.clock();sub['error']='';sub['error_kind']='';sub['warnings']=sub.pop('_pending_warnings',[]);sub['last_result']='unchanged' if not downloaded else 'updated';return downloaded
            # RSS is the notification plane; canonical documents alone advance state.
            feed_ids=[];feed_changed=True
            try:
                xml,feed_changed=self.surface(sub,'feed.xml',with_status=True);tree=ET.fromstring(xml)
                feed_ids=[n.text for n in tree.findall('.//{'+NS+'}id') if n.text and ID.fullmatch(n.text)]
            except (ValueError,ET.ParseError,DefusedXmlException):pass
            last_heal=sub.get('last_archive_heal');heal_due=not last_heal or timestamp(self.clock())-timestamp(last_heal)>=timedelta(days=1)
            if not feed_changed and not heal_due and not sub.get('sync_pending'):
                sub['last_sync']=self.clock();sub['error']='';sub['error_kind']='';sub['warnings']=warnings;sub['last_result']='unchanged';return 0
            try:
                index_text,index_changed=self.surface(sub,'items/index.json',with_status=True,force=heal_due)
                index=json.loads(index_text)
                if heal_due:sub['last_archive_heal']=self.clock()
            except ValueError:
                if not feed_ids:raise
                index={'items':[{'id':iid} for iid in set(feed_ids)]};index_changed=True;warnings.append('Archive index unavailable: feed-window-only sync is lossy.')
            if not isinstance(index,dict) or not isinstance(index.get('items'),list):raise ValueError('Invalid archive index.')
            if len(index['items'])>MAX_ARCHIVE_ITEMS:raise ValueError(f'Archive exceeds the current {MAX_ARCHIVE_ITEMS:,}-item sync limit.')
            rows=[]
            for row in index['items']:
                iid=row.get('id') if isinstance(row,dict) else None
                if not isinstance(iid,str) or not ID.fullmatch(iid):continue
                key=self.key(origin,iid);known=self.state['watermarks'].get(key,{}).get('version')
                version=row.get('version') if isinstance(row,dict) else None
                if (index_changed or feed_changed or sub.get('sync_pending')) and (version is None or version!=known or iid in feed_ids):rows.append(row)
            remaining=max(0,len(rows)-MAX_ITEM_FETCHES);rows=rows[:MAX_ITEM_FETCHES]
            sub['sync_pending']=bool(remaining)
            if remaining:warnings.append(f'{remaining} changed items remain for the next sync.')
            def fetch_item(row):
                iid=row['id'];return iid,self.fetch(origin+'items/'+iid+'.json',limit=MAX_ITEM_BYTES)
            fetched=[]
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(fetch_item,row) for row in rows]
                for future in as_completed(futures):
                    try:fetched.append(future.result())
                    except (ValueError,TypeError,AttributeError) as e:warnings.append(str(e))
            checked=len(rows)
            asset_budget={'remaining':MAX_ASSET_BYTES_PER_SYNC}
            for iid,(final,raw,_,_) in fetched:
                try:
                    doc=json.loads(raw)
                    if not final.startswith(origin+'items/'):raise ValueError('Item redirected outside its subscription origin.')
                    if not isinstance(doc,dict) or doc.get('id')!=iid:raise ValueError('Item identity does not match its endpoint.')
                    if doc.get('kind') not in ('fragment','thread','withdrawn'):continue
                    v=doc.get('version')
                    if type(v)!=int or v<1:raise ValueError('Invalid version.')
                    timestamp(doc.get('created'));timestamp(doc.get('updated'))
                    if not all(isinstance(doc.get(k),str) for k in ('content_md','content_html')):raise ValueError('Missing item content.')
                    key=self.key(origin,iid);old=self.state['items'].get(key,{});water=self.state['watermarks'].get(key,{})
                    if v<water.get('version',0):raise ValueError('Version rollback ignored for '+iid)
                    claimed=doc.get('content_hash');actual='sha256:'+digest(doc['content_md'])
                    if claimed!=actual:raise ValueError('Rejected item with content hash mismatch: '+iid)
                    if doc.get('origin')!=origin:raise ValueError('Rejected item whose origin differs from its subscription: '+iid)
                    if v==water.get('version') and actual!=water.get('hash'):raise ValueError('Rejected same-version edit: '+iid)
                    if old and v==water.get('version') and actual==water.get('hash') and timestamp(doc['updated'])<timestamp(old['doc']['updated']):continue
                    self.state['watermarks'][key]={'version':v,'hash':actual}
                    if doc['kind']=='withdrawn':self.state['items'].pop(key,None);continue
                    assets,visual,issues=self.download_assets(doc,origin,old,asset_budget);warnings.extend(issues)
                    self.state['items'][key]={'key':key,'subscription':sub['id'],'origin':origin,'doc':doc,'first_downloaded_at':old.get('first_downloaded_at',self.clock()),'observed_at':self.clock() if v!=water.get('version') else old.get('observed_at',self.clock()),'assets':assets,'has_visual_media':visual,'saved':old.get('saved',False),'saved_at':old.get('saved_at'),'liked':old.get('liked',False),'reaction':old.get('reaction')}
                    downloaded+=1
                except (ValueError,TypeError,AttributeError) as e:warnings.append(str(e))
            sub['last_sync']=self.clock();sub['error']='';sub['error_kind']='';sub['warnings']=warnings;sub['last_result']='updated' if downloaded else 'unchanged';return downloaded
        except (ValueError,TypeError,AttributeError) as e:
            sub['error']=str(e);sub['error_kind']='network' if str(e).startswith(('Could not fetch','HTTP ')) else 'invalid data';sub['last_result']='failed';return 0
        finally:
            sub['last_duration_ms']=round((time.monotonic()-sub_started)*1000);sub['last_checked']=checked;sub['last_downloaded']=downloaded
    def sync(self,sid=None):
        if not self._sync_lock.acquire(blocking=False):return {'message':'A Reader sync is already running.','already_running':True,'subscriptions':list(self.state['subscriptions'].values())}
        started=time.monotonic()
        try:
            self.cleanup();subs=self.state['subscriptions'];targets=[subs[sid]] if sid in subs and subs[sid].get('active',True) else [s for s in subs.values() if s.get('active',True)] if sid is None else []
            if sid is not None and not targets:raise ValueError('Unknown subscription.')
            if len(targets)>1:
                # Origins are independent. Six workers keep a mixed Reader from
                # waiting in long serial batches without hammering any one site.
                with ThreadPoolExecutor(max_workers=min(6,len(targets))) as pool:imported=sum(pool.map(self._sync_subscription,targets))
            else:imported=sum(self._sync_subscription(sub) for sub in targets)
            self.save();self.cleanup()
            return {'message':f'Sync finished in {time.monotonic()-started:.1f}s: {imported} changed items.','subscriptions':list(subs.values())}
        finally:self._sync_lock.release()
    def listing(self,subscription=None,query='',view='all'):
        out=[]
        for key,item in self.state['items'].items():
            if subscription and item['subscription']!=subscription:continue
            if view=='saved' and not item.get('saved'):continue
            if view=='liked' and not item.get('liked'):continue
            d=item['doc'];sub=self.state['subscriptions'][item['subscription']]
            if not sub.get('active',True) and view=='all':continue
            author=d.get('author')
            name=author.get('name') if isinstance(author,dict) else None
            name=name if isinstance(name,str) else sub['title']
            text=BeautifulSoup(d['content_html'],'html.parser').get_text(' ',strip=True)
            if query.lower() not in (text+' '+str(name)+' '+sub['title']).lower():continue
            published=d.get('created') or d.get('updated') or item['first_downloaded_at'];first_seen=item.get('first_downloaded_at',item.get('observed_at',published))
            title=self.display_title(item);excerpt=text
            if title and excerpt.startswith(title):excerpt=excerpt[len(title):].lstrip(' —–:;,.')
            out.append({'key':key,'origin':item['origin'],'subscription':item['subscription'],'author':name,'site':sub['title'],'id':d.get('id'),'kind':d.get('kind','article'),'version':d.get('version'),'source_type':item.get('source_type','blyg'),'date':published,'sort':min(published,first_seen),'title':title,'excerpt':excerpt[:280],'url':self.page_url(item),'stub_target':self.stub_target(item),'saved':bool(item.get('saved')),'saved_at':item.get('saved_at'),'liked':bool(item.get('liked')),'reaction':item.get('reaction')})
        return sorted(out,key=lambda i:(i['sort'],i['key']),reverse=True)
    def mark(self,key,field,value):
        if field not in ('saved','liked'):raise ValueError('Unknown Reader marker.')
        if key not in self.state['items']:raise ValueError('That Reader item is no longer available.')
        item=self.state['items'][key];item[field]=bool(value)
        if field=='saved':
            if value:item['saved_at']=self.clock()
            else:item.pop('saved_at',None)
        interaction_log.marker(self.state,item,field,value,self.clock(),self.display_title(item))
        self.save();return {'message':('Saved' if field=='saved' else 'Liked') if value else ('Removed from Saved' if field=='saved' else 'Removed from Liked')}
    def react(self,key,reaction):
        if key not in self.state['items']:raise ValueError('That Reader item is no longer available.')
        if reaction is not None and reaction not in REACTIONS:raise ValueError('Unknown private response.')
        item=self.state['items'][key];previous=item.get('reaction')
        value=None if reaction==previous else reaction
        item['reaction']=value
        interaction_log.reaction(self.state,item,value,self.clock(),self.display_title(item),previous)
        self.save();return {'message':'Private response saved.' if value else 'Private response cleared.','reaction':value}
    def interactions(self,query=''):
        return interaction_log.view(self.state.get('interactions',[]),query)
    def _interaction_label(self,origin,iid):
        item=self.state['items'].get(self.key(origin,iid))
        if not item:return {'label':iid,'target_url':origin,'source_type':'blyg'}
        return {'label':self.display_title(item),'target_url':self.page_url(item),'source_type':item.get('source_type','blyg')}
    def record_publications(self,previous,current,backfilled=False):
        changed=False
        for iid,doc in current.items():
            before=previous.get(iid)
            if before and int(before.get('version',0))>=int(doc.get('version',0)):continue
            for entry in interaction_log.publication_entries(before,doc,self.own_origin,self._interaction_label,backfilled):
                changed=interaction_log.append(self.state,entry) or changed
        if changed:self.save()
        return changed
    def backfill_markers(self):
        if self.state.get('interaction_marker_backfill_v1'):return
        for item in self.state['items'].values():
            label=self.display_title(item)
            if item.get('saved'):
                interaction_log.marker(self.state,item,'saved',True,item.get('saved_at') or self.clock(),label,True)
            if item.get('liked'):
                interaction_log.marker(self.state,item,'liked',True,self.clock(),label,True)
            reaction=item.get('reaction')
            if reaction in REACTIONS:
                interaction_log.reaction(self.state,item,reaction,self.clock(),label,None,True)
        self.state['interaction_marker_backfill_v1']=True;self.save()
    def backfill_publications(self,history):
        if self.state.get('interaction_publication_backfill_v1'):return
        for versions in history.values():
            before=None
            for version in sorted(versions,key=lambda value:int(value)):
                doc=versions[version]
                self.record_publications({doc.get('id'):before} if before else {},{doc.get('id'):doc},True)
                before=doc
        self.state['interaction_publication_backfill_v1']=True;self.save()
    def set_blogroll(self,sid,value):
        if sid not in self.state['subscriptions']:raise ValueError('Unknown subscription.')
        self.state['subscriptions'][sid]['blogroll']=bool(value);self.save();return {'message':'Blogroll choice saved locally.'}
    def unsubscribe(self,sid):
        if sid not in self.state['subscriptions'] or not self.state['subscriptions'][sid].get('active',True):raise ValueError('Unknown subscription.')
        sub=self.state['subscriptions'][sid];sub['active']=False;sub['blogroll']=False
        for key,item in list(self.state['items'].items()):
            if item.get('subscription')==sid and not item.get('saved') and not item.get('reaction') and not item.get('liked'):del self.state['items'][key]
        self.save();self.cleanup();return {'message':'Subscription removed. Saved and Liked posts remain on this Mac.'}
    def open_url(self,url,allow_subscription=True):
        """Open a Blyg/feed URL normally, or retain a sanitized one-page web item."""
        url=normalized(url)
        try:
            if not allow_subscription:raise ValueError('Feed links do not become subscriptions automatically. Use Add subscription if you want to follow this feed.')
            result=self.subscribe(url,'manual')
            if not result.get('selected'):
                match=next((key for key,item in self.state['items'].items() if item.get('source_type')=='l0' and item.get('doc',{}).get('url')==url),None)
                if match:result['selected']=match
            return result
        except ValueError as discovery_error:
            final,body,headers,_=self.fetch(url)
            content_type=next((v for k,v in headers.items() if k.lower()=='content-type'),'').lower()
            if 'html' not in content_type and not re.search(br'<(?:!doctype|html|head|body)\b',body[:2048],re.I):raise discovery_error
            soup=BeautifulSoup(body,'html.parser');title=soup.title.get_text(' ',strip=True) if soup.title else final
            article=soup.find('article') or soup.find('main') or soup.body or soup
            for node in article(['script','style','iframe','object','embed','form','nav','aside']):node.decompose()
            markup=clean(str(article));sid='web:'+digest(url);key=self.key(url,url);previous=self.state['items'].get(key,{})
            self.state['subscriptions'].setdefault(sid,{'id':sid,'origin':url,'title':urlsplit(final).netloc,'type':'web','added_at':self.clock(),'blogroll':False,'active':True})
            doc={'title':title,'url':final,'author':{},'created':previous.get('doc',{}).get('created',self.clock()),'updated':self.clock(),'content_html':markup,'content_md':BeautifulSoup(markup,'html.parser').get_text(' ',strip=True),'media':[]}
            assets,visual,warnings=self.download_assets(doc,final,previous)
            self.state['items'][key]={'key':key,'subscription':sid,'origin':url,'source_type':'web','feed_identity':url,'doc':doc,'first_downloaded_at':previous.get('first_downloaded_at',self.clock()),'observed_at':self.clock(),'assets':assets,'has_visual_media':visual,'saved':previous.get('saved',False),'saved_at':previous.get('saved_at'),'liked':previous.get('liked',False),'reaction':previous.get('reaction')}
            self.state['subscriptions'][sid].update(last_sync=self.clock(),error='',warnings=warnings)
            self.save();return {'message':'Opened a sanitized web page in Reader.','selected':key,'subscriptions':list(self.state['subscriptions'].values())}
    def fork_source(self,key,version=None):
        item=self.item(key)
        if item.get('source_type','blyg')!='blyg':raise ValueError('Only a pinned Blyg version can be forked. Ordinary web and RSS writing can be quoted instead.')
        doc=item['doc'];version=int(version or doc.get('version',0));entry=next((c for c in doc.get('changelog',[]) if c.get('version')==version),None)
        if not entry or not entry.get('pinned'):raise ValueError('That version is not pinned, so the Blyg protocol does not permit a fork from it.')
        source=doc
        if version!=doc.get('version'):
            final,body,_,_=self.fetch(item['origin']+'items/'+doc['id']+'/v'+str(version)+'.json');source=json.loads(body)
            if source.get('id')!=doc['id'] or source.get('version')!=version or not source.get('pinned'):raise ValueError('The remote pinned version did not validate.')
        # A fork becomes authored website content, so remote markup must cross the
        # same sanitizing boundary as Reader display before it enters a draft.
        # It also leaves Reader's base URL behind: make addresses permanent here
        # so a later preview or publication cannot reinterpret them as local URLs.
        soup=BeautifulSoup(clean(source.get('content_html','')),'html.parser')
        # A fork copies a pinned document but does not inherit the source's
        # verification claims. Flatten every baked transclusion to an ordinary
        # editable quotation and retain a visible route back to its provenance.
        for quote in list(soup.select('blockquote.blyg-transclusion')):
            origin=quote.get('data-blyg-origin');iid=quote.get('data-blyg-id')
            classes=[name for name in quote.get('class',[]) if name not in ('blyg-transclusion','blyg-partial')]
            if classes:quote['class']=classes
            elif quote.has_attr('class'):del quote['class']
            for attr in list(quote.attrs):
                if attr.startswith('data-blyg-') or attr.startswith('data-blynger-'):del quote[attr]
            if isinstance(origin,str) and isinstance(iid,str):
                attribution=soup.new_tag('p');attribution['class']='blynger-fork-attribution'
                link=soup.new_tag('a',href=urljoin(origin,'items/'+iid+'.json'));link.string='Quoted from '+urlsplit(origin).netloc+' · '+iid
                attribution.append(link);quote.insert_after(attribution)
        for node in soup.find_all(True):
            for attr in ('href','src','poster'):
                value=node.get(attr)
                if not isinstance(value,str) or not value or value.startswith('#'):continue
                resolved=urljoin(item['origin'],value)
                if urlsplit(resolved).scheme in ('http','https','mailto'):node[attr]=resolved
        present={node.get('src') for node in soup.find_all(src=True)}
        for media in source.get('media',[]):
            if not isinstance(media,dict) or not isinstance(media.get('url'),str):continue
            url=urljoin(item['origin'],media['url']);mime=str(media.get('mime',''))
            if url in present or urlsplit(url).scheme not in ('http','https'):continue
            tag='img' if mime.startswith('image/') else 'video' if mime.startswith('video/') else 'audio' if mime.startswith('audio/') else None
            if not tag:continue
            node=soup.new_tag(tag);node['src']=url
            if tag=='img':node['alt']=str(media.get('alt',''))
            else:node['controls']=''
            soup.append(node);present.add(url)
        markup=str(soup)
        title=re.sub(r'\s+',' ',BeautifulSoup(markup,'html.parser').get_text(' ',strip=True)).strip()
        inherited=[]
        if 'blyg-tk-gen' in markup:
            for entry in source.get('generated',[]):
                if not isinstance(entry,dict):continue
                disclosed={'sources':[]}
                for field in ('model','at'):
                    if isinstance(entry.get(field),str):disclosed[field]=entry[field]
                if disclosed not in inherited:inherited.append(disclosed)
            if not inherited:inherited=[{'sources':[]}]
        return {'title':title[:90] or 'Fork','html':markup,'generated':inherited,'forked_from':{'id':doc['id'],'version':version,'origin':item['origin']}}
    def item(self,key):
        if key not in self.state['items']:raise ValueError('That item is no longer cached. Sync its Blyg to download it again.')
        return copy.deepcopy(self.state['items'][key])
    def display_title(self,item):
        doc=item['doc']
        if item.get('source_type') in ('l0','web'):
            title=doc.get('title')
            if isinstance(title,str) and title.strip():return title.strip()
        text=re.sub(r'\s+',' ',BeautifulSoup(doc.get('content_html',''),'html.parser').get_text(' ',strip=True)).strip()
        return text[:90] or '(Untitled)'
    def stub_target(self,item):
        """Return a safe, presentational link for an imported Stub target."""
        target=item.get('doc',{}).get('stub_of')
        if not isinstance(target,dict):return None
        cited=target.get('cited') if isinstance(target.get('cited'),dict) else {}
        label=''
        for value in (cited.get('excerpt'),cited.get('source')):
            if isinstance(value,str) and value.strip():
                label=re.sub(r'\s+',' ',value).strip();break
        result={'version':target.get('version')}
        if isinstance(target.get('origin'),str) and isinstance(target.get('id'),str):
            key=self.key(target['origin'],target['id']);cached=self.state['items'].get(key)
            if cached:
                result.update(key=key,url=self.page_url(cached))
                if not label:label=self.display_title(cached)
            else:
                result['url']=target['origin']
                if not label:label=target['id']
        elif isinstance(target.get('url'),str):
            parsed=urlsplit(target['url'])
            if parsed.scheme not in ('http','https') or not parsed.netloc:return None
            result['url']=target['url']
            if not label:label=parsed.netloc.removeprefix('www.')
        else:return None
        result['label']=(label[:120]+'…') if len(label)>120 else label
        return result
    def conversation_links(self,item):
        """Return locally known response edges without claiming graph completeness."""
        doc=item.get('doc',{});backward=self.stub_target(item);forward=[]
        origin=str(item.get('origin','')).rstrip('/');iid=doc.get('id')
        if not origin or not isinstance(iid,str):return {'backward':backward,'forward':forward}
        for key,candidate in self.state['items'].items():
            if candidate.get('source_type') in ('l0','web'):continue
            target=candidate.get('doc',{}).get('stub_of')
            if not isinstance(target,dict):continue
            if str(target.get('origin','')).rstrip('/')!=origin or target.get('id')!=iid:continue
            cdoc=candidate['doc'];created=cdoc.get('created') or cdoc.get('updated') or candidate.get('observed_at','')
            forward.append({'key':key,'url':self.page_url(candidate),'label':self.display_title(candidate),'version':cdoc.get('version'),'date':created})
        forward.sort(key=lambda link:(link.get('date',''),link['key']))
        return {'backward':backward,'forward':forward}
    def page_url(self,item):
        d=item['doc']
        if item.get('source_type') in ('l0','web'):return d.get('url') or item['origin']
        page=d.get('page')
        if isinstance(page,str) and page and not urlsplit(page).scheme:
            resolved=urljoin(item['origin'],page)
            if urlsplit(resolved).netloc==urlsplit(item['origin']).netloc:return resolved
        if isinstance(d.get('url'),str) and d['url']:return d['url']
        return item['origin']+('t/' if d.get('kind')=='thread' else 'f/')+d['id']+'/'
    def rendered(self,key,asset_prefix='/reader-media/'):
        item=self.item(key);soup=BeautifulSoup(clean_reader(item['doc']['content_html']),'html.parser')
        base=item['doc'].get('url',item['origin']) if item.get('source_type') in ('l0','web') else item['origin']
        present={urljoin(base,n.get('src','')) for n in soup.find_all(src=True)}
        for media in item['doc'].get('media',[]):
            if not isinstance(media,dict) or not isinstance(media.get('url'),str):continue
            url=urljoin(base,media['url']);mime=str(media.get('mime',''))
            if url not in present and url in item['assets']:
                tag='img' if mime.startswith('image/') else 'video' if mime.startswith('video/') else 'audio'
                node=soup.new_tag(tag);node['src']=url;node['alt']=str(media.get('alt',''));soup.append(node);present.add(url)
        for node in soup.find_all(True):
            for attr in list(node.attrs):
                if attr.startswith('data-blynger-'):del node[attr]
            if node.get('href'):
                href=urljoin(base,node['href']);node['href']=href if urlsplit(href).scheme in ('http','https','mailto') else '#'
            for attr in ('src','poster'):
                if node.get(attr):
                    url=urljoin(base,node[attr]);name=item['assets'].get(url)
                    if name:node[attr]=asset_prefix+name
                    else:del node[attr]
            if node.name in ('video','audio'):node['controls']=''
        return str(soup)
    def quotation_html(self,key,asset_prefix='/reader-media/'):
        item=self.item(key);doc=item['doc'];body=BeautifulSoup(self.rendered(key,asset_prefix),'html.parser')
        title=doc.get('title') if item.get('source_type') in ('l0','web') else ''
        title=title.strip() if isinstance(title,str) else ''
        prefix=''
        if title:
            first=body.find(['h1','h2','h3','h4','h5','h6'])
            if first and first.get_text(' ',strip=True)==title:first.decompose()
            prefix='<h4 class="blynger-quote-title">'+html.escape(title)+'</h4>'
        author=doc.get('author');name=author.get('name') if isinstance(author,dict) else None
        url=self.page_url(item)
        label='by '+name.strip() if isinstance(name,str) and name.strip() else 'Source'
        prefix+='<p class="blynger-quote-author"><a href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a></p>'
        return prefix+str(body)
    def quote(self,key,studio):
        item=self.item(key);doc=item['doc']
        matches=[x for x in self.state['items'].values() if x['doc'].get('id')==doc['id']]
        if len(matches)!=1 or doc['id'] in studio.state['published']:raise ValueError('Ambiguous quote identity across origins.')
        url=self.page_url(item)
        author=doc.get('author');label=author.get('name') if isinstance(author,dict) else None
        label=label if isinstance(label,str) else self.state['subscriptions'][item['subscription']]['title']
        return {'html':'<p>![['+doc['id']+']]</p>','origin':item['origin'],'id':doc['id'],'version':doc['version'],'kind':doc['kind'],'title':self.display_title(item),'stub_of':{'id':doc['id'],'version':doc['version'],'origin':item['origin']}}

    def source_fragments(self,key):
        item=self.item(key)
        if item.get('source_type') in ('l0','web'):return []
        doc=item['doc'];out=[];soup=BeautifulSoup(self.rendered(key),'html.parser')
        references=doc.get('transclusions',[])
        for index,node in enumerate(soup.select('blockquote.blyg-transclusion[data-blyg-id]')):
            iid=node.get('data-blyg-id');origin=node.get('data-blyg-origin') or item['origin']
            try:version=int(node.get('data-blyg-version','0'))
            except ValueError:continue
            if not isinstance(iid,str) or not ID.fullmatch(iid) or version<1:continue
            if not any(r.get('id')==iid and r.get('version')==version and r.get('origin',item['origin'])==origin for r in references if isinstance(r,dict)):continue
            cached=self.state['items'].get(self.key(origin,iid),{}).get('doc',{})
            kind=cached.get('kind') if cached.get('version')==version else None
            text=selection_text(node.decode_contents())
            out.append({'index':index,'origin':origin,'id':iid,'version':version,'kind':kind or 'item','html':node.decode_contents(),'text':text,'label':re.sub(r'\s+',' ',text).strip()[:100] or 'Untitled fragment','author':cached.get('author') if cached.get('version')==version else None})
        return out
    def snapshot(self,key,selection,studio):
        import secrets
        item=self.item(key);doc=item['doc'];plain=item.get('source_type') in ('l0','web');mode=selection.get('mode','whole');source={'type':item.get('source_type','l0') if plain else 'blyg','url':self.page_url(item),'title':doc.get('title') or '' if plain else '', 'author':doc.get('author'),'site':self.state['subscriptions'][item['subscription']]['title'],'date':doc.get('created')}
        if not plain:source.update(origin=item['origin'],id=doc['id'],version=doc['version'],kind=doc['kind'])
        body=self.rendered(key);text=None
        if selection.get('fingerprint') and selection['fingerprint']!=digest(json.dumps(doc,sort_keys=True)):
            raise ValueError('This source changed while it was open. Reopen it before quoting.')
        if mode=='fragment':
            fragment=next((f for f in self.source_fragments(key) if f['index']==selection.get('fragment')),None)
            if not fragment:raise ValueError('That source fragment is not available in the imported item.')
            source['site']=fragment['origin']
            source.update(origin=fragment['origin'],id=fragment['id'],version=fragment['version'],kind=fragment['kind'],title='',author=fragment['author'],url=fragment['origin']+('t/' if fragment['kind']=='thread' else 'f/')+fragment['id']+'/');body=fragment['html']
        elif mode=='excerpt':
            text=selection.get('text')
            if not isinstance(text,str) or not text.strip() or len(text)>200000:raise ValueError('Select text inside the opened item.')
            normalize=lambda value:re.sub(r'\s+',' ',value).strip()
            normalized_body=normalize(selection_text(body));exact=normalize(text);position=normalized_body.find(exact)
            if position<0:raise ValueError('The selection is outside this imported item.')
            if not plain:source['selector']={'exact':exact,'prefix':normalized_body[max(0,position-32):position],'suffix':normalized_body[position+len(exact):position+len(exact)+32]}
            body=''.join('<p>'+html.escape(p).replace('\n','<br>')+'</p>' for p in re.split(r'\n\s*\n',text))
        elif mode!='whole':raise ValueError('Unknown quotation selection.')
        # Copy only quoted media into the existing private authoring uploads area.
        assets=[]
        for name in set(item.get('assets',{}).values()):
            if '/reader-media/'+name not in body:continue
            path=self.asset_path(name)
            if not path.is_file():raise ValueError('Quoted media is missing from the cache.')
            atomic(studio.data/'uploads'/name,path.read_bytes());body=body.replace('/reader-media/'+name,studio.site+'blyg/media/'+name);assets.append(name)
        # Nested source metadata remains inside the snapshot, without private selectors.
        body=clean(body);author=source.get('author');name=author.get('name') if isinstance(author,dict) else None
        transclude=bool(selection.get('transclude'))
        label='by '+name if isinstance(name,str) and name.strip() else source['site']
        title=source.get('title') if mode=='whole' else ''
        if title:
            title_soup=BeautifulSoup(body,'html.parser');first=title_soup.find(['h1','h2','h3','h4','h5','h6'])
            if first and first.get_text(' ',strip=True)==title:first.decompose();body=str(title_soup)
        if transclude:
            heading='<h4 class="blynger-quote-title">'+html.escape(title)+'</h4>' if isinstance(title,str) and title else ''
            attribution='<p class="blynger-quote-author"><a href="'+html.escape(source['url'] or item['origin'],quote=True)+'">'+html.escape(label)+'</a>'
            if not plain:attribution+=' · quoted from v'+str(source['version'])
            attribution+='</p>'
        else:
            heading='';candidate=source.get('title') or (selection_text(body) if mode=='fragment' else self.display_title(item))
            candidate=re.sub(r'\s+',' ',candidate).strip();sentence=re.match(r'.+?(?:[.!?](?=\s|$)|$)',candidate)
            citation_title=((sentence.group(0) if sentence else candidate)[:140].strip() or 'Source')
            attribution='<p class="blynger-quote-author"><strong>From:</strong> <a href="'+html.escape(source['url'] or item['origin'],quote=True)+'">'+html.escape(citation_title)+'</a></p>'
        token='q'+secrets.token_hex(16)
        record={'type':mode,'source':source,'html':body,'text':text,'assets':assets,'at':self.clock(),'token':token}
        # Quote is the light, editable citation path. Only Stub explicitly asks
        # for a protocol transclusion; its protected source block is then
        # re-verified from this private snapshot at publication.
        if not transclude:
            quoted_body=BeautifulSoup(body,'html.parser')
            for nested in quoted_body.select('blockquote.blyg-transclusion'):
                nested['class']=[value for value in nested.get('class',[]) if value not in ('blyg-transclusion','blyg-partial')]
                for key in ('data-blyg-id','data-blyg-version','data-blyg-origin'):nested.attrs.pop(key,None)
            body=str(quoted_body)
        native=not plain and transclude and mode in ('whole','fragment')
        attrs=(' data-blyg-id="'+source['id']+'" data-blyg-version="'+str(source['version'])+'" data-blyg-origin="'+html.escape(source['origin'],quote=True)+'"') if native else ''
        visible='<blockquote class="blynger-citation'+(' blyg-transclusion' if native else '')+(' blyg-partial' if native and mode=='excerpt' else '')+'" data-blynger-quote="'+token+'"'+attrs+'>'+heading+attribution+body+'</blockquote>'
        record['visible_html']=visible
        cited={'source':source['site'],'author':name or source['site'],'excerpt':re.sub(r'\s+',' ',selection_text(body)).strip()[:200],'url':source['url'],'retrieved':self.clock()}
        target={'url':source['url'],'cited':cited} if plain else {'id':doc['id'],'version':doc['version'],'origin':item['origin'],'cited':cited}
        source_soup=BeautifulSoup(body,'html.parser')
        heading=source_soup.find(['h1','h2','h3','h4','h5','h6'])
        stub_title=source.get('title') or (heading.get_text(' ',strip=True) if heading else '')
        if not stub_title:
            plain_text=re.sub(r'\s+',' ',source_soup.get_text(' ',strip=True)).strip()
            sentence=re.match(r'.+?(?:[.!?](?=\s|$)|$)',plain_text)
            stub_title=(sentence.group(0) if sentence else plain_text)[:140].strip()
        stub_title=stub_title or self.display_title(item)
        stub_url=source.get('url') or item['origin']
        stub_label_html='<p class="blynger-stub-label"><strong>Stubbing:</strong> <a href="'+html.escape(stub_url,quote=True)+'">'+html.escape(stub_title)+'</a></p>'
        # Plain-web responses have no protocol identity to transclude. Blyg
        # targets use ``html`` and the private snapshot record instead.
        stub_html=stub_label_html+'<blockquote class="blynger-stub-context">'+body+'</blockquote>'
        return {'html':visible,'stub_html':stub_html,'stub_label_html':stub_label_html,'snapshot':record,'title':self.display_title(item),'origin':source.get('origin'),'id':source.get('id'),'version':source.get('version'),'stub_of':target}
