"""Private block anchors for intentional fragment ranges; no protocol extensions."""
import copy, re
from bs4 import BeautifulSoup

def canonical(body):
    return ''.join(str(n) for n in BeautifulSoup(body,'html.parser').contents if str(n).strip())

def excluded(body):
    s=BeautifulSoup(body,'html.parser')
    text=s.get_text(' ',strip=True)
    return bool(s.find('h1',recursive=False) or re.match(r'^(?:[—–-]\s*|By\s+)\S+(?:\s+\S+){0,5}$',text,re.I) or re.fullmatch(r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',text))

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
    output=[]
    for pos,i in enumerate(headings):
        end=headings[pos+1] if pos+1<len(headings) else len(blocks)
        if i+1==end:
            # Empty dated headings are private authoring objects too. The UI adds
            # a paragraph when using New opener; a hand-written empty heading
            # needs prose before it can become a non-empty protocol fragment.
            continue
        heading=blocks[i]['id']; start=blocks[i+1]['id']; stop=blocks[end]['id'] if end<len(blocks) else None
        old=by_heading.get(heading) or next((r for r in prior if r.get('start')==start and r.get('end')==stop),{})
        r={**copy.deepcopy(old),'key':old.get('key',heading),'start':start,'end':stop,'heading':heading,'date_label':nodes[i].get_text(' ',strip=True),'legacy_anchor':nodes[i].get('id')}
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
