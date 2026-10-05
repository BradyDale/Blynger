"""Head-only metadata updates; article markup and historical dates are preserved."""
import html,json,re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from PIL import Image

from version import APP_VERSION, BLYG_VERSION
from configuration import DEFAULT_SETTINGS
PROTOCOL=BLYG_VERSION

def valid_date(value):
    try:
        datetime.fromisoformat(value.replace('Z','+00:00'))
        return value
    except (ValueError,AttributeError): return None

def discovery_markup(config,blyg=False,rss=False,item_json=None):
    lines=[]
    if blyg:lines.append('<link rel="blyg" href="/blyg/">')
    if rss:lines.append('<link rel="alternate" type="application/rss+xml" title="'+html.escape(config['blyg_title'],quote=True)+'" href="/feed.xml">')
    if item_json:lines.append('<link rel="alternate" type="application/json" href="'+html.escape(item_json,quote=True)+'">')
    return '\n'.join(lines)

def favicon_markup(config):
    return '<link rel="icon" type="image/png" href="'+html.escape(config['favicon'],quote=True)+'">' if config.get('favicon') else ''

def enrich(raw,name,root,published=None,modified=None,standalone=False,config=None,item_json=None,blyg_item=None,blyg_discovery=None,rss_discovery=None):
    config=config or DEFAULT_SETTINGS; site=config['site_url'].rstrip('/')+'/'; author=config['author_name']
    main_pages=set(config.get('main_pages',[]))
    if blyg_item is None:blyg_item=not standalone and name not in main_pages
    if blyg_discovery is None:blyg_discovery=blyg_item or name=='index.html'
    if rss_discovery is None:rss_discovery=not standalone
    head=re.search(r'<head\b[^>]*>(.*?)</head\s*>',raw,re.I|re.S)
    if not head: raise ValueError(name+': missing HTML head; metadata was not changed.')
    soup=BeautifulSoup(raw,'html.parser'); tags={m.get('property') or m.get('name'):m.get('content','') for m in soup.find_all('meta')}
    title_node=soup.find('h1') or soup.title
    title=title_node.get_text(' ',strip=True) if title_node else name
    article=soup.find('article') or soup.body or soup
    description=tags.get('description') or tags.get('og:description') or tags.get('twitter:description')
    # Generated summaries track edits; hand-written legacy descriptions are preserved.
    if tags.get('blynger:description-source')=='auto' or not description or len(description.strip())<20 or description in ('en_US','Are you ready to change your life?'):
        candidates=[p for p in article.find_all('p') if not p.find_parent(['nav','footer']) and not p.find_parent(id='blynger-versions')]
        # Prefer the author's own prose. Quote attribution and quoted source text
        # should not become the summary when a response follows the quotation.
        own=[p for p in candidates if not p.find_parent('blockquote') and 'blynger-quote-author' not in p.get('class',[])]
        quoted=[p for p in candidates if 'blynger-quote-author' not in p.get('class',[])]
        paragraphs=[p.get_text(' ',strip=True) for p in (own or quoted)]
        description=next((p for p in paragraphs if len(p)>30),title)
        description=re.sub(r'\s+',' ',description)
        if len(description)>170: description=description[:167].rsplit(' ',1)[0]+'…'
        desc_source='auto'
    else: desc_source='custom'
    canonical=site if name=='index.html' else site+name
    def normalize_image(value):
        if not value:return None
        url=urljoin(site,value); parsed=urlsplit(url)
        if parsed.scheme not in ('http','https'):return None
        if parsed.hostname in set(config.get('local_hostnames',[])):
            path=(Path(root)/unquote(parsed.path).lstrip('/')).resolve()
            if not path.is_relative_to(Path(root).resolve()) or not path.is_file():return None
            return site+path.relative_to(Path(root).resolve()).as_posix()
        return url
    image=normalize_image(tags.get('og:image') or tags.get('twitter:image'))
    if not image:
        image=next((u for im in article.find_all('img') if not im.find_parent('nav') and not im.find_parent('a') and (u:=normalize_image(im.get('src')))),None)
    image=image or next((normalize_image(value) for value in config.get('default_images',[]) if normalize_image(value)),None)
    image_alt=tags.get('og:image:alt') or ''
    for im in soup.find_all('img'):
        if image and normalize_image(im.get('src'))==image and im.get('alt'):image_alt=im['alt'];break
    if image and not image_alt:image_alt=author if image in [normalize_image(v) for v in config.get('default_images',[])] else 'Image accompanying '+title
    date=valid_date(tags.get('article:published_time')) or valid_date(published)
    site_page=name in set(config.get('main_pages',[])) or standalone
    if not site_page:
        # Recover the byline date, never replace an old date with migration time.
        tail=article.get_text(' ',strip=True)[-650:]
        if date: tail=tail.split(author,1)[-1] if author in tail else ''
        matches=re.findall(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',tail)
        if matches:
            try:
                byline=datetime.strptime(matches[-1].replace(',',''),'%B %d %Y').date().isoformat()
                if not date or date[:10]!=byline: date=byline
            except ValueError:pass
    updated=valid_date(modified) or valid_date(tags.get('article:modified_time')) or date
    # Preserve the page's original generator so an app upgrade alone does not
    # rewrite every published HTML file.
    generator=tags.get('generator') or 'Blynger '+APP_VERSION
    metas={'description':description,'author':author,'generator':generator,'blynger:description-source':desc_source,'twitter:card':'summary_large_image' if image else 'summary','twitter:title':title,'twitter:description':description}
    if config.get('twitter_creator'):metas['twitter:creator']=config['twitter_creator']
    if blyg_item: metas['blyg:protocol-version']=PROTOCOL
    props={'og:title':title,'og:type':'website' if site_page else 'article','og:url':canonical,'og:description':description,'og:site_name':config.get('site_label') or author,'og:locale':'en_US'}
    if image:
        props.update({'og:image':image,'og:image:alt':image_alt});metas.update({'twitter:image':image,'twitter:image:alt':image_alt})
        if urlsplit(image).hostname in set(config.get('local_hostnames',[])):
            try:
                with Image.open(Path(root)/unquote(urlsplit(image).path).lstrip('/')) as im:
                    props.update({'og:image:width':str(im.width),'og:image:height':str(im.height)})
            except OSError:pass
    if not site_page:
        props['article:author']=site
        if date:props['article:published_time']=date
        if updated:props['article:modified_time']=updated
    schema={'@context':'https://schema.org','@type':'WebSite' if name=='index.html' else 'WebPage' if site_page else 'BlogPosting','name':title,'description':description,'url':canonical,'author':{'@type':'Person','name':author,'url':site}}
    if not site_page:
        schema['headline']=title;schema['mainEntityOfPage']=canonical
        if date:schema['datePublished']=date
        if updated:schema['dateModified']=updated
    if image:schema['image']=image
    oldhead=head.group(1)
    # Some hand-written pages used typographic quotation marks around HTML
    # attributes. Browsers ignore those obsolete Open Graph tags; remove them
    # before writing the valid metadata block below.
    oldhead=re.sub(r'<meta\b[^>]*(?:property|name)\s*=\s*[“”][^>]*>[ \t]*(?:\r?\n)?','',oldhead,flags=re.I)
    def remove_meta(m):
        node=BeautifulSoup(m.group(),'html.parser').find('meta')
        keymatch=re.search(r'(?:property|name)\s*=\s*[\"\']([^\"\']+)',m.group(),re.I)
        key=keymatch.group(1) if keymatch else ''
        return '' if key in metas or key.startswith(('og:','twitter:','article:','blyg:','blynger:')) else m.group()
    oldhead=re.sub(r'<meta\b[^>]*>[ \t]*(?:\r?\n)?',remove_meta,oldhead,flags=re.I)
    def remove_link(m):
        node=BeautifulSoup(m.group(),'html.parser').find('link'); rel=node.get('rel',[])
        managed_alternate='alternate' in rel and node.get('type') in ('application/rss+xml','application/json')
        return '' if any(r in rel for r in ('canonical','blyg','icon')) or managed_alternate else m.group()
    oldhead=re.sub(r'<link\b[^>]*>[ \t]*(?:\r?\n)?',remove_link,oldhead,flags=re.I)
    oldhead=re.sub(r'<script\b[^>]*id=[\"\']blynger-structured-data[\"\'][^>]*>.*?</script\s*>[ \t]*(?:\r?\n)?','',oldhead,flags=re.I|re.S)
    oldhead=re.sub(r'(?:\r?\n)?<title\b[^>]*>.*?</title\s*>[ \t]*(?:\r?\n)?','',oldhead,flags=re.I|re.S)
    lines=['<title>'+html.escape(title)+'</title>']
    if favicon_markup(config):lines.append(favicon_markup(config))
    lines += ['<meta '+kind+'="'+key+'" content="'+html.escape(str(value),quote=True)+'">' for kind,data in [('name',metas),('property',props)] for key,value in data.items()]
    lines += ['<link rel="canonical" href="'+canonical+'">']
    links=discovery_markup(config,blyg_discovery,rss_discovery,item_json)
    if links:lines.extend(links.splitlines())
    lines += ['<script type="application/ld+json" id="blynger-structured-data">'+json.dumps(schema,ensure_ascii=False).replace('<','\\u003c')+'</script>']
    return raw[:head.start(1)]+oldhead.rstrip()+'\n'+'\n'.join(lines)+'\n'+raw[head.end(1):]

def sitemap(names,site=None):
    site=(site or DEFAULT_SETTINGS['site_url']).rstrip('/')+'/'
    root=ET.Element('urlset',xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    for name in sorted(set(names)):
        node=ET.SubElement(root,'url');ET.SubElement(node,'loc').text=site if name=='index.html' else site+name
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)
