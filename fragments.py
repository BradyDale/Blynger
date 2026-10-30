"""Private block anchors for intentional fragment ranges; no protocol extensions."""
import copy
import re
import secrets
from collections import defaultdict, deque
from bs4 import BeautifulSoup, Comment
from urllib.parse import urlsplit

BLOCK_ATTR = 'data-blynger-block'
FRAGMENT_ATTR = 'data-blynger-fragment'
BREAK_ATTR = 'data-blynger-break'
MARKER_ATTRS = (BLOCK_ATTR, FRAGMENT_ATTR, BREAK_ATTR)


def _nodes(body):
    return [
        node
        for node in BeautifulSoup(body, 'html.parser').contents
        if getattr(node, 'name', None)
        and 'blynger-fragment-marker' not in node.get('class', [])
    ]


def _without_presentation(body):
    soup = BeautifulSoup(body, 'html.parser')
    for node in soup.select('.blynger-fragment-marker'):
        node.decompose()
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        if 'blynger-fragment-link-' in str(node):
            node.extract()
    return str(soup)


def _unmarked(node):
    clone = BeautifulSoup(str(node), 'html.parser').find()
    for attribute in MARKER_ATTRS:
        clone.attrs.pop(attribute, None)
    return str(clone)


def has_markers(body):
    return any(node.get(BLOCK_ATTR) for node in _nodes(body))


def remove_markers(body):
    if not any(attribute in body for attribute in MARKER_ATTRS):
        return body
    soup = BeautifulSoup(body, 'html.parser')
    for node in soup.find_all(True):
        for attribute in MARKER_ATTRS:
            node.attrs.pop(attribute, None)
    return str(soup)


def embed(meta, body):
    """Write the authoritative fragment map onto top-level article blocks."""
    if meta is None:
        return remove_markers(body)
    checked = validate(meta, clean_markers(_without_presentation(body)))
    soup = BeautifulSoup(body, 'html.parser')
    nodes = [
        node
        for node in soup.contents
        if getattr(node, 'name', None)
        and 'blynger-fragment-marker' not in node.get('class', [])
    ]
    if len(nodes) != len(checked['blocks']):
        raise ValueError('Fragment markers no longer match the article blocks.')
    membership = {}
    ids = [block['id'] for block in checked['blocks']]
    for item in checked.get('ranges', []):
        start = ids.index(item['start'])
        end = ids.index(item['end']) if item.get('end') else len(ids)
        for index in range(start, end):
            membership[index] = item['key']
    dividers = set(checked.get('dividers', []))
    for index, (node, block) in enumerate(zip(nodes, checked['blocks'])):
        for attribute in MARKER_ATTRS:
            node.attrs.pop(attribute, None)
        node[BLOCK_ATTR] = block['id']
        if index in membership:
            node[FRAGMENT_ATTR] = membership[index]
        if block['id'] in dividers:
            node[BREAK_ATTR] = ''
    return str(soup)


def extract(body, previous=None):
    """Rebuild private editor metadata from durable HTML block markers."""
    nodes = _nodes(body)
    if not nodes or not any(node.get(BLOCK_ATTR) for node in nodes):
        return None
    submitted_blocks = [
        block
        for block in (previous or {}).get('blocks', [])
        if isinstance(block, dict)
        and isinstance(block.get('id'), str)
        and isinstance(block.get('html'), str)
    ]
    prior_blocks = {
        block.get('id'): block.get('html')
        for block in submitted_blocks
    }
    ids = []
    blocks = []
    for index, node in enumerate(nodes):
        block_id = node.get(BLOCK_ATTR)
        markup = _unmarked(node)
        # A new editor block can exist for one save cycle between the private
        # block map and its durable HTML copy. The submitted map is safe to use
        # only when it identifies this exact block content. Prefer the same
        # position; fall back only to a unique unchanged block.
        if not block_id and index < len(submitted_blocks):
            candidate = submitted_blocks[index]
            if (
                candidate['id'] not in ids
                and canonical(candidate['html']) == canonical(markup)
            ):
                block_id = candidate['id']
        if not block_id:
            matches = [
                block
                for block in submitted_blocks
                if block['id'] not in ids
                and canonical(block['html']) == canonical(markup)
            ]
            if len(matches) == 1:
                block_id = matches[0]['id']
        if not block_id and excluded(str(node)):
            block_id = 'b' + secrets.token_hex(16)
        if not isinstance(block_id, str) or not re.fullmatch(
            r'[a-zA-Z0-9_-]{1,80}', block_id
        ):
            raise ValueError('A durable fragment block marker is missing or invalid.')
        if block_id in ids:
            raise ValueError('A durable fragment block marker was duplicated.')
        ids.append(block_id)
        old_markup = prior_blocks.get(block_id)
        if isinstance(old_markup, str) and canonical(old_markup) == canonical(markup):
            markup = old_markup
        blocks.append({'id': block_id, 'html': markup})
    prior = {item.get('key'): item for item in (previous or {}).get('ranges', [])}
    ranges = []
    index = 0
    while index < len(nodes):
        key = nodes[index].get(FRAGMENT_ATTR)
        if not key:
            index += 1
            continue
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', key):
            raise ValueError('A durable fragment identity is invalid.')
        end = index + 1
        while end < len(nodes) and nodes[end].get(FRAGMENT_ATTR) == key:
            end += 1
        item = copy.deepcopy(prior.get(key, {}))
        item.update(key=key, start=ids[index], end=ids[end] if end < len(ids) else None)
        ranges.append(item)
        index = end
    result = {
        'version': 1,
        'blocks': blocks,
        'dividers': [node[BLOCK_ATTR] for node in nodes if node.has_attr(BREAK_ATTR)],
        'ranges': ranges,
    }
    if (previous or {}).get('purpose'):
        result['purpose'] = previous['purpose']
    return validate(result, remove_markers(body))


def clean_markers(body):
    return remove_markers(body)


def canonical(body):
    soup = BeautifulSoup(body, 'html.parser')
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    return ''.join(str(node) for node in soup.contents if str(node).strip())

def managed_signature(body, site=None):
    """Recognize private/editor and public copies of Blynger-managed markup."""
    soup=BeautifulSoup(body,'html.parser')
    site_url=urlsplit(site) if site else None
    if site_url and site_url.netloc:
        for link in soup.select('[href]'):
            target=urlsplit(link.get('href',''))
            if target.scheme in ('http','https') and target.netloc==site_url.netloc:
                link['href']=(target.path or '/')+('?' + target.query if target.query else '')+('#' + target.fragment if target.fragment else '')
    root=next((node for node in soup.contents if getattr(node,'name',None)),None)
    if root and 'blynger-image' in root.get('class',[]):
        image=root.find('img',src=True)
        if image:
            filename=image['src'].split('?',1)[0].split('#',1)[0].rstrip('/').rsplit('/',1)[-1]
            image['src']='blynger-media:'+filename
    return canonical(str(soup))

def website_attribution(soup):
    """A linked domain credited after a dash is a source, not a byline."""
    text = soup.get_text(' ', strip=True)
    credit = re.sub(r'^[—–-]\s*', '', text).strip()
    if credit == text:
        return False
    links = soup.find_all('a', href=True)
    if len(links) != 1 or re.sub(r'^[—–-]\s*', '', links[0].get_text(' ', strip=True)).strip() != credit:
        return False
    target = urlsplit(links[0]['href'])
    return (
        target.scheme in ('http', 'https')
        and target.hostname is not None
        and credit.lower().removeprefix('www.')
        == target.hostname.lower().removeprefix('www.')
    )


def excluded(body):
    s=BeautifulSoup(body,'html.parser')
    text=s.get_text(' ',strip=True)
    managed=s.select_one('.blynger-series-title, .blynger-series-next')
    return bool(managed or s.find('h1',recursive=False) or (not website_attribution(s) and re.match(r'^(?:[—–-]\s*|By\s+)\S+(?:\s+\S+){0,5}$',text,re.I)) or re.fullmatch(r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',text))

def validate(meta,body):
    if meta is None: return None
    m=copy.deepcopy(meta)
    if not isinstance(m,dict) or m.get('version')!=1: raise ValueError('Unsupported fragment draft format.')
    blocks=m.get('blocks',[]); dividers=m.get('dividers',[]); ranges=m.get('ranges',[])
    if not isinstance(blocks,list) or len(blocks)>10000: raise ValueError('Invalid fragment blocks.')
    ids=[]
    for b in blocks:
        if not isinstance(b,dict) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',b.get('id','')) or not isinstance(b.get('html'),str): raise ValueError('Invalid fragment anchor.')
        ids.append(b['id'])
    if len(set(ids))!=len(ids): raise ValueError('Duplicate fragment anchors.')
    if canonical(''.join(b['html'] for b in blocks))!=canonical(body): raise ValueError('Fragment anchors no longer match the article. Return to Write to review the fragment boundaries before saving.')
    if len(set(dividers))!=len(dividers) or any(d not in ids for d in dividers): raise ValueError('Blynger could not match a fragment break to a paragraph. Undo the paragraph merge, then remove that fragment break before editing it again.')
    occupied=set(); keys=set()
    for r in ranges:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',r.get('key','')) or r['key'] in keys: raise ValueError('Invalid fragment identity.')
        keys.add(r['key'])
        if r.get('start') not in ids or (r.get('end') is not None and r['end'] not in ids): raise ValueError('A fragment boundary was deleted. Review the fragments before saving.')
        a=ids.index(r['start']); z=ids.index(r['end']) if r.get('end') else len(ids)
        if z<=a or occupied.intersection(range(a,z)): raise ValueError('Fragment ranges overlap or have reversed boundaries.')
        if any(excluded(b['html']) for b in blocks[a:z]): raise ValueError('Titles, signatures, and dates cannot be fragments.')
        occupied.update(range(a,z))
    return separate_quotes(m)

def repair_editor_anchors(meta):
    """Discard orphaned editor-only dividers; fragment ranges stay authoritative."""
    if not isinstance(meta,dict) or not isinstance(meta.get('blocks'),list):return meta
    m=copy.deepcopy(meta);ids={b.get('id') for b in m['blocks'] if isinstance(b,dict)};seen=set();clean=[]
    for divider in m.get('dividers',[]):
        if divider in ids and divider not in seen:clean.append(divider);seen.add(divider)
    m['dividers']=clean
    return m

def rebase_managed(meta,body,site=None):
    """Rebase anchors after Blynger changes only its own page furniture.

    Exact authored blocks retain their ids and therefore their fragment
    identities. Newly generated Series blocks receive fresh private anchors.
    A missing range boundary is still an error; this helper never guesses that
    authored text was moved or replaced.
    """
    if meta is None:
        return None
    m=copy.deepcopy(meta)
    matches=defaultdict(deque)
    old_managed=set()
    for block in m.get('blocks',[]):
        if not isinstance(block,dict) or not isinstance(block.get('html'),str):
            continue
        matches[managed_signature(block['html'],site)].append(block['id'])
        if excluded(block['html']) and BeautifulSoup(block['html'],'html.parser').select_one('.blynger-series-title, .blynger-series-next'):
            old_managed.add(block['id'])
    for item in m.get('ranges',[]):
        if item.get('end') in old_managed:
            item['end']=None
    nodes=[node for node in BeautifulSoup(_without_presentation(body),'html.parser').contents if str(node).strip()]
    blocks=[]
    used=set()
    for node in nodes:
        markup=str(node)
        pool=matches[managed_signature(markup,site)]
        block_id=pool.popleft() if pool else 'b'+secrets.token_hex(16)
        while block_id in used:
            block_id='b'+secrets.token_hex(16)
        used.add(block_id)
        blocks.append({'id':block_id,'html':markup})
    m['blocks']=blocks
    ids=[block['id'] for block in blocks]
    ranges=m.get('ranges',[])
    for index,item in enumerate(ranges):
        if item.get('end') in ids:
            continue
        # Adjacent fragments commonly share a boundary: one range ends where
        # the next begins. If an older HTML normalization changed that exact
        # boundary block, the next surviving start is the only non-guessing
        # replacement and preserves both fragment identities.
        start=ids.index(item['start']) if item.get('start') in ids else -1
        following=next((later.get('start') for later in ranges[index+1:] if later.get('start') in ids and ids.index(later['start'])>start),None)
        if following:
            item['end']=following
    for item in m.get('ranges',[]):
        if item.get('start') not in ids:
            continue
        start=ids.index(item['start'])
        end=ids.index(item['end']) if item.get('end') in ids else len(ids)
        managed=next((block['id'] for block in blocks[start:end] if excluded(block['html'])),None)
        if managed:
            item['end']=managed
    m=repair_editor_anchors(m)
    return validate(m,_without_presentation(body))

def separate_quotes(meta):
    """Keep existing transclusions in the thread, splitting only designated ranges."""
    if meta.get("purpose")=="openers":return meta
    m=copy.deepcopy(meta);out=[];blocks=m["blocks"];ids=[b["id"] for b in blocks]
    def quoted(b):
        soup=BeautifulSoup(b["html"],"html.parser")
        return "![[" in soup.get_text() or bool(soup.select("blockquote.blyg-transclusion,blockquote.blynger-citation"))
    for r in m["ranges"]:
        a=ids.index(r["start"]);z=ids.index(r["end"]) if r.get("end") else len(ids)
        if not any(quoted(b) for b in blocks[a:z]):out.append(r);continue
        start=None;used_key=False
        for i in range(a,z+1):
            stop=i==z or quoted(blocks[i])
            if stop and start is not None:
                first=ids[start];key=r["key"] if not used_key else first
                out.append({**r,"key":key,"start":first,"end":ids[i] if i<len(ids) else None});used_key=True
                if first not in m["dividers"]:m["dividers"].append(first)
                start=None
            if i<z and not stop and start is None:start=i
    m["ranges"]=out
    return m

def ranges(meta):
    ids=[b['id'] for b in meta['blocks']]
    for r in sorted(meta['ranges'],key=lambda r:ids.index(r['start'])):
        a=ids.index(r['start']); z=ids.index(r['end']) if r.get('end') else len(ids)
        yield r,a,z,''.join(b['html'] for b in meta['blocks'][a:z])


def openers_metadata(body, previous=None, submitted=None):
    """Adapt dated Openers sections to the SAME block/range model used by posts.

    Date headings and original public anchors stay in the page, outside fragment
    prose. No Blyg IDs, timestamps or publication history are allocated here.
    """
    import secrets
    from collections import defaultdict, deque
    from bs4 import Tag
    previous=previous or {}
    nodes=[n for n in BeautifulSoup(body,'html.parser').contents if str(n).strip()]
    htmls=[str(n) if isinstance(n,Tag) else n.output_ready() for n in nodes]
    # Browsers may repair legacy HTML into a different number of top-level
    # elements while leaving the rendered article unchanged.  A submitted
    # block map is reusable only when it also matches the server-side layout;
    # otherwise rebuild the map below instead of trapping the author's draft.
    if submitted and len(submitted.get('blocks',[]))==len(nodes) and canonical(''.join(b['html'] for b in submitted.get('blocks',[])))==canonical(body):
        blocks=copy.deepcopy(submitted['blocks'])
    else:
        old=previous.get('blocks',[]); matches=defaultdict(deque)
        for b in old: matches[b['html']].append(b['id'])
        blocks=[{'id':matches[h].popleft() if matches[h] else None,'html':h} for h in htmls]
        used={b['id'] for b in blocks if b['id']}
        for i,b in enumerate(blocks):
            # In-place edits retain their block anchor; insertions match unchanged blocks first.
            if not b['id']:
                candidate=old[i]['id'] if len(old)==len(blocks) else None
                b['id']=candidate if candidate and candidate not in used else 'b'+secrets.token_hex(16)
                used.add(b['id'])
    if len(blocks)!=len(nodes): raise ValueError('Openers block layout is inconsistent. Reopen the draft before saving.')
    headings=[i for i,n in enumerate(nodes) if isinstance(n,Tag) and (n.name=='h3' or (n.name=='strong' and excluded(str(n))))]
    prior=(submitted or previous).get('ranges',[])
    by_heading={r.get('heading'):r for r in prior if r.get('heading')}
    known_by_heading={r.get('heading'):r for r in previous.get('ranges',[]) if r.get('heading')}
    valid_identity=lambda value:isinstance(value,str) and bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value))
    persisted_keys={r.get('key') for r in previous.get('ranges',[]) if valid_identity(r.get('key'))}
    output=[];used_keys=set()
    for pos,i in enumerate(headings):
        end=headings[pos+1] if pos+1<len(headings) else len(blocks)
        if i+1==end:
            # Empty dated headings are private authoring objects too. The UI adds
            # a paragraph when using New opener; a hand-written empty heading
            # needs prose before it can become a non-empty protocol fragment.
            continue
        heading=blocks[i]['id']; start=blocks[i+1]['id']; stop=blocks[end]['id'] if end<len(blocks) else None
        old=by_heading.get(heading) or next((r for r in prior if r.get('start')==start and r.get('end')==stop),{})
        known=known_by_heading.get(heading) or next((r for r in previous.get('ranges',[]) if r.get('start')==start and r.get('end')==stop),{})
        # A browser-only key must never prevent an Opener save. Existing
        # persisted identities remain authoritative; a malformed unsaved key
        # is safely rebuilt from the durable heading block.
        if valid_identity(known.get('key')):
            key=known['key']
        else:
            key=next((candidate for candidate in (old.get('key'),heading) if valid_identity(candidate) and candidate not in persisted_keys and candidate not in used_keys),None)
        if key is None:
            key='b'+secrets.token_hex(16)
        used_keys.add(key)
        r={**copy.deepcopy(old),'key':key,'start':start,'end':stop,'heading':heading,'date_label':nodes[i].get_text(' ',strip=True),'legacy_anchor':nodes[i].get('id')}
        output.append(r)
    result={'version':1,'purpose':'openers','blocks':blocks,'dividers':[blocks[i]['id'] for i in headings],'ranges':output}
    return validate(result,body)


def designate_sections(meta):
    """Resolve explicit dividers into shared ranges with implicit body edges."""
    m=copy.deepcopy(meta);blocks=m['blocks'];out=[];start=None
    for i in range(len(blocks)+1):
        block=blocks[i] if i<len(blocks) else None
        stop=block is None or excluded(block['html']) or block['id'] in m['dividers']
        if stop and start is not None:
            body=''.join(b['html'] for b in blocks[start:i]);soup=BeautifulSoup(body,'html.parser')
            if soup.get_text(strip=True) or soup.find(['img','audio','video']):
                first=blocks[start]['id'];end=block['id'] if block else None
                old=next((r for r in m['ranges'] if r['start']==first),{})
                out.append({**old,'key':old.get('key',first),'start':first,'end':end})
            start=None
        if block is not None and not excluded(block['html']) and start is None:start=i
    m['ranges']=out
    return validate(m,''.join(b['html'] for b in blocks))
