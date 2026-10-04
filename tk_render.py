"""Render TK prose without permitting model-supplied active HTML."""
import html
import bleach
import markdown
from core import clean


def render_tk(prose):
    # Escape raw HTML before Markdown interpretation; sanitize the resulting links.
    rendered=markdown.markdown(html.escape(prose,quote=False),extensions=['sane_lists','nl2br'])
    rendered=bleach.linkify(clean(rendered),skip_tags=['pre','code'],parse_email=False)
    return '<div class="blyg-tk-gen">'+rendered+'</div>'
