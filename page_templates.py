"""Small HTML templates and forward-only presentation styles.

Keeping presentation strings here makes the publication engine easier to
review. These constants are intentionally stable because old pages retain the
design they were published with.
"""

import html
import re

from configuration import DEFAULT_SETTINGS


GENERATED_STYLE = (
    '<style id="blynger-generation-style">'
    '.blyg-tk-gen{position:relative;background:#f2f2f2;border:1px dashed #505050;'
    'margin:1em 0 1.4em;padding:.65em .8em 1.15em}'
    '.blyg-tk-gen::after{content:"";position:absolute;box-sizing:border-box;'
    'left:.65em;bottom:-14px;width:30px;height:27px;border:1px solid #444;'
    'background:#fff center/20px 20px no-repeat '
    'url("data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 '
    'width=%2224%22 height=%2224%22 viewBox=%220 0 24 24%22 fill=%22none%22 '
    'stroke=%22%23111%22 stroke-width=%221.7%22 stroke-linecap=%22round%22 '
    'stroke-linejoin=%22round%22%3E%3Cpath d=%22M12 8V4H8%22/%3E%3Crect '
    'width=%2216%22 height=%2212%22 x=%224%22 y=%228%22 rx=%222%22/%3E%3Cpath '
    'd=%22M2 14h2M20 14h2M15 13v2M9 13v2%22/%3E%3C/svg%3E")}'
    '.blyg-tk-gen> :first-child{margin-top:0}'
    '.blyg-tk-gen> :last-child{margin-bottom:0}'
    'img{max-width:100%}'
    '</style>'
)

QUOTE_STYLE = (
    '<style id="blynger-quote-style">'
    'blockquote.blyg-transclusion,blockquote.blynger-citation{background:#eee;'
    'border:1px solid #ddd;margin:1em 0;padding:.75em 1em;overflow-wrap:anywhere}'
    'blockquote.blyg-transclusion> :first-child{margin-top:0}'
    'blockquote.blyg-transclusion> :last-child{margin-bottom:0}'
    '.blynger-quote-title{font-size:1em;margin:0 0 .35em}'
    '.blynger-quote-author{font-size:.85em;margin:0 0 1em}'
    '.blynger-blockquote-source{display:block;margin-top:.65em;text-align:right;'
    'font:13px/1.4 Tahoma,Verdana,sans-serif}'
    '</style>'
)

FRAGMENT_DOT_STYLE = (
    '<style id="blynger-fragment-dot-style">'
    '.blynger-fragment-marker{display:block;position:relative;height:0;margin:0;'
    'padding:0;border:0}'
    '.blynger-fragment-marker a{position:absolute;right:-17px;top:0;width:14px;'
    'height:14px;border:0;text-decoration:none!important;background:none;color:#90958b}'
    '.blynger-fragment-marker a::after{content:"";position:absolute;top:5px;left:5px;'
    'width:4px;height:4px;border-radius:50%;background:currentColor}'
    '.blynger-fragment-marker a:focus-visible{outline:1px dotted currentColor;'
    'outline-offset:2px}'
    '</style>'
)

IMAGE_STYLE = (
    '<style id="blynger-image-style">'
    '.blynger-image{text-align:center}'
    '.blynger-image img{display:block;height:auto;max-width:100%;margin-left:auto;'
    'margin-right:auto}'
    '.blynger-image-standard img{width:min(400px,77vw)}'
    '.blynger-image-small img{width:min(200px,50vw)}'
    '.blynger-image-wide img{width:77vw}'
    '.blynger-image-full img{width:100%}'
    '</style>'
)

ALIGN_STYLE = '<style id="blynger-alignment-style">.blynger-centered{text-align:center}</style>'


def post_navigation(config=None):
    """Render the site's configured image navigation."""
    links = (config or DEFAULT_SETTINGS).get("navigation", [])
    anchors = []
    for item in links:
        anchors.append(
            '<a href="{}"><img src="/images/{}" alt="{}"></a>'.format(
                item["url"], item["image"], html.escape(item["label"], quote=True)
            )
        )
    return '<nav aria-label="Site navigation">' + "".join(anchors) + "</nav>"


def restore_post_navigation(raw, name, config=None):
    """Repair Blynger's known post template without touching custom layouts."""
    settings = config or DEFAULT_SETTINGS
    if name in set(settings.get("main_pages", [])):
        return raw

    article = re.search(r"<article\b", raw, re.I)
    if not article:
        return raw
    top = next(
        (
            match
            for match in re.finditer(
                r"<nav\b[^>]*>.*?</nav\s*>", raw[: article.start()], re.I | re.S
            )
            if "/images/home.JPG" in match.group()
        ),
        None,
    )
    if not top:
        return raw

    raw = raw[: top.start()] + post_navigation(config) + raw[top.end() :]
    end = re.search(r"</article\s*>", raw, re.I)
    if end and "/images/home.JPG" not in raw[end.end() :]:
        raw = raw[: end.end()] + post_navigation(config) + raw[end.end() :]
    return raw


def new_page(title, body, config=None):
    """Create the intentionally small default document used for new pages."""
    page_style = (
        "body{font:125%/1.5 Menlo,monospace;margin:25px}"
        "article{max-width:768px;margin:auto}"
        "a{color:blue}img{max-width:100%}"
        "nav{text-align:center;margin:20px}"
        "nav img{width:18%;height:55px}"
    )
    navigation = post_navigation(config)
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width"><title>'
        + html.escape(title)
        + "</title><style>"
        + page_style
        + "</style>"
        + GENERATED_STYLE
        + "</head><body>"
        + navigation
        + "<article><h1>"
        + html.escape(title)
        + "</h1>"
        + body
        + "</article>"
        + navigation
        + "</body></html>"
    )


# Historical public names retained for internal callers and third-party tests.
STYLE = GENERATED_STYLE
