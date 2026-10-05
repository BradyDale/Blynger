"""Local authoring and static Blyg publication. No network on save."""
import base64, copy, hashlib, html, io, json, mimetypes, os, re, secrets, shlex, subprocess, tempfile
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup, Comment, NavigableString
from markdownify import markdownify
import bleach
from PIL import Image
from metadata import enrich, sitemap, discovery_markup, favicon_markup
from configuration import DEFAULT_SETTINGS
from version import APP_VERSION, BLYG_VERSION
import fragments as fragment_model
from conformance import validate_surface
from generation_disclosure import decorate as decorate_generation

NS='https://blygger.org/ns/0.1'
ET.register_namespace('blyg', NS)
ET.register_namespace('atom','http://www.w3.org/2005/Atom')
ET.register_namespace('dc','http://purl.org/dc/elements/1.1/')
TAGS=set(bleach.sanitizer.ALLOWED_TAGS)|{'p','div','span','br','hr','h1','h2','h3','h4','h5','h6','img','figure','figcaption','table','thead','tbody','tr','td','th','pre','code','audio','source','video','s','sub','sup','center','cite'}
ATTR={'*':['class','id','title'],'a':['href','title'],'img':['src','alt','width','height'],'audio':['src','controls'],'video':['src','controls','poster'],'source':['src','type'],'blockquote':['class','cite','data-blyg-id','data-blyg-version','data-blyg-origin','data-blynger-quote','data-source-origin','data-source-id','data-source-version']}
STYLE='<style id="blynger-generation-style">.blyg-tk-gen{position:relative;background:#f2f2f2;border:1px dashed #505050;margin:1em 0 1.4em;padding:.65em .8em 1.15em}.blyg-tk-gen::after{content:"";position:absolute;box-sizing:border-box;left:.65em;bottom:-14px;width:30px;height:27px;border:1px solid #444;background:#fff center/20px 20px no-repeat url("data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2224%22 height=%2224%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23111%22 stroke-width=%221.7%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22%3E%3Cpath d=%22M12 8V4H8%22/%3E%3Crect width=%2216%22 height=%2212%22 x=%224%22 y=%228%22 rx=%222%22/%3E%3Cpath d=%22M2 14h2M20 14h2M15 13v2M9 13v2%22/%3E%3C/svg%3E")}.blyg-tk-gen> :first-child{margin-top:0}.blyg-tk-gen> :last-child{margin-bottom:0}img{max-width:100%}</style>'

QUOTE_STYLE='<style id="blynger-quote-style">blockquote.blyg-transclusion,blockquote.blynger-citation{background:#eee;border:1px solid #ddd;margin:1em 0;padding:.75em 1em;overflow-wrap:anywhere}blockquote.blyg-transclusion> :first-child{margin-top:0}blockquote.blyg-transclusion> :last-child{margin-bottom:0}.blynger-quote-title{font-size:1em;margin:0 0 .35em}.blynger-quote-author{font-size:.85em;margin:0 0 1em}.blynger-blockquote-source{display:block;margin-top:.65em;text-align:right;font:13px/1.4 Tahoma,Verdana,sans-serif}</style>'

FRAGMENT_DOT_STYLE='<style id="blynger-fragment-dot-style">.blynger-fragment-marker{display:block;position:relative;height:0;margin:0;padding:0;border:0}.blynger-fragment-marker a{position:absolute;right:-17px;top:0;width:14px;height:14px;border:0;text-decoration:none!important;background:none;color:#90958b}.blynger-fragment-marker a::after{content:"";position:absolute;top:5px;left:5px;width:4px;height:4px;border-radius:50%;background:currentColor}.blynger-fragment-marker a:focus-visible{outline:1px dotted currentColor;outline-offset:2px}</style>'
IMAGE_STYLE='<style id="blynger-image-style">.blynger-image{text-align:center}.blynger-image img{display:block;height:auto;max-width:100%;margin-left:auto;margin-right:auto}.blynger-image-standard img{width:min(400px,77vw)}.blynger-image-small img{width:min(200px,50vw)}.blynger-image-wide img{width:77vw}.blynger-image-full img{width:100%}</style>'
def strip_fragment_markers(raw):
    raw=re.sub(r'<!-- blynger-fragment-link-start -->.*?<!-- blynger-fragment-link-end -->','',raw,flags=re.S)
    return re.sub(r'<style id="blynger-fragment-dot-style">.*?</style>','',raw,flags=re.S)

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def human_date(value=None):
    value=value or datetime.now()
    return value.strftime('%B ')+str(value.day)+value.strftime(', %Y')
def digest(data): return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()
def clean(text):
    soup=BeautifulSoup(text,'html.parser')
    for node in soup(['script','style','iframe','object','embed']): node.decompose()
    return bleach.clean(str(soup),tags=TAGS,attributes=ATTR,protocols={'http','https','mailto'},strip=True)

def normalize_authored_quotes(markup):
    """Use straight quotes in authored prose while leaving quoted sources exact."""
    if not any(char in markup for char in '“”‘’'):return markup
    soup=BeautifulSoup(markup,'html.parser')
    for node in list(soup.find_all(string=True)):
        if isinstance(node,Comment) or node.find_parent('blockquote'):continue
        value=str(node).translate(str.maketrans({'“':'"','”':'"','‘':"'",'’':"'"}))
        if value!=str(node):node.replace_with(NavigableString(value))
    return str(soup)
def uid():
    n=secrets.randbits(128); alphabet='0123456789abcdefghjkmnpqrstvwxyz'; out=''
    for _ in range(26): out=alphabet[n&31]+out; n>>=5
    return out

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp-'+secrets.token_hex(4))
    tmp.write_bytes(data if isinstance(data,bytes) else data.encode())
    os.replace(tmp,path)
def region(raw):
    for tag in ['article','body']:
        a=re.search(r'<'+tag+r'\b[^>]*>',raw,re.I)
        b=re.search(r'</'+tag+r'\s*>',raw[a.end():],re.I) if a else None
        if a and b: return a.end(),a.end()+b.start()
    return 0,len(raw)
def title_of(raw,name):
    soup=BeautifulSoup(raw,'html.parser'); node=soup.find('h1') or soup.title
    return node.get_text(' ',strip=True) if node else name

class FragmentFileConflict(ValueError):
    """A public file no longer matches the private fragment safety record."""
    code='fragment-file-conflict'
    def __init__(self,names,can_accept):
        self.files=list(names); self.can_accept=bool(can_accept)
        label=', '.join(self.files)
        if self.can_accept:
            message=label+' changed outside Blynger, but its writing and links are unchanged. You can use the current file as it is.'
        else:
            message=label+' changed outside Blynger, including its writing or links. Blynger will not guess how its private fragment identities should move.'
        super().__init__(message)

class FragmentStateError(ValueError):
    """Fragment metadata failed validation for one specific authoring page."""
    code='fragment-state'
    def __init__(self,page,problem):
        self.page=page
        super().__init__(str(problem))

def post_navigation(config=None):
    links=(config or DEFAULT_SETTINGS).get('navigation',[])
    return '<nav aria-label="Site navigation">'+''.join('<a href="'+item['url']+'"><img src="/images/'+item['image']+'" alt="'+html.escape(item['label'],quote=True)+'"></a>' for item in links)+'</nav>'

def restore_post_navigation(raw,name,config=None):
    # Recognize Blynger's article/nav template; leave hand-authored layouts alone.
    if name in set((config or DEFAULT_SETTINGS).get('main_pages',[])):return raw
    article=re.search(r'<article\b',raw,re.I)
    if not article:return raw
    top=next((m for m in re.finditer(r'<nav\b[^>]*>.*?</nav\s*>',raw[:article.start()],re.I|re.S) if '/images/home.JPG' in m.group()),None)
    if not top:return raw
    raw=raw[:top.start()]+post_navigation(config)+raw[top.end():]
    end=re.search(r'</article\s*>',raw,re.I)
    if end and '/images/home.JPG' not in raw[end.end():]:raw=raw[:end.end()]+post_navigation(config)+raw[end.end():]
    return raw

def new_page(title,body,config=None):
    return '<!doctype html>\n<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+html.escape(title)+'</title><style>body{font:125%/1.5 Menlo,monospace;margin:25px}article{max-width:768px;margin:auto}a{color:blue}img{max-width:100%}nav{text-align:center;margin:20px}nav img{width:18%;height:55px}</style>'+STYLE+'</head><body>'+post_navigation(config)+'<article><h1>'+html.escape(title)+'</h1>'+body+'</article>'+post_navigation(config)+'</body></html>'

class Studio:
    def __init__(self,root,data,config=None):
        self.root=Path(root).resolve(); self.data=Path(data).resolve(); self.data.mkdir(parents=True,exist_ok=True)
        self.apply_config(config or DEFAULT_SETTINGS)
        self.file=self.data/'state.json'
        pub=self.config['publishing']
        self.state=json.loads(self.file.read_text()) if self.file.exists() else {'drafts':{},'ids':{},'published':{},'pending':[], 'uploaded':[], 'remote':pub['remote'],'branch':pub['branch']}
        # Recover permanent identities from generated public files if local studio state is lost.
        for item in (self.root/'blyg/items').glob('*.json'):
            if item.name=='index.json': continue
            doc=json.loads(item.read_text()); name=urlsplit(doc.get('url','')).path.lstrip('/')
            if name and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.html',name): self.state['ids'].setdefault(name,doc['id'])
        self.state.setdefault('history',{})
        self.state.setdefault('pins',{})
        self.state.setdefault('fragment_posts',{})
        self.state.setdefault('fragment_ids',{})
        self.state.setdefault('fragment_history',{})
        self.state.setdefault('deleted_posts',{})
        self.state.setdefault('standalone_pages',[])
        self.state.setdefault('item_titles',{})
        self.state.setdefault('site_feed_titles',{})
        # Pages are not fragment-bearing authoring objects. Older builds could
        # leave a block map on a main or standalone Page; remove only that
        # impossible metadata while preserving the page, drafts, and published
        # Blyg history. Openers are the intentional exception.
        for records in (self.state['drafts'],self.state['fragment_posts']):
            for name,source in records.items():
                if not self.fragment_capable(name) and isinstance(source,dict):
                    source['fragments']=None
        for doc in self.state['published'].values():
            if isinstance(doc.get('title'),str) and doc['title'].strip():
                self.state['item_titles'].setdefault(doc['id'],doc['title'].strip())
                if doc.get('version')==1:self.state['site_feed_titles'].setdefault(doc['id'],doc['title'].strip())
        for iid,versions in self.state['history'].items():
            first=versions.get('1',{})
            if isinstance(first.get('title'),str) and first['title'].strip():self.state['site_feed_titles'].setdefault(iid,first['title'].strip())
        # Older exports used an absolute, non-protocol `url` member. Keep its
        # page-to-id recovery locally while the public item shape moves to 0.3.
        for page in self.root.glob('*.html'):
            try:soup=BeautifulSoup(page.read_text(),'html.parser')
            except UnicodeDecodeError:continue
            link=soup.find('link',rel=lambda value:value and 'alternate' in value,type='application/json')
            match=re.search(r'/blyg/items/([0-7][0-9a-hjkmnp-tv-z]{25})\.json$',link.get('href','')) if link else None
            if match:self.state['ids'].setdefault(page.name,match.group(1))
        excluded_ids={self.state['ids'][name] for name in self.non_blyg_pages|set(self.state['standalone_pages']) if name in self.state['ids']}
        for iid in excluded_ids:self.state['published'].pop(iid,None)
        self.remember(self.state['published'])
        opener_source=self.state['drafts'].get('openers.html') or self.state['fragment_posts'].get('openers.html',{})
        self.baseline_opener_feed(opener_source.get('fragments'))
        self.save_state()
        from reader import Reader
        self.reader=Reader(self.data,own_origin=self.origin)
        self.reader.backfill_publications(self.state['history'])
        self.configure_remote()

    def apply_config(self,config):
        self.config=copy.deepcopy(config); self.site=self.config['site_url'].rstrip('/')+'/'; self.origin=self.site+'blyg/'
        self.author=self.config['author_name']; self.signature=self.config['author_signature']
        self.main_pages=set(self.config.get('main_pages',[])); self.non_blyg_pages=set(self.config.get('non_blyg_pages',[]))
        if hasattr(self,'state'):
            self.state['remote']=self.config['publishing']['remote']; self.state['branch']=self.config['publishing']['branch']
            if hasattr(self,'reader'): self.reader.own_origin=self.origin
            self.configure_remote(); self.save_state()

    def fragment_capable(self,name):
        return name=='openers.html' or (name not in self.non_blyg_pages and name not in set(self.state.get('standalone_pages',[])))

    def validate_fragments(self,name,meta,body):
        if not self.fragment_capable(name):return None
        try:return fragment_model.validate(meta,body)
        except ValueError as problem:raise FragmentStateError(name,problem) from problem

    def configure_remote(self):
        pub=self.config['publishing']
        if not all(pub.get(k) for k in ('remote','ssh_user','hostname','remote_path')) or not (self.root/'.git').exists(): return
        url='ssh://'+pub['ssh_user']+'@'+pub['hostname']+pub['remote_path']
        names=subprocess.run(['git','remote'],cwd=self.root,capture_output=True,text=True).stdout.split()
        if pub['remote'] in names:
            current=subprocess.run(['git','remote','get-url',pub['remote']],cwd=self.root,capture_output=True,text=True).stdout.strip()
            if current==url:return
        self.git('remote','set-url' if pub['remote'] in names else 'add',pub['remote'],url)
    def baseline_opener_feed(self,meta):
        # A one-time private boundary keeps the imported archive out of RSS.
        if meta and meta.get('purpose')=='openers' and 'opener_rss_legacy_keys' not in self.state:
            self.state['opener_rss_legacy_keys']=[r['key'] for r in meta['ranges']]
    def save_state(self): atomic(self.file,json.dumps(self.state,ensure_ascii=False,indent=2))
    def path(self,name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.html',name): raise ValueError('Choose an HTML page from this site.')
        p=(self.root/name).resolve()
        if p.parent!=self.root or p.is_symlink(): raise ValueError('Invalid page path.')
        return p
    def read(self,name): return self.path(name).read_bytes().decode('utf-8')
    def pages(self):
        names={p.name for p in self.root.glob('*.html')}|set(self.state['drafts'])|set(self.state['deleted_posts'])
        priority={'index.html':0,'portfolio.html':1,'openers.html':2,'privacypolicy.html':3}
        out=[]
        for name in sorted(names,key=lambda n:(priority.get(n,4 if n in self.state['standalone_pages'] else 5),n)):
            if name=='template.html': continue
            draft=self.state['drafts'].get(name)
            deleted=self.state['deleted_posts'].get(name,{})
            published=self.state.get('published',{}).get(self.state.get('ids',{}).get(name),{})
            path=self.path(name)
            fallback=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z') if path.exists() else now()
            created=published.get('created') or (draft or {}).get('at') or fallback
            updated=(draft or {}).get('updated') or published.get('updated') or fallback
            if deleted.get('active'):
                out.append({'name':name,'title':deleted['page']['title'],'draft':bool(draft),'main':False,'kind':'post','deleted':True,'created':created,'updated':updated});continue
            try: raw=draft['raw'] if draft else self.read(name)
            except UnicodeDecodeError: continue  # Signed binary artifact, not editable HTML.
            kind='main' if name in priority else 'page' if name in self.state['standalone_pages'] else 'post'
            out.append({'name':name,'title':title_of(raw,name),'draft':bool(draft),'main':name in priority,'kind':kind,'created':created,'updated':updated})
        return out
    def migrate_openers(self):
        """Add private fragment designations, preserving the public page byte-for-byte."""
        name='openers.html'; p=self.path(name)
        if not p.exists(): return {'count':0,'changed':False}
        draft=self.state['drafts'].get(name)
        saved=self.state.get('fragment_posts',{}).get(name)
        source=draft or saved
        if source and source.get('fragments',{} ) and source['fragments'].get('purpose')=='openers':
            return {'count':len(source['fragments']['ranges']),'changed':False}
        backup=self.data/'migrations/openers-fragments-v1.json'
        if not backup.exists(): atomic(backup,json.dumps(self.state,ensure_ascii=False,indent=2))
        raw=(source or {}).get('raw') or self.read(name)
        raw=strip_fragment_markers(raw)
        raw=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',raw,flags=re.S)
        a,b=region(raw)
        meta=fragment_model.openers_metadata(clean(raw[a:b]),(source or {}).get('fragments'))
        self.baseline_opener_feed(meta)
        if draft: draft['fragments']=meta
        else:
            self.state['fragment_posts'][name]={**(saved or {}),'raw':raw,'fragments':meta,'generated':(saved or {}).get('generated',[]),'file_hash':digest(p.read_bytes())}
        self.save_state()
        return {'count':len(meta['ranges']),'changed':True}
    def fragment_objects(self,name):
        """Shared PRIVATE reusable objects. Draft references are (page, key), not public IDs."""
        self.path(name)
        source=self.state['drafts'].get(name) or self.state.get('fragment_posts',{}).get(name,{})
        meta=source.get('fragments')
        if not meta: return []
        identities=self.state['fragment_ids'].get(name,{})
        result=[]
        for r,a,b,body in fragment_model.ranges(meta):
            iid=identities.get(r['key']); published=self.state['published'].get(iid)
            result.append({'reference':{'page':name,'key':r['key']},'kind':published.get('kind','fragment') if published else ('thread' if r.get('stub_of') else 'fragment'),'html':body,'date_label':r.get('date_label'),'legacy_anchor':r.get('legacy_anchor'),'id':iid if published else None,'version':published['version'] if published else None,'published':bool(published),'url':self.permalink(published) if published else None})
        return result
    def fragment_file_conflicts(self):
        conflicts=[]
        for name,saved in self.state.get('fragment_posts',{}).items():
            p=self.path(name)
            if name not in self.state['drafts'] and p.exists() and saved.get('file_hash')!=digest(p.read_bytes()):
                conflicts.append(name)
        return sorted(conflicts)
    def fragment_file_signature(self,raw):
        """Compare visible authored structure while ignoring private/public Blyg bookkeeping."""
        raw=strip_fragment_markers(raw)
        raw=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',raw,flags=re.S)
        a,b=region(raw); soup=BeautifulSoup(raw[a:b],'html.parser')
        # A published local quotation contains the quoted snapshot; its private
        # authoring source contains only the stable directive.
        for quote in soup.select('blockquote.blyg-transclusion[data-blyg-id]'):
            if 'blynger-citation' in quote.get('class',[]) or quote.find_parent('blockquote',class_='blynger-citation'): continue
            node=soup.new_tag('p'); node.string='![['+quote['data-blyg-id']+']]'; quote.replace_with(node)
        ignored={'data-blynger-quote','data-source-origin','data-source-id','data-source-version','data-blyg-id','data-blyg-origin','data-blyg-version'}
        def signature(node):
            if isinstance(node,Comment): return None
            if isinstance(node,NavigableString):
                text=re.sub(r'\s+',' ',str(node))
                return ('text',text) if text.strip() else None
            attrs=[]
            for key,value in node.attrs.items():
                if key in ignored: continue
                if isinstance(value,list): value=tuple(value)
                attrs.append((key,value))
            children=tuple(part for child in node.children if (part:=signature(child)) is not None)
            return ('tag',node.name,tuple(sorted(attrs)),children)
        return tuple(part for child in soup.contents if (part:=signature(child)) is not None)
    def can_accept_fragment_file(self,name):
        saved=self.state.get('fragment_posts',{}).get(name); p=self.path(name)
        if not saved or name in self.state['drafts'] or not p.exists(): return False
        try:
            actual=p.read_bytes().decode('utf-8')
            return self.fragment_file_signature(saved['raw'])==self.fragment_file_signature(actual)
        except (UnicodeDecodeError,KeyError,TypeError): return False
    def accept_fragment_files(self,names):
        if not isinstance(names,list) or not names or len(names)>100 or any(not isinstance(n,str) for n in names):
            raise ValueError('Choose the changed pages to keep.')
        names=list(dict.fromkeys(names)); conflicts=set(self.fragment_file_conflicts())
        if any(name not in conflicts for name in names): raise ValueError('One of those pages no longer needs reconciliation. Review again.')
        unsafe=[name for name in names if not self.can_accept_fragment_file(name)]
        if unsafe: raise FragmentFileConflict(unsafe,False)
        for name in names:
            current_bytes=self.path(name).read_bytes(); current=current_bytes.decode('utf-8')
            current=strip_fragment_markers(current)
            current=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',current,flags=re.S)
            saved=self.state['fragment_posts'][name]; saved_start,saved_end=region(saved['raw'])
            current_start,current_end=region(current)
            # The signature check proves the authored regions are equivalent. Keep
            # the private fragment-aware body, but make accepted surrounding HTML
            # the durable source for later edits instead of merely blessing its hash.
            saved['raw']=current[:current_start]+saved['raw'][saved_start:saved_end]+current[current_end:]
            saved['file_hash']=digest(current_bytes)
        self.save_state()
        return {'message':'Kept the current '+('files' if len(names)>1 else 'file')+' and preserved its private fragment identities.','files':names}
    def require_current_fragment_files(self):
        names=self.fragment_file_conflicts()
        if names: raise FragmentFileConflict(names,all(self.can_accept_fragment_file(name) for name in names))
    def page(self,name):
        if name=='openers.html': self.migrate_openers()
        p=self.path(name); draft=self.state['drafts'].get(name)
        deleted=self.state['deleted_posts'].get(name,{})
        if deleted.get('active'):
            d=copy.deepcopy(deleted['page']);d.update(deleted=True,draft=bool(draft),body='<p>This post is in Deleted posts. Restore it to edit.</p>');return d
        saved=self.state.get('fragment_posts',{}).get(name)
        if not draft and saved and saved.get('file_hash')!=digest(p.read_bytes()):
            raise FragmentFileConflict([name],self.can_accept_fragment_file(name))
        raw=draft['raw'] if draft else saved['raw'] if saved else self.read(name)
        raw=strip_fragment_markers(raw)
        raw=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',raw,flags=re.S)
        soup=BeautifulSoup(raw,'html.parser')
        for quote in soup.select('blockquote.blyg-transclusion[data-blyg-id]'):
            if 'blynger-citation' in quote.get('class',[]) or quote.find_parent('blockquote',class_='blynger-citation'):continue
            node=soup.new_tag('p'); node.string='![['+quote['data-blyg-id']+']]'; quote.replace_with(node)
        if 'blyg-transclusion' in raw: raw=str(soup)
        a,b=region(raw)
        kind='page' if name in self.state['standalone_pages'] else 'main' if name in self.non_blyg_pages else 'post'
        iid=self.state['ids'].get(name)
        # A pin is a choice about the version being prepared, not just version
        # one. Keep the control available whenever a Post is editable so a
        # later revision can be made permanent too.
        pin_available=bool(name!='openers.html' and kind=='post')
        return {'name':name,'title':title_of(raw,name),'raw':raw,'body':clean(raw[a:b]),'start':a,'end':b,'prefix':raw[:a],'suffix':raw[b:],'base':draft['base'] if draft else digest(p.read_bytes()),'draft':bool(draft),'new':draft.get('new',False) if draft else False,'kind':kind,'note':draft.get('note','') if draft else '', 'fragments':self.validate_fragments(name,(draft or saved or {}).get('fragments'),clean(raw[a:b])), 'generated':copy.deepcopy((draft or saved or {}).get('generated',[])), 'quotes':copy.deepcopy((draft or saved or {}).get('quotes',{})), 'stub_of':copy.deepcopy((draft or saved or {}).get('stub_of')), 'forked_from':copy.deepcopy((draft or saved or {}).get('forked_from')), 'pin_available':pin_available, 'pin_on_publish':bool((draft or {}).get('pin_on_publish',False))}
    def protect_quote_snapshots(self,raw,quotes):
        """Restore atomic source blocks from private records; whole-block deletion wins."""
        if not quotes:return raw
        soup=BeautifulSoup(raw,'html.parser');changed=False
        for block in list(soup.select('blockquote[data-blynger-quote]')):
            record=quotes.get(block.get('data-blynger-quote'))
            if not isinstance(record,dict) or not isinstance(record.get('visible_html'),str):continue
            replacement=BeautifulSoup(record['visible_html'],'html.parser').find('blockquote')
            if replacement is not None:block.replace_with(replacement);changed=True
        return str(soup) if changed else raw
    def upgrade_stub_context(self,raw,target,quotes):
        """Turn the obsolete editable context of a Blyg stub into its exact snapshot."""
        if not isinstance(target,dict) or not {'origin','id','version'}<=set(target):return raw
        soup=BeautifulSoup(raw,'html.parser');legacy=soup.select_one('blockquote.blynger-stub-context')
        if legacy is None:return raw
        key=self.reader.key(target['origin'],target['id'])
        try:item=self.reader.item(key)
        except (KeyError,ValueError):raise ValueError('This Blyg Stub still has editable copied context, but its source snapshot is unavailable. Refresh the source in Reader before saving.')
        if item['doc'].get('version')!=target['version']:
            raise ValueError('This Blyg Stub still has editable copied context, but Reader no longer has the exact source version. Reopen that version before saving.')
        quoted=self.reader.snapshot(key,{'mode':'whole'},self);record=quoted['snapshot']
        legacy.replace_with(BeautifulSoup(quoted['html'],'html.parser'))
        quotes[record['token']]=record
        return str(soup)
    def upgrade_opener_stub_contexts(self,raw,meta,previous,quotes):
        """Upgrade genuine Stub blocks without assuming block-map bytes equal page bytes."""
        if not isinstance(meta,dict):return raw
        prior={row.get('key'):body for row,start,end,body in fragment_model.ranges(previous)} if isinstance(previous,dict) else {}
        rows=[]
        for opener,start,end,body in fragment_model.ranges(meta):
            if BeautifulSoup(body,'html.parser').select_one('blockquote.blynger-stub-context'):
                old=prior.get(opener.get('key'),'')
                untouched=bool(BeautifulSoup(old,'html.parser').select_one('blockquote.blynger-stub-context'))
                rows.append((opener.get('stub_of'),not untouched))
        pattern=re.compile(r'<blockquote\b(?=[^>]*class=["\'][^"\']*\bblynger-stub-context\b)[^>]*>.*?</blockquote\s*>',re.I|re.S)
        matches=list(pattern.finditer(raw))
        if len(matches)!=len(rows):
            raise ValueError('Openers Stub layout is inconsistent. Reopen the draft before saving.')
        pieces=[];position=0
        for match,(target,upgrade) in zip(matches,rows):
            pieces.append(raw[position:match.start()])
            upgraded=self.upgrade_stub_context(match.group(),target,quotes) if upgrade else match.group()
            block=BeautifulSoup(upgraded,'html.parser').find('blockquote')
            pieces.append(str(block) if block is not None else match.group())
            position=match.end()
        pieces.append(raw[position:])
        return ''.join(pieces)
    def save_draft(self,d):
        name=d['name']
        if self.state['deleted_posts'].get(name,{}).get('active'):raise ValueError('Restore this deleted post before editing it.')
        p=self.path(name); existing=self.state['drafts'].get(name)
        actual=digest(p.read_bytes()) if p.exists() else None
        if d.get('base')!=actual: raise ValueError('This page changed outside Blynger. Reopen it before saving so those changes are preserved.')
        if not isinstance(d.get('raw'),str) or len(d['raw'])>3000000: raise ValueError('Page content is missing or too large.')
        quotes=copy.deepcopy(d.get('quotes',existing.get('quotes',{}) if existing else {}))
        d['raw']=self.protect_quote_snapshots(d['raw'],quotes)
        a,b=region(d['raw'])
        previous=existing or self.state.get('fragment_posts',{}).get(name,{})
        if name!='openers.html':
            target=d.get('stub_of',previous.get('stub_of'))
            d['raw']=self.upgrade_stub_context(d['raw'],target,quotes);a,b=region(d['raw'])
        if not (d.get('forked_from') or previous.get('forked_from') or d.get('preserve_authored_typography')):
            body=normalize_authored_quotes(d['raw'][a:b]);d['raw']=d['raw'][:a]+body+d['raw'][b:];a,b=region(d['raw'])
        # Clearing fragments is an explicit destructive choice in the editor.
        # Do not allow an older fragment-aware source to fill them back in when
        # handling a recovery save.
        clear_fragments=d.get('clear_fragments') is True
        meta=None if clear_fragments or not self.fragment_capable(name) else copy.deepcopy(d.get('fragments',previous.get('fragments')))
        if isinstance(meta,dict) and isinstance(meta.get('blocks'),list):
            for block in meta['blocks']:
                if isinstance(block,dict) and isinstance(block.get('html'),str):
                    block['html']=clean(block['html'])
                    if not (d.get('forked_from') or previous.get('forked_from') or d.get('preserve_authored_typography')):block['html']=normalize_authored_quotes(block['html'])
            # Dividers are private editor guides. If a browser paragraph merge
            # removes their block, never let the invisible guide trap a draft.
            meta=fragment_model.repair_editor_anchors(meta)
        if name=='openers.html':
            # Older UI code inserted copied editable context even for genuine
            # Blyg targets. Upgrade each such Opener from its exact Reader
            # snapshot before rebuilding the block map.
            submitted=copy.deepcopy(meta);submitted_stubs=[]
            if isinstance(submitted,dict):
                submitted_stubs=[copy.deepcopy(row.get('stub_of')) for row in submitted.get('ranges',[])]
                d['raw']=self.upgrade_opener_stub_contexts(d['raw'],submitted,previous.get('fragments'),quotes)
                a,b=region(d['raw'])
            meta=fragment_model.openers_metadata(clean(d['raw'][a:b]),previous.get('fragments'),meta)
            for index,target in enumerate(submitted_stubs):
                if target is not None and index<len(meta.get('ranges',[])):meta['ranges'][index]['stub_of']=target
            prior={r['key']:r for r in (previous.get('fragments') or {}).get('ranges',[]) if isinstance(r,dict) and isinstance(r.get('key'),str)}
            for opener in meta.get('ranges',[]):
                old_stub=prior.get(opener['key'],{}).get('stub_of');new_stub=opener.get('stub_of')
                if old_stub is not None and new_stub!=old_stub:raise ValueError('Stub target cannot be changed after this Opener is created.')
                if new_stub is not None:
                    if not isinstance(new_stub,dict):raise ValueError('An Opener response lost its source identity.')
                    if set(new_stub)=={'url'}:
                        if not isinstance(new_stub['url'],str) or urlsplit(new_stub['url']).scheme not in ('http','https'):raise ValueError('An Opener response needs one public source URL.')
                    elif not {'origin','id','version'}<=set(new_stub) or set(new_stub)-{'origin','id','version','cited'}:
                        raise ValueError('An Opener response lost its Blyg source identity.')
        meta=self.validate_fragments(name,meta,clean(d['raw'][a:b]))
        lineage={}
        for field in ('stub_of','forked_from'):
            prior=(existing or previous).get(field);supplied=d.get(field,prior)
            if prior is not None and supplied!=prior:raise ValueError(field.replace('_',' ').title()+' cannot be changed after this draft is created.')
            if supplied is not None:lineage[field]=copy.deepcopy(supplied)
        self.state['drafts'][name]={'raw':d['raw'],'base':actual,'new':existing.get('new',False) if existing else False,'kind':'page' if name in self.state['standalone_pages'] else 'post','at':existing.get('at',now()) if existing else now(),'updated':now(),'generated':d.get('generated',existing.get('generated',[]) if existing else []),'note':d.get('note',existing.get('note','') if existing else ''),'revision':existing.get('revision',False) if existing else False}
        self.state['drafts'][name]['fragments']=meta
        self.state['drafts'][name]['quotes']=quotes
        if name!='openers.html' and self.fragment_capable(name):
            self.state['drafts'][name]['pin_on_publish']=bool(d.get('pin_on_publish',existing.get('pin_on_publish',False) if existing else False))
        self.state['drafts'][name].update(lineage)
        if (existing or previous).get('blogroll_snapshot') is not None:self.state['drafts'][name]['blogroll_snapshot']=copy.deepcopy((existing or previous)['blogroll_snapshot'])
        self.save_state(); return {'message':'Draft saved on this Mac. The website has not changed.'}
    def discard(self,name):
        self.path(name)
        if self.state['deleted_posts'].get(name,{}).get('active'):raise ValueError('Use Restore post to undo a deletion.')
        draft=self.state['drafts'].pop(name,None)
        if draft and draft.get('new') and name in self.state['standalone_pages'] and not self.path(name).exists():self.state['standalone_pages'].remove(name)
        self.save_state()
        return {'message':'Draft discarded. The site file is unchanged.'}
    def delete_post(self,name):
        if name in ('index.html','portfolio.html','openers.html','privacypolicy.html','template.html'):raise ValueError('Main pages cannot be deleted here.')
        self.path(name)
        if self.state['deleted_posts'].get(name,{}).get('active'):return {'message':'Post is already deleted locally.'}
        page=self.page(name);iid=self.state['ids'].get(name);published=self.state['published'].get(iid)
        backup={'active':True,'page':copy.deepcopy(page),'published':copy.deepcopy(published),'draft':copy.deepcopy(self.state['drafts'].get(name)),'source':copy.deepcopy(self.state['fragment_posts'].get(name)),'at':now()}
        self.state['deleted_posts'][name]=backup
        self.state['fragment_posts'].pop(name,None)
        if published or self.path(name).exists():
            self.state['drafts'][name]={'raw':new_page('Post removed','<p>This post has been removed by its author.</p>',self.config),'base':digest(self.path(name).read_bytes()) if self.path(name).exists() else None,'new':False,'at':now(),'generated':[],'fragments':None,'note':'Post withdrawn by author','revision':True}
        else:self.state['drafts'].pop(name,None)
        self.save_state();return {'message':'Post moved to Deleted posts. Publish to withdraw it from the website; Restore post recovers your writing.'}
    def restore_post(self,name):
        self.path(name);backup=self.state['deleted_posts'].get(name)
        if not backup or not backup.get('active'):raise ValueError('This post is not deleted.')
        backup['active']=False;p=self.path(name);page=copy.deepcopy(backup['page']);page['base']=digest(p.read_bytes()) if p.exists() else None
        self.save_draft(page);self.state['drafts'][name].update(new=not bool(self.state['published'].get(self.state['ids'].get(name))),note='Restore deleted post',revision=True,restore_home=True)
        self.save_state();return {'message':'Post restored as a local draft. Publish to return it to the website.'}
    def create(self,title,body=None,stub_of=None,forked_from=None):
        title=title.strip()
        if not title: raise ValueError('Give the post a title.')
        # Standalone Pages may intentionally use year-like filenames (for
        # example 2018.html), but they are not part of the post sequence.
        names=({p.name for p in self.root.glob('*.html')} | set(self.state['drafts']) | set(self.state['ids']) | set(self.state['deleted_posts']))-set(self.state['standalone_pages'])
        numbers=[int(name[:-5]) for name in names if re.fullmatch(r'[0-9]+\.html',name)]
        name=str(max(numbers,default=0)+1)+'.html'
        authored=body if isinstance(body,str) else '<p>Start writing here.</p>'
        raw=new_page(title,authored+'<p>'+html.escape(self.signature)+'<br>'+human_date()+'</p>',self.config)
        raw=enrich(raw,name,self.root,published=now(),config=self.config,blyg_item=True,blyg_discovery=True,rss_discovery=True)
        self.state['drafts'][name]={'raw':raw,'base':None,'new':True,'at':now(),'generated':[],'pin_on_publish':False}
        if stub_of is not None:self.state['drafts'][name]['stub_of']=copy.deepcopy(stub_of)
        if forked_from is not None:self.state['drafts'][name]['forked_from']=copy.deepcopy(forked_from)
        self.save_state(); return self.page(name)
    def create_page(self,title,name):
        title=title.strip() if isinstance(title,str) else ''
        name=name.strip() if isinstance(name,str) else ''
        if not title: raise ValueError('Give the page a title.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*\.html',name) or name=='template.html' or re.fullmatch(r'[0-9]+\.html',name):
            raise ValueError('Use a descriptive HTML filename such as year-2018.html. Numbered filenames are reserved for Posts.')
        reserved={p.name for p in self.root.glob('*.html')}|set(self.state['drafts'])|set(self.state['ids'])|set(self.state['deleted_posts'])
        if name in reserved: raise ValueError(name+' already exists. Choose a different filename so nothing is overwritten.')
        raw=enrich(new_page(title,'<p>Start writing here.</p>',self.config),name,self.root,standalone=True,config=self.config)
        self.state['standalone_pages'].append(name)
        self.state['drafts'][name]={'raw':raw,'base':None,'new':True,'kind':'page','at':now(),'generated':[],'fragments':None,'quotes':{}}
        self.save_state(); return self.page(name)
    def remember(self,docs):
        for iid,doc in docs.items():
            history=self.state['history'].setdefault(iid,{})
            key=str(doc['version'])
            if key in history and history[key]['content_hash']!=doc['content_hash']:
                raise ValueError('Published version conflicts with the private archive.')
            history.setdefault(key,copy.deepcopy(doc))
    def versions(self,name):
        self.path(name); iid=self.state['ids'].get(name); current=self.state['published'].get(iid)
        history=self.state['history'].get(iid,{})
        return {'current':current['version'] if current else None,'versions':[{'version':d['version'],'at':d['updated'],'note':d['changelog'][-1].get('note'),'html':d['content_html'],'pinned':any(c['version']==d['version'] and c.get('pinned') for c in (current or {}).get('changelog',[])), 'queued':str(d['version']) in self.state['pins'].get(iid,[])} for d in sorted(history.values(),key=lambda d:d['version'],reverse=True)]}
    def revise(self,name,note,version=None):
        if not isinstance(note,str) or not note.strip() or len(note)>1000: raise ValueError('Add a short change note (up to 1,000 characters).')
        d=self.page(name)
        if version is not None:
            iid=self.state['ids'].get(name); doc=self.state['history'].get(iid,{}).get(str(int(version)))
            if not doc: raise ValueError('That historical version is not available on this Mac.')
            a,b=region(d['raw']); d['raw']=d['raw'][:a]+doc['content_html']+d['raw'][b:]
            archived=self.state.get('fragment_history',{}).get(iid,{}).get(str(int(version)))
            if archived:
                d['raw']=archived['raw']; d['fragments']=copy.deepcopy(archived['fragments']);d['quotes']=copy.deepcopy(archived.get('quotes',{}))
            else: d['fragments']=None;d['quotes']={}
            d['generated']=copy.deepcopy(doc.get('generated',[]))
        d['note']=note.strip(); self.save_draft(d); self.state['drafts'][name]['revision']=True; self.save_state()
        return self.page(name)
    def pin(self,name,version):
        self.path(name); iid=self.state['ids'].get(name); key=str(int(version))
        doc=self.state['history'].get(iid,{}).get(key)
        if not doc or doc['kind']=='withdrawn': raise ValueError('Only an available published version with content can be pinned.')
        pins=self.state['pins'].setdefault(iid,[])
        if key not in pins: pins.append(key)
        self.save_state(); return {'message':'Pin queued. Review and publish to make this version permanently public.'}
    def fragments(self):
        return [{'id':d['id'],'title':self.item_title(d),'version':d['version']} for d in self.state['published'].values() if d['kind']=='fragment']
    def quote_choices(self):
        local=[{'id':d['id'],'title':self.item_title(d),'version':d['version'],'kind':d['kind'],'origin':self.origin,'source':'local'} for d in self.state['published'].values() if d['kind'] in ('fragment','thread')]
        remote=[{**d,'source':'remote'} for d in self.reader.listing()]
        return local+remote
    def quote_item(self,source,key,selection=None):
        if source=='remote':return self.reader.snapshot(key,selection,self) if selection is not None else self.reader.quote(key,self)
        doc=self.state['published'].get(key)
        if not doc or doc['kind'] not in ('fragment','thread'):raise ValueError('This item is not available to quote.')
        return {'html':'<p>![['+key+']]</p>','id':key,'origin':self.origin,'version':doc['version'],'kind':doc['kind'],'title':self.item_title(doc),'stub_of':{'id':key,'version':doc['version'],'origin':self.origin}}
    def quote_source(self,iid,own_id,docs,files,origin=None):
        source=None if origin and origin!=self.origin else docs.get(iid) if iid not in self.state['ids'].values() else self.state['published'].get(iid)
        if source:
            if source['kind'] not in ('fragment','thread'):raise ValueError('The quoted local item is unavailable.')
            def reaches(target,seen):
                if target==own_id:return True
                if target in seen:return False
                seen.add(target)
                return any(reaches(ref['id'],seen) for ref in self.state['published'].get(target,{}).get('transclusions',[]) if not ref.get('origin'))
            if reaches(iid,set()):raise ValueError('A post cannot quote itself or a local thread that quotes it.')
            return source['content_html'],{'id':iid,'version':source['version']}
        found=[i for i in self.reader.state['items'].values() if i['doc'].get('id')==iid and (origin is None or i['origin']==origin)]
        if len(found)>1:raise ValueError('Ambiguous quote: this ID was imported from multiple origins.')
        if not found:raise ValueError('Quoted item is not cached or was withdrawn. Sync its Blyg or remove the quote before publishing.')
        item=found[0];source=item['doc']
        body=self.reader.rendered(item['key'],self.site+'blyg/media/')
        for asset in set(item['assets'].values()):
            path=self.reader.asset_path(asset)
            if not path.is_file():raise ValueError('Quoted media is missing from the reader cache. Sync its Blyg again.')
            files['blyg/media/'+asset]=path.read_bytes()
        return body,{'id':iid,'version':source['version'],'origin':item['origin']}
    def link_source(self,iid,docs):
        source=docs.get(iid) or self.state['published'].get(iid)
        if source and source.get('kind') in ('fragment','thread'):
            return self.permalink(source),self.item_title(source)
        found=[item for item in self.reader.state['items'].values() if item.get('source_type','blyg')=='blyg' and item.get('doc',{}).get('id')==iid]
        if len(found)>1:raise ValueError('Ambiguous link: this ID was imported from multiple origins.')
        if not found:raise ValueError('Linked item is not published or cached. Publish or sync it before using its ID.')
        item=found[0];text=BeautifulSoup(item['doc'].get('content_html',''),'html.parser').get_text(' ',strip=True)
        return self.reader.page_url(item),text[:100] or iid
    def resolve_internal_links(self,soup,docs):
        pattern=re.compile(r'(?<!!)\[\[([0-7][0-9a-hjkmnp-tv-z]{25})\]\]')
        for node in list(soup.find_all(string=pattern)):
            if node.find_parent(['pre','code']) or node.find_parent('blockquote',class_=lambda value:value and ('blyg-transclusion' in value or 'blynger-citation' in value)):continue
            value=str(node);cursor=0;parts=[]
            for match in pattern.finditer(value):
                if match.start()>cursor:parts.append(NavigableString(value[cursor:match.start()]))
                target,label=self.link_source(match.group(1),docs);link=soup.new_tag('a',href=target);link.string=label;parts.append(link);cursor=match.end()
            if cursor<len(value):parts.append(NavigableString(value[cursor:]))
            for part in parts:node.insert_before(part)
            node.extract()
        return soup
    def item_title(self,doc):
        title=self.state.get('item_titles',{}).get(doc['id'])
        if isinstance(title,str) and title.strip():return title.strip()
        text=BeautifulSoup(doc.get('content_html',''),'html.parser').get_text(' ',strip=True)
        return text[:100] or doc['id']
    def item_kind_path(self,doc):
        return 't' if doc.get('kind')=='thread' or (doc.get('kind')=='withdrawn' and 'transclusions' in doc) else 'f'
    def normalize_item(self,doc):
        if isinstance(doc.get('title'),str) and doc['title'].strip():self.state['item_titles'].setdefault(doc['id'],doc['title'].strip())
        doc.pop('title',None);doc.pop('url',None)
        doc['page']=doc.get('page') or self.item_kind_path(doc)+'/'+doc['id']+'/'
        return doc
    def normalize_partial_quotes(self,doc,stamp):
        partial=[ref for ref in doc.get('transclusions',[]) if isinstance(ref,dict) and 'selector' in ref]
        if not partial:return doc
        stamp=self.state.setdefault('blyg_03_migration_at',stamp)
        soup=BeautifulSoup(doc['content_html'],'html.parser');md=doc['content_md']
        for ref in partial:
            query='blockquote.blyg-partial[data-blyg-id="'+ref['id']+'"]'
            node=soup.select_one(query)
            if node:
                node['class']=[value for value in node.get('class',[]) if value!='blyg-transclusion']
                for key in ('data-blyg-id','data-blyg-version','data-blyg-origin'):node.attrs.pop(key,None)
            md=re.sub(r'^\s*!\[\['+re.escape(ref['id'])+r'\]\]\s*\n?','',md,count=1,flags=re.M)
        doc['transclusions']=[ref for ref in doc.get('transclusions',[]) if ref not in partial]
        doc['content_html']=str(soup);doc['content_md']=md.strip();doc['content_hash']='sha256:'+digest(doc['content_md'])
        doc['version']+=1;doc['updated']=stamp
        doc['changelog'].append({'version':doc['version'],'at':stamp,'note':'Aligned highlighted quotation metadata with Blyg 0.3'})
        return doc
    def permalink(self,doc):
        return urljoin(self.origin,doc.get('page') or self.item_kind_path(doc)+'/'+doc['id']+'/')
    def permalink_rules(self,docs):
        # Apache serves the existing published page; never maintain another body copy.
        rules=['RewriteEngine On']
        names={iid:name for name,iid in self.state['ids'].items()}
        for iid,doc in sorted(docs.items()):
            if iid not in names:
                if doc['kind']=='withdrawn':continue
                route=self.item_kind_path(doc)
                rules.append('RewriteRule ^'+route+'/'+iid+'/?$ '+route+'/'+iid+'/index.html [END]')
                continue
            name=names[iid]; self.path(name)  # Restrict targets to known public HTML files.
            route=str(doc.get('page') or self.item_kind_path(doc)+'/'+iid+'/').strip('/')
            if not re.fullmatch(r'[ft]/'+re.escape(iid),route):route=self.item_kind_path(doc)+'/'+iid
            rules.append('RewriteRule ^'+route+'/?$ /'+name+' [END]')
        # Explicitly reject unknown IDs and the wrong kind, including pin directories.
        rules.append('RewriteRule ^[ft]/[^/]+/?$ - [R=404,L]')
        return '\n'.join(rules)+'\n'
    def pin_files(self,doc,files):
        iid=doc['id']
        for entry in doc['changelog']:
            if str(entry['version']) in self.state['pins'].get(iid,[]): entry['pinned']=True
            if not entry.get('pinned'): continue
            v=entry['version']; rel=f'blyg/items/{iid}/v{v}.json'; dest=self.root/rel
            if dest.exists():
                pin=json.loads(dest.read_text())
            else:
                source=doc if v==doc['version'] else self.state['history'].get(iid,{}).get(str(v))
                if not source: raise ValueError('The pinned version is missing from the private archive.')
                pin={k:copy.deepcopy(source[k]) for k in ('blyg','id','kind','version','origin','author','created','updated','content_md','content_html','content_hash','transclusions','generated','stub_of','forked_from') if k in source}
                pin.update(at=source['updated'],note=source['changelog'][-1].get('note'),pinned=True)
                files[rel]=json.dumps(pin,ensure_ascii=False,indent=2)
            kind='t' if pin['kind']=='thread' else 'f'
            page=f'blyg/{kind}/{iid}/v{v}/index.html'
            if not (self.root/page).exists():
                current=self.permalink(doc)
                frozen='<!doctype html><html><head><meta charset="utf-8"><link rel="canonical" href="'+html.escape(current,quote=True)+'">'+favicon_markup(self.config)+discovery_markup(self.config,blyg=True,rss=True)+'<title>Frozen version '+str(v)+'</title><style>body{font:18px/1.6 Georgia;max-width:800px;margin:40px auto;padding:20px}img{max-width:100%}</style></head><body><header><b>Frozen snapshot · version '+str(v)+'</b><p><a href="'+html.escape(current,quote=True)+'">Current version</a> · <a href="/'+rel+'">Pinned JSON</a></p></header><article>'+pin['content_html']+'</article></body></html>'
                files[page]=decorate_generation(frozen,pin.get('generated',[]))
    def version_footer(self,doc):
        links=[]
        for c in doc['changelog']:
            if not c.get('pinned'): continue
            pinpath=self.root/f"blyg/items/{doc['id']}/v{c['version']}.json"
            source=json.loads(pinpath.read_text()) if pinpath.exists() else doc if c['version']==doc['version'] else self.state['history'][doc['id']][str(c['version'])]
            kind='t' if source['kind']=='thread' else 'f'
            links.append('<li><a href="/blyg/'+kind+'/'+doc['id']+'/v'+str(c['version'])+'/">Version '+str(c['version'])+' · frozen pin</a> — '+html.escape(c['at'][:10])+' '+html.escape(c.get('note') or '')+'</li>')
        current='Versions · current v'+str(doc['version'])+' · '+html.escape(doc['updated'][:10])
        content='<details><summary style="cursor:pointer">'+current+'</summary><ul style="margin:6px 0;padding-left:20px">'+''.join(links)+'</ul></details>' if links else current
        return '<!-- blynger-versions-start --><section id="blynger-versions" aria-label="Version history" style="font:12px/1.5 Menlo,monospace;color:#666;border-top:1px solid #ddd;padding-top:8px;margin:24px auto 12px;max-width:768px;text-align:left"><div style="display:flex;gap:12px;align-items:flex-start;justify-content:space-between"><div>'+content+'</div><a href="'+html.escape(self.site+'feed.xml',quote=True)+'" style="font-size:14px;white-space:nowrap">RSS</a></div></section><!-- blynger-versions-end -->'
    def blogroll_entries(self):
        out=[]
        for sub in self.reader.state['subscriptions'].values():
            if not sub.get('active',True) or not sub.get('blogroll') or sub.get('type')=='web':continue
            feed=sub['origin'] if sub.get('type')=='l0' else sub['origin']+'feed.xml'
            u=urlsplit(feed);site=urlunsplit((u.scheme,u.netloc,'/','',''))
            out.append({'title':sub.get('title') or site,'htmlUrl':site,'xmlUrl':feed})
        return sorted(out,key=lambda row:row['title'].casefold())
    def place_blogroll(self,raw,entries):
        def home(row):
            u=urlsplit(row.get('xmlUrl') or row.get('htmlUrl') or '');return urlunsplit((u.scheme,u.netloc,'/','',''))
        if not entries:return raw
        if '<!-- blynger-blogroll-start -->' in raw:
            a=raw.index('<!-- blynger-blogroll-start -->');b=raw.index('<!-- blynger-blogroll-end -->',a)+len('<!-- blynger-blogroll-end -->');rail=raw[a:b]
            for row in entries:
                target=html.escape(home(row),quote=True)
                for old in {row.get('htmlUrl'),row.get('xmlUrl')}:
                    if not old:continue
                    escaped=html.escape(old,quote=True);rail=rail.replace('href="'+escaped+'"','href="'+target+'"').replace("href='"+escaped+"'","href='"+target+"'")
            return raw[:a]+rail+raw[b:]
        heading=html.escape(self.config.get('blogroll_heading') or 'Blogroll')
        links=''.join('<li><a href="'+html.escape(home(row),quote=True)+'">'+html.escape(row['title'])+'</a></li>' for row in entries)
        rail='<!-- blynger-blogroll-start --><aside class="blynger-blogroll"><h2>'+heading+'</h2><ul>'+links+'</ul></aside><!-- blynger-blogroll-end -->'
        style='<style id="blynger-blogroll-style">body>.blynger-post-layout{max-width:1080px;margin:auto;display:grid;grid-template-columns:minmax(0,768px) 220px;gap:32px;align-items:start}.blynger-post-layout>article{margin:0}.blynger-blogroll{font:70%/1.5 Menlo,monospace;border:1px solid #aaa;padding:10px}.blynger-blogroll h2{font-size:1em;margin-top:0}.blynger-blogroll ul{margin:0;padding-left:18px}@media(max-width:900px){body>.blynger-post-layout{display:block}.blynger-blogroll{max-width:768px;margin:20px auto}}</style>'
        raw=raw.replace('</head>',style+'</head>',1)
        match=re.search(r'(<article\b[^>]*>.*?</article\s*>)',raw,re.I|re.S)
        return raw[:match.start()]+'<div class="blynger-post-layout">'+match.group()+rail+'</div>'+raw[match.end():] if match else raw
    def place_versions(self,raw,name,doc):
        raw=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',raw,flags=re.S)
        footer=self.version_footer(doc)
        if name not in self.main_pages:
            a,b=region(raw)
            dates=list(re.finditer(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',raw[a:b]))
            bylines=[d for d in dates if self.author in raw[max(a,a+d.start()-200):a+d.start()]]
            end=a+bylines[-1].end() if bylines else b
            trailing=re.match(r'(?:\s*(?:<br\s*/?>|</p\s*>))*',raw[end:b],re.I)
            end+=trailing.end()
            footer=footer.replace('border-top:1px solid #ddd;padding-top:8px;margin:24px auto 12px','padding-top:0;margin:4px 0 12px')
            return raw[:end]+footer+raw[end:]
        return re.sub(r'</body\s*>',lambda m:footer+m.group(),raw,count=1,flags=re.I) if re.search(r'</body\s*>',raw,re.I) else raw+footer
    def upload(self,data,name,alt):
        content=base64.b64decode(data,validate=True)
        if len(content)>20*1024*1024: raise ValueError('Please choose an image under 20 MB.')
        with Image.open(io.BytesIO(content)) as im:
            im.verify(); ext={'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp'}.get(im.format)
        if not ext: raise ValueError('Use PNG, JPEG, GIF, or WebP.')
        rel='images/blynger/'+digest(content)+ext
        atomic(self.data/'uploads'/Path(rel).name,content)
        if rel not in self.state['uploaded']: self.state['uploaded'].append(rel)
        self.save_state(); return {'url':'/'+rel,'alt':alt,'html':'<p class="blynger-image blynger-image-standard"><img src="/'+rel+'" alt="'+html.escape(alt,quote=True)+'"></p>'}
    def images(self):
        out=[]
        usage={}
        for page in self.pages():
            if page.get('deleted'):continue
            try: raw=(self.state['drafts'].get(page['name']) or {}).get('raw') or self.read(page['name'])
            except (OSError,UnicodeDecodeError):continue
            for src in re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)',raw,re.I):
                target=urlsplit(urljoin(self.site,src))
                if target.netloc!=urlsplit(self.site).netloc:continue
                image_path=unquote(target.path).lstrip('/')
                usage.setdefault(image_path,[]).append(page['name'])
        for p in sorted((self.root/'images').rglob('*')):
            if p.is_file() and p.suffix.lower() in ['.jpg','.jpeg','.png','.gif','.webp']:
                rel=p.relative_to(self.root).as_posix(); dimensions=None
                try:
                    with Image.open(p) as image: dimensions=[image.width,image.height]
                except OSError:pass
                out.append({'url':'/'+rel,'name':p.name,'path':rel,'dimensions':dimensions,'used_in':sorted(set(usage.get(rel,[])))})
        for rel in self.state['uploaded']:
            if not (self.root/rel).exists():
                upload=self.data/'uploads'/Path(rel).name; dimensions=None
                try:
                    with Image.open(upload) as image: dimensions=[image.width,image.height]
                except OSError:pass
                out.append({'url':'/'+rel,'name':Path(rel).name,'path':rel,'dimensions':dimensions,'used_in':sorted(set(usage.get(rel,[])))})
        return out
    def git(self,*args,env=None,timeout=30):
        e=os.environ.copy(); e['GIT_TERMINAL_PROMPT']='0'; key=self.config['publishing'].get('ssh_key','')
        e['GIT_SSH_COMMAND']='ssh'+((' -i '+shlex.quote(str(key))) if key else '')+' -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes'
        if env: e.update(env)
        p=subprocess.run(['git',*args],cwd=self.root,env=e,capture_output=True,text=True,timeout=timeout)
        if p.returncode: raise ValueError(p.stderr.strip() or p.stdout.strip() or 'Git operation failed.')
        return p.stdout.strip()
    def settings(self):
        remote=self.state['remote']
        try: url=self.git('remote','get-url',remote)
        except ValueError: url=''
        items=sum(name not in self.non_blyg_pages and name not in self.state['standalone_pages'] for name in self.state['ids'])
        return {'remote':remote,'url':url,'branch':self.state['branch'],'site':self.site,'site_label':self.config['site_label'],'drafts':len(self.state['drafts']),'items':items}
    def connection(self):
        refs=self.git('ls-remote',self.state['remote'],'refs/heads/'+self.state['branch'],timeout=20)
        return {'message':'Connected to the publishing repository. No files sent.','refs':refs}
    def set_remote(self,hostname):
        suffix=self.config['publishing'].get('hostname_suffix','')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+',hostname) or (suffix and not hostname.endswith(suffix)): raise ValueError('Enter the SSH hostname shown by your hosting provider.')
        pub=self.config['publishing']; url='ssh://'+pub['ssh_user']+'@'+hostname+pub['remote_path']
        self.git('remote','set-url',pub['remote'],url); return self.settings()
    def effective_pages(self):
        return {p['name']:(self.page(p['name'])['raw'] if p['name'] in self.state.get('fragment_posts',{}) and not p.get('deleted') else self.state['drafts'][p['name']]['raw'] if p['name'] in self.state['drafts'] else self.read(p['name'])) for p in self.pages() if not (p.get('deleted') and p['name'] not in self.state['drafts'] and not self.path(p['name']).exists())}
    def content(self,raw,name,files):
        raw=strip_fragment_markers(raw)
        raw=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',raw,flags=re.S)
        a,b=region(raw); soup=BeautifulSoup(clean(raw[a:b]),'html.parser'); media=[]
        # Formatting a standalone quote marker must not turn it into inert Markdown.
        for node in soup.find_all(['h1','h2','h3','h4','h5','h6']):
            if not node.find_parent(['pre','code']) and re.fullmatch(r'\s*!\[\[[0-7][0-9a-hjkmnp-tv-z]{25}\]\]\s*',node.get_text()):node.name='p'
        snapshot_source=self.state['drafts'].get(name) or self.state['fragment_posts'].get(name,{})
        for quote in soup.select('[data-blynger-quote]'):
            token=quote.get('data-blynger-quote');record=snapshot_source.get('quotes',{}).get(token)
            if not record:raise ValueError('A quotation lost its source record. Reinsert the quote before publishing.')
            for asset in record.get('assets',[]):
                from reader import ASSET
                if not isinstance(asset,str) or not ASSET.fullmatch(asset):raise ValueError('Invalid quote asset.')
                path=self.data/'uploads'/asset
                if path.is_symlink() or not path.is_file():raise ValueError('A saved quotation image is missing.')
                files['blyg/media/'+asset]=path.read_bytes()
            source=record['source']
            if source.get('type')=='blyg':
                quote['data-source-origin']=source['origin'];quote['data-source-id']=source['id'];quote['data-source-version']=str(source['version'])
                if record.get('type')=='excerpt' and isinstance(source.get('selector'),dict):quote['data-blynger-selector']=json.dumps(source['selector'],ensure_ascii=False,separators=(',',':'))
            del quote['data-blynger-quote']
        # Preserve images outside article blocks, but omit image-based navigation.
        all_soup=BeautifulSoup(raw,'html.parser')
        present={im.get('src') for im in soup.find_all('img')}
        for im in all_soup.find_all('img'):
            src=im.get('src','')
            if src in present or im.find_parent('a') or not src: continue
            clone=BeautifulSoup(clean(str(im)),'html.parser')
            soup.insert(0,clone); present.add(src)
        for node in soup.find_all(True):
            for attr in ('href','src','poster'):
                if not node.get(attr): continue
                value=node[attr]; absolute=urljoin(self.site+name,value)
                if attr in ('src','poster'):
                    u=urlsplit(absolute)
                    if u.hostname in set(self.config.get('local_hostnames',[])):
                        local=(self.root/unquote(u.path).lstrip('/')).resolve()
                        if not local.is_relative_to(self.root): raise ValueError('Media path leaves the site.')
                        upload=self.data/'uploads'/local.name
                        content=local.read_bytes() if local.is_file() else upload.read_bytes() if upload.is_file() else None
                        if content is not None:
                            rel='blyg/media/'+digest(content)+local.suffix.lower(); files[rel]=content; absolute=self.site+rel
                    if attr=='src': media.append({'url':absolute,'mime':mimetypes.guess_type(absolute)[0] or 'application/octet-stream','alt':node.get('alt','')})
                node[attr]=absolute
        for paragraph in list(soup.find_all('p')):
            if not paragraph.get_text(strip=True) and not paragraph.find(['img','audio','video','source']):paragraph.decompose()
        for quote in soup.select('blockquote.blyg-transclusion[data-blyg-id]'):
            if 'blynger-citation' in quote.get('class',[]) or quote.find_parent('blockquote',class_='blynger-citation'):continue
            node=soup.new_tag('p'); node.string='![['+quote['data-blyg-id']+']]'; quote.replace_with(node)
        content_html=str(soup)
        md_soup=BeautifulSoup(content_html,'html.parser')
        for quote in md_soup.select('blockquote.blynger-citation.blyg-transclusion.blyg-partial[data-blyg-id]'):
            quote['class']=[value for value in quote.get('class',[]) if value!='blyg-transclusion']
            for key in ('data-blyg-id','data-blyg-version','data-blyg-origin','data-blynger-selector'):quote.attrs.pop(key,None)
        for quote in md_soup.select('blockquote.blynger-citation.blyg-transclusion[data-blyg-id]:not(.blyg-partial)'):
            if quote.find_parent('blockquote',class_='blynger-citation'):continue
            node=md_soup.new_tag('p');node.string='![['+quote['data-blyg-id']+']]';quote.replace_with(node)
        md=markdownify(str(md_soup),heading_style='ATX').strip()
        # An unresolved TK scope must never reach published files.
        if re.search(r'\[/?TK\]',md,re.I): raise ValueError(name+': resolve or remove [TK] instructions before publishing.')
        return content_html,md,media
    def resolve_transclusions(self,content_html,item_id,docs,files):
        """Bake genuine directives from the current local Reader snapshot."""
        transclusions=[];soup=BeautifulSoup(content_html,'html.parser')
        directive=re.compile(r'^\s*!\[\[([0-7][0-9a-hjkmnp-tv-z]{25})\]\]\s*$')
        for quote in soup.select('blockquote.blynger-citation.blyg-transclusion[data-blyg-id]'):
            if quote.find_parent('blockquote',class_='blynger-citation'):continue
            if 'blyg-partial' in quote.get('class',[]):
                quote['class']=[value for value in quote.get('class',[]) if value!='blyg-transclusion']
                for key in ('data-blyg-id','data-blyg-version','data-blyg-origin','data-blynger-selector'):quote.attrs.pop(key,None)
                continue
            reference={'id':quote['data-blyg-id'],'version':int(quote['data-blyg-version']),'origin':quote['data-blyg-origin']}
            quoted,reference=self.quote_source(reference['id'],item_id,docs,files,reference['origin'])
            quote.clear();quote.append(BeautifulSoup(quoted,'html.parser'))
            # The editor's citation class, private token, and convenience
            # attributes are authoring state. The wire wrapper is the bare
            # protocol shape required by §10.2.
            quote.attrs={'class':['blyg-transclusion'],'data-blyg-id':reference['id'],'data-blyg-version':str(reference['version'])}
            if reference.get('origin'):quote['data-blyg-origin']=reference['origin']
            transclusions.append(reference)
        for node in list(soup.find_all(['p','div','h1','h2','h3','h4','h5','h6'])):
            if node.find(['p','div','h1','h2','h3','h4','h5','h6','pre','code']) or node.find_parent(['pre','code']):continue
            if node.find_parent('blockquote',class_='blynger-citation'):continue
            match=directive.fullmatch(node.get_text())
            if not match:continue
            iid=match.group(1);quoted,reference=self.quote_source(iid,item_id,docs,files)
            transclusions.append(reference)
            origin_attr=' data-blyg-origin="'+html.escape(reference['origin'],quote=True)+'"' if reference.get('origin') else ''
            block=BeautifulSoup('<blockquote class="blyg-transclusion" data-blyg-id="'+iid+'" data-blyg-version="'+str(reference['version'])+'"'+origin_attr+'>'+quoted+'</blockquote>','html.parser')
            node.replace_with(block)
        return str(self.resolve_internal_links(soup,docs)),transclusions
    def public_content(self,raw,content_html,name):
        """Do not echo an outside-article hero image into the human article."""
        page=BeautifulSoup(raw,'html.parser');content=BeautifulSoup(content_html,'html.parser')
        article=page.find('article')
        outside=[node for node in page.find_all('img') if not node.find_parent('a') and (not article or node not in article.descendants)]
        for original in outside:
            source=original.get('src','');absolute=urljoin(self.site+name,source);fingerprint=None
            parsed=urlsplit(absolute)
            if parsed.hostname in set(self.config.get('local_hostnames',[])):
                local=(self.root/unquote(parsed.path).lstrip('/')).resolve()
                if local.is_relative_to(self.root) and local.is_file():fingerprint=digest(local.read_bytes())
            for candidate in content.find_all('img'):
                target=urljoin(self.site+name,candidate.get('src',''));managed=Path(urlsplit(target).path).stem
                if target==absolute or (fingerprint and managed==fingerprint):
                    candidate.decompose();break
        return str(content)
    def build(self,pages):
        files={}; docs={}; fragment_context={}; touched_fragments=set(); stamp=now()
        # Published standalone fragments remain available when their designation is removed.
        page_ids=set(self.state['ids'].values())
        docs.update({iid:copy.deepcopy(d) for iid,d in self.state['published'].items() if iid not in page_ids})
        mapped_pages={}
        for name,raw in pages.items():
            if self.state['deleted_posts'].get(name,{}).get('active'):continue
            if name in self.state['standalone_pages']:continue
            source=self.state['drafts'].get(name) or self.state.get('fragment_posts',{}).get(name,{})
            meta=source.get('fragments')
            if not meta: continue
            if name=='openers.html': self.state['ids'].setdefault(name,uid())  # Private parent key; the aggregate page is not a public Blyg item.
            a,b=region(raw); meta=self.validate_fragments(name,meta,clean(raw[a:b]))
            blocks=[x['html'] for x in meta['blocks']]
            identities=self.state['fragment_ids'].setdefault(name,{})
            for r,start,end,body in reversed(list(fragment_model.ranges(meta))):
                iid=identities.setdefault(r['key'],uid()); old=self.state['published'].get(iid)
                if meta.get('purpose')!='openers':
                    fragment_context[iid]={'title':title_of(raw,name),'url':self.site+name}
                staged_path=self.root/f'blyg/items/{iid}.json'
                staged=json.loads(staged_path.read_text()) if staged_path.exists() else {}
                first_at=staged.get('created',stamp)
                fh,fm,media=self.content('<article>'+body+'</article>',name,files)
                if meta.get('purpose')=='openers' and not fm.strip(): raise ValueError('An Opener is empty. Add its text before publishing.')
                stub=copy.deepcopy(r.get('stub_of',(old or {}).get('stub_of')))
                transclusions=[]
                if re.search(r'!\[\[',fm):
                    if stub is None:raise ValueError('A reusable fragment cannot contain another quote. Leave that section as ordinary thread prose.')
                    fh,transclusions=self.resolve_transclusions(fh,iid,docs,files)
                all_generated=source.get('generated') or []
                offset=len(BeautifulSoup(''.join(x['html'] for x in meta['blocks'][:start]),'html.parser').select('.blyg-tk-gen'))
                count=len(BeautifulSoup(body,'html.parser').select('.blyg-tk-gen'))
                generated=all_generated[offset:offset+count] or (old or {}).get('generated',[])
                generated=generated+[{'sources':[]}] * max(0,count-len(generated))
                changed=not old or old['content_md']!=fm or old['content_html']!=fh or stub!=(old or {}).get('stub_of')
                if changed:
                    v=old['version']+1 if old else 1
                    self.state['item_titles'][iid]=BeautifulSoup(fh,'html.parser').get_text(' ',strip=True)[:100] or iid
                    if v==1:self.state['site_feed_titles'].setdefault(iid,self.state['item_titles'][iid])
                    kind='thread' if (old or {}).get('kind')=='thread' or stub is not None else 'fragment'
                    page=(old or {}).get('page') or kind[0]+'/'+iid+'/'
                    doc={'blyg':BLYG_VERSION,'id':iid,'kind':kind,'origin':self.origin,'page':page,'author':{'name':self.author,'url':self.site},'created':old['created'] if old else first_at,'updated':stamp if old else first_at,'version':v,'content_md':fm,'content_html':fh,'content_hash':'sha256:'+digest(fm),'media':media,'changelog':copy.deepcopy(old['changelog']) if old else []}
                    doc['changelog'].append({'version':v,'at':doc['updated'],'note':source.get('note') or ('Updated fragment' if old else 'Fragment from '+name)})
                    if r.get('pin_on_publish'):doc['changelog'][-1]['pinned']=True
                    if doc['kind']=='thread':doc['transclusions']=transclusions
                    if stub is not None:
                        match=next((ref for ref in transclusions if ref['id']==stub.get('id') and ref.get('origin',self.origin)==stub.get('origin')),None) if isinstance(stub,dict) else None
                        if match:stub['version']=match['version']
                        doc['stub_of']=stub
                    if 'blyg-tk-gen' in fh: doc['generated']=copy.deepcopy(generated or [{'sources':[]}])
                else: doc=copy.deepcopy(old)
                if changed or name in self.state['drafts']:touched_fragments.add(iid)
                docs[iid]=doc
                blocks[start:end]=['<p>![['+iid+']]</p>']
            mapped_pages[name]=raw[:a]+''.join(blocks)+raw[b:]

        for name,raw in pages.items():
            if name in self.state['standalone_pages'] or name in self.non_blyg_pages:continue
            item_id=self.state['ids'].setdefault(name,uid()); old=self.state['published'].get(item_id)
            if self.state['deleted_posts'].get(name,{}).get('active'):
                if not old:continue
                doc=copy.deepcopy(old)
                if old['kind']!='withdrawn':
                    doc.update(kind='withdrawn',version=old['version']+1,updated=stamp,content_md='',content_html='',content_hash='sha256:'+digest(''),media=[])
                    if 'transclusions' in doc:doc['transclusions']=[]
                    doc.pop('generated',None);doc.pop('stub_of',None);doc['changelog'].append({'version':doc['version'],'at':stamp,'note':'Post withdrawn by author'})
                docs[item_id]=doc;continue
            content_html,md,media=self.content(mapped_pages.get(name,raw),name,files)
            old_local=self.root/'blyg/items'/f'{item_id}.json'
            local=json.loads(old_local.read_text()) if old_local.exists() else None
            created=old['created'] if old else local['created'] if local else stamp
            if not old and not local:
                soup=BeautifulSoup(raw,'html.parser'); meta=soup.find('meta',attrs={'property':'article:published_time'})
                if meta:
                    try: created=datetime.fromisoformat(meta.get('content','').replace('Z','+00:00')).astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
                    except ValueError: pass
            transclusions=[]
            if re.search(r'!\[\[[^\]]+@v[0-9]+\]\]',md): raise ValueError('Explicit-version quote directives are reserved. Use a link to a pinned version instead.')
            draft=self.state['drafts'].get(name,{})
            reuse=bool(old and md==old['content_md'] and not draft)
            if reuse:
                # An unchanged published snapshot is already complete. Reusing it
                # must not depend on a Reader cache that may since have expired.
                content_html=old['content_html'];transclusions=copy.deepcopy(old.get('transclusions',[]))
            else:
                content_html,transclusions=self.resolve_transclusions(content_html,item_id,docs,files)
            changed=bool(draft.get('revision')) or not old or old['content_hash']!='sha256:'+digest(md) or old['content_html']!=content_html
            if not changed: doc=copy.deepcopy(old)
            else:
                version=old['version']+1 if old else 1
                at=stamp if old else created
                self.state['item_titles'][item_id]=title_of(raw,name)
                if version==1:self.state['site_feed_titles'].setdefault(item_id,self.state['item_titles'][item_id])
                stub=draft.get('stub_of',(old or {}).get('stub_of'))
                kind='thread' if (old or {}).get('kind')=='thread' or len(md)>2000 or transclusions or stub is not None else 'fragment'
                page=(old or local or {}).get('page') or kind[0]+'/'+item_id+'/'
                doc={'blyg':BLYG_VERSION,'id':item_id,'kind':kind,'origin':self.origin,'page':page,'author':{'name':self.author,'url':self.site},'created':created,'updated':at,'version':version,'content_md':md,'content_html':content_html,'content_hash':'sha256:'+digest(md),'media':media,'changelog':(copy.deepcopy(old['changelog']) if old else [])+[{'version':version,'at':at,'note':draft.get('note') or ('Updated in Blynger' if old else 'Imported from '+name)}]}
                if draft.get('pin_on_publish'):doc['changelog'][-1]['pinned']=True
                if doc['kind']=='thread': doc['transclusions']=transclusions
                for field in ('stub_of','forked_from'):
                    value=draft.get(field,(old or {}).get(field))
                    if value is not None:doc[field]=copy.deepcopy(value)
                if doc.get('stub_of') is not None:
                    target=doc['stub_of']
                    if not isinstance(target,dict):raise ValueError('A response lost its source identity.')
                    if set(target)=={'url'}:
                        if not isinstance(target['url'],str) or urlsplit(target['url']).scheme not in ('http','https'):raise ValueError('A web response needs one public source URL.')
                    elif not {'origin','id','version'}<=set(target) or set(target)-{'origin','id','version','cited'}:
                        raise ValueError('A Blyg response lost its source identity.')
                    else:
                        match=next((ref for ref in transclusions if ref['id']==target['id'] and ref.get('origin',self.origin)==target['origin']),None)
                        # The response identity remains fixed, while the published
                        # stub records the source version actually quoted.
                        if match:target['version']=match['version']
                generated=self.state['drafts'].get(name,{}).get('generated',[])
                if 'blyg-tk-gen' in content_html:
                    doc['generated']=generated or (old or local or {}).get('generated',[{'sources':[]}])
            docs[item_id]=doc
        for iid,doc in docs.items():
            self.normalize_partial_quotes(doc,stamp)
            if re.search(r'(?<!!)\[\[[0-7][0-9a-hjkmnp-tv-z]{25}\]\]',doc['content_md']):
                doc['content_html']=str(self.resolve_internal_links(BeautifulSoup(doc['content_html'],'html.parser'),docs))
            self.normalize_item(doc)
            self.pin_files(doc,files)
            files[f'blyg/items/{iid}.json']=json.dumps(doc,ensure_ascii=False,indent=2)
            if iid not in self.state['ids'].values():
                context=fragment_context.get(iid)
                if context:
                    body=doc['content_html']+'<p class="blynger-full-thread"><a href="'+html.escape(context['url'],quote=True)+'">Full thread</a></p>'
                    page=new_page('FROM: '+context['title'],body,self.config)
                else:
                    page=new_page(self.item_title(doc),doc['content_html'],self.config)
                rel=f"blyg/{'t' if doc['kind']=='thread' else 'f'}/{iid}/index.html";existing=self.root/rel
                advertise=iid in touched_fragments or not existing.exists()
                if existing.exists() and BeautifulSoup(existing.read_text(),'html.parser').find('link',rel=lambda value:value and 'blyg' in value):advertise=True
                links=discovery_markup(self.config,blyg=advertise,rss=advertise,item_json=self.origin+'items/'+iid+'.json')
                head='\n'.join(part for part in (favicon_markup(self.config),links) if part)
                page=page.replace('</head>',head+'\n</head>',1)
                keep_disclosure=existing.exists() and 'id="blynger-generation-disclosure-script"' in existing.read_text()
                if iid in touched_fragments or not existing.exists() or keep_disclosure:page=decorate_generation(page,doc.get('generated',[]))
                files[rel]=self.place_versions(page,'fragment.html',doc)
        ordered=sorted(docs.values(),key=lambda d:(d['updated'],d['id']),reverse=True)
        updated=max((d['updated'] for d in ordered),default=stamp)
        manifest={'blyg':BLYG_VERSION,'level':2,'generator':'Blynger/'+APP_VERSION,'generator_url':'https://github.com/BradyDale/Blynger','site':self.origin,'title':self.config['blyg_title'],'author':{'name':self.author,'links':[{'label':'Home','url':self.site}]},'feed':'feed.xml','items':'items/index.json','updated':updated}
        blogroll=self.blogroll_entries()
        if blogroll:
            manifest['blogroll']='blogroll.opml'
            opml=ET.Element('opml',version='2.0');head=ET.SubElement(opml,'head');ET.SubElement(head,'title').text=self.config.get('blogroll_heading') or 'Blogroll';body=ET.SubElement(opml,'body')
            for row in blogroll:ET.SubElement(body,'outline',text=row['title'],title=row['title'],type='rss',xmlUrl=row['xmlUrl'],htmlUrl=row['htmlUrl'])
            files['blyg/blogroll.opml']=ET.tostring(opml,encoding='utf-8',xml_declaration=True)
        files['blyg/blyg.json']=json.dumps(manifest,indent=2)
        files['blyg/items/index.json']=json.dumps({'updated':updated,'items':[{k:d[k] for k in ('id','kind','created','updated','version')} for d in ordered]},indent=2)
        def elem(parent,tag,text,**attrs): ET.SubElement(parent,tag,attrs).text=str(text)
        def rfc(value): return format_datetime(datetime.fromisoformat(value.replace('Z','+00:00')),usegmt=True)
        def event_title(doc,event):
            if doc['kind']=='withdrawn':return 'withdrawn'
            excerpt=re.sub(r'\s+',' ',BeautifulSoup(doc['content_html'],'html.parser').get_text(' ',strip=True)).strip()
            excerpt=excerpt[:117].rstrip()+('…' if len(excerpt)>117 else '')
            note=event.get('note') if isinstance(event.get('note'),str) else ''
            return (note.strip()+' — '+excerpt if note.strip() and excerpt else note.strip() or excerpt or 'untitled')
        rss=ET.Element('rss',version='2.0'); channel=ET.SubElement(rss,'channel')
        ET.SubElement(channel,'{http://www.w3.org/2005/Atom}link',href=self.origin+'feed.xml',rel='self',type='application/rss+xml')
        for tag,val in [('title',manifest['title']),('link',self.origin),('description',self.config['feed_description']),('lastBuildDate',rfc(updated)),('{'+NS+'}level','2'),('{'+NS+'}manifest',self.origin+'blyg.json')]: elem(channel,tag,val)
        opener_ids=self.state['fragment_ids'].get('openers.html',{})
        opener_item_ids=set(opener_ids.values())
        quiet_ids={opener_ids[k] for k in self.state.get('opener_rss_legacy_keys',[]) if k in opener_ids}
        page_names={iid:name for name,iid in self.state['ids'].items()}
        events=[]
        for d in ordered:
            if d['kind']=='withdrawn':
                current=next((c for c in reversed(d['changelog']) if c.get('version')==d['version']),None)
                changelog=[current] if current else []
            else:changelog=d['changelog']
            for c in changelog:events.append((c['at'],d,c))
        events=sorted(events,key=lambda x:(x[0],x[2].get('version',0),x[1]['id']),reverse=True)[:50]
        for at,d,c in events:
            item=ET.SubElement(channel,'item'); elem(item,'guid',f"blyg:{d['id']}:v{c['version']}",isPermaLink='false')
            author=d.get('author',{}).get('name') if isinstance(d.get('author'),dict) else None
            values=[('link',self.permalink(d)),('title',event_title(d,c)),('description',d['content_html']),('pubDate',rfc(at))]
            if author:values.append(('{http://purl.org/dc/elements/1.1/}creator',author))
            values += [('{'+NS+'}id',d['id']),('{'+NS+'}kind',d['kind']),('{'+NS+'}version',c['version']),('{'+NS+'}created',d['created']),('{'+NS+'}item',self.origin+'items/'+d['id']+'.json')]
            for tag,val in values:elem(item,tag,val)
        files['blyg/feed.xml']=ET.tostring(rss,encoding='utf-8',xml_declaration=True)
        # A separate plain RSS feed preserves the site's quiet editorial policy:
        # first publications of posts and new Openers only, with no blyg fields.
        site_rss=ET.Element('rss',version='2.0');site_channel=ET.SubElement(site_rss,'channel')
        ET.SubElement(site_channel,'{http://www.w3.org/2005/Atom}link',href=self.site+'feed.xml',rel='self',type='application/rss+xml')
        for tag,val in [('title',manifest['title']),('link',self.site),('description',self.config['feed_description']),('lastBuildDate',rfc(updated))]:elem(site_channel,tag,val)
        site_events=[]
        for d in ordered:
            if d['kind']=='withdrawn' or d['id'] in quiet_ids:continue
            name=page_names.get(d['id'])
            if d['id'] not in opener_item_ids and (not name or name in self.non_blyg_pages):continue
            first=next((c for c in d['changelog'] if c.get('version')==1),None)
            if first:
                site_events.append((first['at'],d))
        for at,current in sorted(site_events,key=lambda row:row[0],reverse=True)[:77]:
            item=ET.SubElement(site_channel,'item');link=self.permalink(current)
            elem(item,'guid',link,isPermaLink='true');elem(item,'link',link);elem(item,'title',self.state['site_feed_titles'].get(current['id'],self.item_title(current)));elem(item,'description',current['content_html']);elem(item,'pubDate',rfc(at))
        files['feed.xml']=ET.tostring(site_rss,encoding='utf-8',xml_declaration=True)
        blogroll_link='<link rel="blogroll" href="blogroll.opml">' if blogroll else ''
        blyg_head=''.join(part for part in (favicon_markup(self.config),discovery_markup(self.config,blyg=True,rss=True),blogroll_link) if part)
        files['blyg/index.html']='<!doctype html><html><head><meta charset="utf-8"><title>'+html.escape(self.config['blyg_title'])+'</title>'+blyg_head+'<style>body{font:18px/1.6 monospace;max-width:800px;margin:40px auto;padding:20px}</style></head><body><h1>'+html.escape(self.config['blyg_title'])+'</h1><p><a href="/">Home</a> · <a href="feed.xml">Blyg feed</a></p>'+''.join('<p><a href="'+html.escape(self.permalink(d),quote=True)+'">'+html.escape(self.item_title(d))+'</a> · v'+str(d['version'])+'</p>' for d in ordered if d['kind']!='withdrawn')+'</body></html>'
        files['blyg/.htaccess']='<IfModule mod_headers.c>\nHeader set Access-Control-Allow-Origin "*"\n</IfModule>\nAddType application/json .json\nAddType application/rss+xml .xml\n'+self.permalink_rules(docs)
        # Observe the final wire artifacts independently before private state
        # is saved or any website file is written.
        self.last_conformance=validate_surface(self.root,self.origin,files,strict_existing=False)
        self.save_state(); return files,docs
    def migrate(self):
        if any(d.get('fragments') for d in self.state['drafts'].values()):
            raise ValueError('Use Review & publish to prepare your fragment drafts together with their parent posts.')
        pages={p['name']:self.page(p['name'])['raw'] if p['name'] in self.state.get('fragment_posts',{}) else self.read(p['name']) for p in self.pages() if self.path(p['name']).exists()}
        files,docs=self.build(pages)
        for name,data in files.items(): atomic(self.root/name,data)
        self.state['pending']=sorted(set(self.state['pending'])|set(files)); self.save_state()
        return {'message':f'Prepared {len(docs)} Blyg copies locally. Original pages preserved. Nothing published.','count':len(docs)}
    def prepare(self,review=True):
        self.require_current_fragment_files()
        pages=self.effective_pages(); changes={}
        for name,draft in self.state['drafts'].items():
            if draft.get('new') and name not in self.non_blyg_pages and name not in self.state['standalone_pages'] and 'blogroll_snapshot' not in draft:
                draft['blogroll_snapshot']=self.blogroll_entries()
        for name,d in self.state['drafts'].items():
            p=self.path(name); actual=digest(p.read_bytes()) if p.exists() else None
            if actual!=d['base']: raise ValueError(name+' changed outside Blynger. Reopen it before publishing.')
            changes[name]=d['raw']
        new=sorted(((n,d) for n,d in self.state['drafts'].items() if n not in self.state['standalone_pages'] and (d['new'] or d.get('restore_home'))),key=lambda x:(x[1]['at'],list(self.state['drafts']).index(x[0])),reverse=True)
        if new:
            home=pages['index.html']
            headings=[m for m in re.finditer(r'<h([1-6])\b[^>]*>.*?</h\1\s*>',home,re.I|re.S) if BeautifulSoup(m.group(), 'html.parser').get_text(' ',strip=True).casefold()=='posts']
            if len(headings)>1:raise ValueError('The homepage has more than one Posts heading. Give the post list a single Posts heading before publishing.')
            match=headings[0] if headings else None
            if not match: raise ValueError('The homepage Posts heading is missing; no homepage changes were made.')
            links='\n'+''.join('<a href="/'+n+'">'+html.escape(title_of(d['raw'],n))+'</a>, '+human_date(datetime.fromisoformat(d['at'].replace('Z','+00:00')))+'<br>\n' for n,d in new if not re.search(r'href=[\"\']/?'+re.escape(n)+r'[\"\']',home))
            home=home[:match.end()]+links+home[match.end():]; pages['index.html']=home; changes['index.html']=home
        home=pages['index.html']
        for removed,entry in self.state['deleted_posts'].items():
            if entry.get('active'):
                home=re.sub(r'<a\b[^>]*href=[\"\'](?:'+re.escape(self.site)+r'|/)?'+re.escape(removed)+r'[\"\'][^>]*>.*?</a>[^<]*(?:<br\s*/?>)?','',home,flags=re.I|re.S)
        if home!=pages['index.html']:pages['index.html']=home;changes['index.html']=home
        for name,raw in list(changes.items()):
            has_generation_style=BeautifulSoup(raw,'html.parser').find('style',id='blynger-generation-style') is not None
            if 'blyg-tk-gen' in raw and not has_generation_style:
                raw=raw.replace('</head>',STYLE+'</head>',1); changes[name]=raw; pages[name]=raw
            if 'blynger-image' in raw and 'id="blynger-image-style"' not in raw:
                raw=raw.replace('</head>',IMAGE_STYLE+'</head>',1);changes[name]=raw;pages[name]=raw
        # Only pages explicitly being authored (or explicitly pinned) may be
        # re-rendered. Blyg mirrors are rebuilt from all pages, but that must
        # never back-propagate a current template into the static archive.
        render_names={name for name in changes if name.endswith('.html')}
        render_names.update(name for name,iid in self.state['ids'].items() if self.state.get('pins',{}).get(iid))
        if 'openers.html' in self.state.get('fragment_posts',{}) and 'openers.html' not in self.state.get('fragment_ids',{}):
            render_names.add('openers.html')  # One-time public fragment links after the private Openers migration.
        files,docs=self.build(pages); changes.update(files)
        blogroll_file=self.root/'blyg/blogroll.opml'
        if 'blyg/blogroll.opml' not in files and blogroll_file.is_file():
            blogroll_file.unlink();self.state['pending'].append('blyg/blogroll.opml')
        sitemap_names={n for n in pages if not self.state['deleted_posts'].get(n,{}).get('active')}
        page_ids=set(self.state['ids'].values())
        sitemap_names.update('blyg/'+('t' if d['kind']=='thread' else 'f')+'/'+iid+'/' for iid,d in docs.items() if d['kind'] in ('fragment','thread') and iid not in page_ids)
        changes['sitemap.xml']=sitemap(sitemap_names,self.site)
        for name,raw in pages.items():
            if name not in render_names: continue
            if name in self.state['standalone_pages']:
                rendered=restore_post_navigation(strip_fragment_markers(raw),name,self.config)
                rendered=enrich(rendered,name,self.root,standalone=True,config=self.config)
                if not BeautifulSoup(rendered,'html.parser').find('base'):
                    rendered=re.sub(r'<head\b[^>]*>',lambda m:m.group()+'<base href="'+html.escape(self.site+name,quote=True)+'">',rendered,count=1,flags=re.I)
                changes[name]=rendered
                continue
            if name in self.non_blyg_pages:
                rendered=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',strip_fragment_markers(raw),flags=re.S)
                source=self.state['drafts'].get(name) or self.state.get('fragment_posts',{}).get(name,{})
                if source.get('fragments',{}):
                    a,b=region(rendered);meta=self.validate_fragments(name,source['fragments'],clean(rendered[a:b]));blocks=[x['html'] for x in meta['blocks']]
                    identities=self.state['fragment_ids'].get(name,{})
                    for r,start,end,body in reversed(list(fragment_model.ranges(meta))):
                        iid=identities[r['key']]
                        target=docs.get(iid,{});route='t' if target.get('kind')=='thread' else 'f'
                        permalink=self.origin+str(target.get('page') or route+'/'+iid+'/').lstrip('/')
                        blocks[start]='<!-- blynger-fragment-link-start --><span class="blynger-fragment-marker"><a href="'+permalink+'" title="'+('Response' if route=='t' else 'Fragment')+'" aria-label="Read this '+('response' if route=='t' else 'fragment')+'"></a></span><!-- blynger-fragment-link-end -->'+blocks[start]
                    rendered=rendered[:a]+''.join(blocks)+rendered[b:]
                    rendered=rendered.replace('</head>',FRAGMENT_DOT_STYLE+'</head>',1)
                rendered=enrich(rendered,name,self.root,config=self.config,blyg_item=False,blyg_discovery=name=='index.html',rss_discovery=True)
                changes[name]=rendered
                continue
            doc=docs.get(self.state['ids'][name])
            if not doc:continue
            stripped=re.sub(r'<!-- blynger-versions-start -->.*?<!-- blynger-versions-end -->','',strip_fragment_markers(raw),flags=re.S)
            rendered=new_page('Post removed','<p>This post has been removed by its author.</p>',self.config) if self.state['deleted_posts'].get(name,{}).get('active') else stripped
            # Public thread pages show baked quotes; draft source retains directives.
            if doc.get('transclusions') or 'data-blynger-quote=' in rendered:
                a,b=region(rendered); rendered=rendered[:a]+self.public_content(stripped,doc['content_html'],name)+rendered[b:]
            source=self.state['drafts'].get(name) or self.state.get('fragment_posts',{}).get(name,{})
            if source.get('fragments',{}):
                own=set(self.state['fragment_ids'].get(name,{}).values())
                soup=BeautifulSoup(rendered,'html.parser')
                # The protocol keeps quote wrappers; the author's own page keeps its prose layout.
                for quote in soup.select('blockquote.blyg-transclusion[data-blyg-id]'):
                    if quote['data-blyg-id'] in own:
                        iid=quote['data-blyg-id']
                        marker=BeautifulSoup('<!-- blynger-fragment-link-start --><span class="blynger-fragment-marker"><a href="'+self.origin+'f/'+iid+'/" title="Fragment" aria-label="Read this fragment"></a></span><!-- blynger-fragment-link-end -->','html.parser')
                        quote.insert_before(marker);quote.unwrap()
                rendered=str(soup)
                if soup.select('.blynger-fragment-marker'):
                    rendered=rendered.replace('</head>',FRAGMENT_DOT_STYLE+'</head>',1)
            if 'blyg-transclusion' in rendered or 'blynger-citation' in rendered:
                rendered=re.sub(r'<style id="blynger-quote-style">.*?</style>','',rendered,flags=re.S)
                rendered=rendered.replace('</head>',QUOTE_STYLE+'</head>',1)
            rendered=restore_post_navigation(rendered,name,self.config)
            rendered=self.place_blogroll(rendered,source.get('blogroll_snapshot',[]))
            rendered=self.place_versions(rendered,name,doc)
            rendered=decorate_generation(rendered,doc.get('generated',[]))
            rendered=enrich(rendered,name,self.root,published=self.state['drafts'].get(name,{}).get('at') if self.state['drafts'].get(name,{}).get('new') else None,modified=doc['updated'] if doc['version']>1 else None,config=self.config,item_json=self.origin+'items/'+doc['id']+'.json',blyg_item=True,blyg_discovery=True,rss_discovery=True)
            if not BeautifulSoup(rendered,'html.parser').find('base'):
                rendered=re.sub(r'<head\b[^>]*>',lambda m:m.group()+'<base href="'+html.escape(self.site+name,quote=True)+'">',rendered,count=1,flags=re.I)
            changes[name]=rendered

        for rel in self.state['uploaded']:
            p=self.data/'uploads'/Path(rel).name
            if p.exists(): changes[rel]=p.read_bytes()
        written=[]
        for name,data in changes.items():
            payload=data if isinstance(data,bytes) else data.encode()
            target=self.root/name
            if target.is_file() and target.read_bytes()==payload:continue
            atomic(target,payload);written.append(name)
        for name,d in self.state['drafts'].items():
            d['raw']=pages[name]; d['base']=digest(self.path(name).read_bytes()); d['new']=False
        for name,saved in self.state.get('fragment_posts',{}).items():
            if name in changes: saved['file_hash']=digest(self.path(name).read_bytes())
        self.state['pending']=sorted(set(self.state['pending'])|set(written)); self.save_state()
        if review:return self.review()
        return {'message':'Prepared local publication files. Nothing published.','changed':len(written)}
    def allowed(self,name):
        return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.html',name) and name!='template.html') or name in ('feed.xml','sitemap.xml','robots.txt') or name.startswith('blyg/') or name in self.state['uploaded']
    def refresh_review(self):
        self.git('fetch','--no-tags',self.state['remote'],'refs/heads/'+self.state['branch'],timeout=60)
        hosted=self.git('rev-parse','FETCH_HEAD');head=self.git('rev-parse','HEAD')
        self.state['review_base']=hosted;self.save_state();review=self.review()
        if hosted!=head:
            common=self.git('merge-base',head,hosted)
            hosted_changes={name for name in self.git('diff','--name-only',common,hosted).splitlines() if self.allowed(name)}
            overlap=hosted_changes & {change['path'] for change in review['changes']}
            if overlap:
                names=', '.join(sorted(overlap)[:5]);more=' and '+str(len(overlap)-5)+' more' if len(overlap)>5 else ''
                raise ValueError('The hosted site has newer versions of files this publication would replace ('+names+more+'). Publishing stopped so newer writing cannot be overwritten. Bring the hosted changes to this Mac before continuing.')
        return review
    def publication_message(self,changes):
        pages=[c for c in changes if '/' not in c['path'] and c['path'].endswith('.html')]
        parts=[]
        removed=[c['path'] for c in pages if c.get('deleted')]
        if removed:parts.append('Removed '+', '.join(removed[:5])+(' and '+str(len(removed)-5)+' more pages' if len(removed)>5 else ''))
        for new,label in ((True,'Created'),(False,'Changed')):
            names=[c['path'] for c in pages if not c.get('deleted') and c['new']==new]
            if names: parts.append(label+' '+', '.join(names[:5])+(' and '+str(len(names)-5)+' more pages' if len(names)>5 else ''))
        other=[c['path'] for c in changes if c['path'] in ('robots.txt','sitemap.xml')]
        if other: parts.append('Updated '+', '.join(other))
        if any(c['path'].startswith('images/') for c in changes): parts.append('Updated images')
        return '; '.join(parts) or ('Updated Blyg publication files' if changes else 'Retry previous publication')
    def publication_note(self,note):
        if not isinstance(note,str) or len(note)>1000 or '\x00' in note: raise ValueError('Use a publication note under 1,000 characters.')
        self.state['publication_note']=note.strip(); self.save_state()
        return {'message':'Publication note saved locally.'}
    def publication_status(self):
        """Fast local signal for whether Review & publish has work to do."""
        if self.state.get('pending_publication'):return {'ready':True}
        if self.state['drafts'] or any(self.state.get('pins',{}).values()): return {'ready':True}
        base=self.state.get('review_base') or self.git('rev-parse','HEAD')
        tracked={name for name in self.git('diff','--name-only',base).splitlines() if self.allowed(name)}
        if tracked:return {'ready':True}
        base_paths=set(self.git('ls-tree','-r','--name-only',base).splitlines())
        pending=any(name not in base_paths and self.allowed(name) and (self.root/name).is_file() for name in self.state['pending'])
        return {'ready':pending}
    def review(self):
        base=self.state.get('review_base') or self.git('rev-parse','HEAD')
        tracked={n for n in self.git('diff','--name-only',base).splitlines() if self.allowed(n)}
        base_paths=set(self.git('ls-tree','-r','--name-only',base).splitlines())
        head_paths=set(self.git('ls-tree','-r','--name-only','HEAD').splitlines())
        # Git identifies tracked changes in one pass. Pending is needed only
        # for newly generated files that are not yet present in the baseline.
        names=tracked|{n for n in self.state['pending'] if n not in base_paths and self.allowed(n)}
        changes=[]
        for name in sorted(names):
            p=(self.root/name).resolve()
            if not p.is_relative_to(self.root) or not self.allowed(name): continue
            if not p.is_file():
                # A file newly added by the hosted branch is inherited below;
                # its absence from the older local checkout is not a user deletion.
                if name in tracked and name in base_paths and name in head_paths:changes.append({'path':name,'bytes':0,'new':False,'deleted':True})
                continue
            changes.append({'path':name,'bytes':p.stat().st_size,'new':name not in base_paths,'deleted':False})
        comparisons=[]
        for c in changes:
            if c['path'].endswith('.html') and not c['path'].startswith('blyg/') and not c['new']:
                diff=self.git('diff','--no-ext-diff','--no-color','--ignore-space-at-eol',base,'--',c['path'])
                if diff: comparisons.append({'path':c['path'],'diff':diff})
        signature=digest(base+json.dumps([(c['path'],'deleted' if c.get('deleted') else digest((self.root/c['path']).read_bytes())) for c in changes])+self.git('rev-parse','HEAD')+json.dumps(self.settings(),sort_keys=True))
        planned_pins=sum(1 for c in changes if re.fullmatch(r'blyg/items/[0-7][0-9a-hjkmnp-tv-z]{25}/v[0-9]+\.json',c['path']))
        report=(validate_surface(self.root,self.origin,strict_existing=False).public()
                if (self.root/'blyg/blyg.json').is_file() else None)
        return {'commit_message':self.state.get('publication_note') or self.publication_message(changes),'changes':changes,'comparisons':comparisons,'base':base,'signature':signature,'settings':self.settings(),'planned_pins':planned_pins,'conformance':report,'message':'Review these local files before publishing. Includes existing site edits.'}
    def publish(self,signature,note=None):
        pending=self.state.get('pending_publication')
        if pending:
            if self.git('branch','--show-current')!=pending['branch']:raise ValueError('The checkout is on a different branch. Publication retry stopped.')
            refs=self.connection()['refs'];remote_head=refs.split()[0] if refs else None
            if remote_head not in (None,pending['base'],pending['commit']):raise ValueError('The hosted site changed after the failed publication. Review it before trying again.')
            if remote_head!=pending['commit']:self.git('push',self.state['remote'],pending['commit']+':refs/heads/'+pending['branch'],timeout=90)
            return self.finish_publication(pending.get('inherited',[]))
        review=self.review()
        if signature!=review['signature']: raise ValueError('Files changed since review. Review again before publishing.')
        if self.git('diff','--cached','--name-only'): raise ValueError('Git already has staged changes. Please finish that Git operation before publishing from Blynger.')
        branch=self.git('branch','--show-current')
        if branch!=self.state['branch']: raise ValueError('The checkout is on a different branch. Publishing stopped.')
        connection=self.connection() # Fail before committing if the server cannot be reached.
        remote_head=connection['refs'].split()[0] if connection['refs'] else None
        if remote_head and remote_head!=review['base']:
            raise ValueError('The hosted site changed since the review. Close this window and review publication again.')
        if note is not None and (not isinstance(note,str) or len(note)>1000 or '\x00' in note): raise ValueError('Use a publication note under 1,000 characters.')
        message=(note.strip() if note is not None else self.state.get('publication_note','')) or self.publication_message(review['changes'])
        paths=[c['path'] for c in review['changes']]
        old=self.git('rev-parse','HEAD')
        inherited=self.git('diff','--name-only','--diff-filter=A',old,review['base']).splitlines()
        if paths:
            with tempfile.TemporaryDirectory(dir=self.data) as tmp:
                env={'GIT_INDEX_FILE':str(Path(tmp)/'index')}
                self.git('read-tree',review['base'],env=env)
                self.git('add','-A','-f','--',*paths,env=env)
                tree=self.git('write-tree',env=env)
                commit=self.git('commit-tree',tree,'-p',review['base'],'-m',message)
                self.git('update-ref','refs/heads/'+branch,commit,old)
                self.git('read-tree','HEAD') # Staging was checked empty; leave working files untouched.
        commit=self.git('rev-parse','HEAD')
        self.state['pending_publication']={'commit':commit,'base':review['base'],'branch':branch,'inherited':inherited};self.save_state()
        # Never force or merge automatically. A rejected push leaves this exact approved commit available to retry.
        self.git('push',self.state['remote'],commit+':refs/heads/'+branch,timeout=90)
        return self.finish_publication(inherited)
    def finish_publication(self,inherited):
        for name in inherited:
            target=(self.root/name).resolve()
            if target.is_relative_to(self.root) and not target.exists() and not any(part.startswith('.') for part in Path(name).parts):
                data=subprocess.run(['git','show','HEAD:'+name],cwd=self.root,capture_output=True,check=True).stdout
                atomic(target,data)
        docs={}
        excluded_ids={self.state['ids'][name] for name in self.non_blyg_pages|set(self.state['standalone_pages']) if name in self.state['ids']}
        for p in (self.root/'blyg/items').glob('*.json'):
            if p.name!='index.json':
                d=json.loads(p.read_text())
                if d['id'] not in excluded_ids:docs[d['id']]=d
        # Record only interactions made real by this successful publication.
        # The log is private Reader state and never enters generated site files.
        self.reader.record_publications(self.state['published'],docs)
        self.remember(docs)
        for name,draft in self.state['drafts'].items():
            if draft.get('fragments') is None and not draft.get('quotes'):
                self.state['fragment_posts'].pop(name,None)
            if draft.get('fragments') is not None or draft.get('quotes'):
                saved={'raw':draft['raw'],'fragments':copy.deepcopy(draft.get('fragments')),'quotes':copy.deepcopy(draft.get('quotes',{})),'generated':copy.deepcopy(draft.get('generated',[])),'file_hash':digest(self.path(name).read_bytes())}
                if saved.get('fragments'):
                    for row in saved['fragments'].get('ranges',[]):row.pop('pin_on_publish',None)
                for field in ('stub_of','forked_from','blogroll_snapshot'):
                    if field in draft:saved[field]=copy.deepcopy(draft[field])
                self.state['fragment_posts'][name]=saved
                if name not in self.non_blyg_pages:
                    iid=self.state['ids'][name]
                    self.state['fragment_history'].setdefault(iid,{})[str(docs[iid]['version'])]=copy.deepcopy(saved)
        # Presentation-only prepares can update the file without changing the private source.
        for name,saved in self.state['fragment_posts'].items():
            saved['file_hash']=digest(self.path(name).read_bytes())
            iid=self.state['ids'].get(name)
            if iid in docs: self.state['fragment_history'].setdefault(iid,{})[str(docs[iid]['version'])]=copy.deepcopy(saved)
        self.state['pins']={}
        self.state.pop('pending_publication',None)
        self.state.pop('publication_note',None)
        self.state['published']=docs; self.state['review_base']=self.git('rev-parse','HEAD'); self.state['drafts']={}; self.state['pending']=[]; self.save_state()
        return {'message':'Git push completed. The host’s deployment hook determines when the public site updates.'}
