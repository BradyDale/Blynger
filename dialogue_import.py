"""Safely turn a pasted ChatGPT dialogue into authored and TK passages."""
import html
import markdown
from bs4 import BeautifulSoup, NavigableString

from core import clean, now
from tk_render import normalize_links

ROLES={'author','assistant'}


def _safe_turn(turn):
    role=turn.get('role') if isinstance(turn,dict) else None
    if role not in ROLES:raise ValueError('Every dialogue turn must be Brady or ChatGPT.')
    rich=turn.get('html')
    text=turn.get('text')
    if rich is not None:
        if not isinstance(rich,str):raise ValueError('Dialogue HTML must be text.')
        rendered=clean(rich)
    elif isinstance(text,str):
        rendered=clean(markdown.markdown(html.escape(text,quote=False),extensions=['sane_lists','nl2br']))
    else:raise ValueError('Every dialogue turn needs text.')
    rendered=normalize_links(rendered)
    soup=BeautifulSoup(rendered,'html.parser')
    # Imported markup cannot declare itself generated. Blynger owns that claim
    # and adds it only around turns the author identifies as ChatGPT.
    for node in soup.find_all(True):
        for attribute in ('class','id'):
            if node.has_attr(attribute):del node[attribute]
        for key in list(node.attrs):
            if key.startswith('data-generated') or key.startswith('data-blynger-'):del node[key]
    for node in list(soup.contents):
        if isinstance(node,NavigableString) and node.strip():
            paragraph=soup.new_tag('p');paragraph.string=str(node);node.replace_with(paragraph)
    return role,str(soup).strip()


def render_dialogue(turns, model=None):
    """Return editor HTML plus one disclosure record per assistant turn."""
    if not isinstance(turns,list) or not turns or len(turns)>200:
        raise ValueError('Paste between 1 and 200 dialogue turns.')
    if len(str(turns))>300000:raise ValueError('That dialogue is too large to import at once.')
    if model is not None and not isinstance(model,str):
        raise ValueError('The self-reported model name must be text.')
    model=(model or '').strip()
    if len(model)>100 or any(ord(character)<32 for character in model):
        raise ValueError('Keep the self-reported model name under 100 characters.')
    disclosed_model=model or 'ChatGPT import (model not stated)'
    safe=[]
    for turn in turns:
        role,markup=_safe_turn(turn)
        if not BeautifulSoup(markup,'html.parser').get_text(' ',strip=True):continue
        safe.append((role,markup))
    if not safe:raise ValueError('The pasted dialogue contains no writing.')
    imported_at=now();parts=[];generated=[]
    for role,markup in safe:
        if role=='assistant':
            parts.append('<div class="blyg-tk-gen">'+markup+'</div>')
            generated.append({'sources':[],'model':disclosed_model,'at':imported_at})
        else:parts.append(markup)
    return {'html':'\n'.join(parts),'generated':generated,'turns':len(safe)}
