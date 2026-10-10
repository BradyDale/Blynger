"""Render TK prose without permitting model-supplied active HTML."""
import html
import re
import markdown
from bs4 import BeautifulSoup, NavigableString
from core import clean

URL=re.compile(r'(?<![\w"\'=])https?://[^\s<>]+')

def linkify(markup):
    """Link bare web addresses without reintroducing a second sanitizer."""
    soup=BeautifulSoup(markup,'html.parser')
    for node in list(soup.find_all(string=True)):
        if node.find_parent(['a','pre','code']):continue
        text=str(node);matches=list(URL.finditer(text))
        if not matches:continue
        pieces=[];at=0
        for match in matches:
            url=match.group(0).rstrip('.,;:!?)]}')
            if not url:continue
            end=match.start()+len(url)
            pieces.append(NavigableString(text[at:match.start()]))
            link=soup.new_tag('a',href=url);link.string=url;pieces.append(link);at=end
        pieces.append(NavigableString(text[at:]));node.replace_with(*pieces)
    return str(soup)


def render_tk(prose):
    # Escape raw HTML before Markdown interpretation; sanitize the resulting links.
    rendered=markdown.markdown(html.escape(prose,quote=False),extensions=['sane_lists','nl2br'])
    rendered=linkify(clean(rendered))
    return '<div class="blyg-tk-gen">'+rendered+'</div>'
