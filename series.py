"""Private series records and managed static-page decorations.

This module knows how a Series looks on human HTML pages.  It does not own
feeds, Blyg objects, publication, or Git; core.Studio coordinates those.
"""

import html
import re
import unicodedata
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


SUBTITLE_START = "<!-- blynger-series-subtitle-start -->"
SUBTITLE_END = "<!-- blynger-series-subtitle-end -->"
NEXT_START = "<!-- blynger-series-next-start -->"
NEXT_END = "<!-- blynger-series-next-end -->"
STYLE_START = "<!-- blynger-series-style-start -->"
STYLE_END = "<!-- blynger-series-style-end -->"
ENTRIES_START = "<!-- blynger-series-entries-start -->"
ENTRIES_END = "<!-- blynger-series-entries-end -->"


def slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value[:60] or "series"


def clean_managed(raw):
    for start, end in (
        (SUBTITLE_START, SUBTITLE_END),
        (NEXT_START, NEXT_END),
        (STYLE_START, STYLE_END),
    ):
        raw = re.sub(re.escape(start) + r".*?" + re.escape(end), "", raw, flags=re.S)
    return raw


def _remove_old_next(raw, plug):
    """Remove the owner's existing hand-made NEXT PLUG paragraph."""
    soup = BeautifulSoup(raw, "html.parser")
    target = "next " + plug.casefold().rstrip(":")
    for node in list(soup.find_all(["p", "div"])):
        text = node.get_text(" ", strip=True).casefold()
        if text.startswith(target):
            node.decompose()
    return str(soup)


def canonical_title(value, series_title, include=True):
    """Return one stable, managed series suffix without duplicating it."""
    value = str(value).strip()
    pattern = r"\s*:\s*" + re.escape(series_title.strip()) + r"\s*$"
    while re.search(pattern, value, flags=re.I):
        value = re.sub(pattern, "", value, flags=re.I).rstrip()
    return value + (": " + series_title.strip() if include else "")


def _set_headline(raw, series_title, include=True):
    soup = BeautifulSoup(raw, "html.parser")
    article = soup.find("article")
    heading = article.find("h1") if article else None
    if not heading:
        raise ValueError("A series post needs one article headline.")
    title = canonical_title(heading.get_text(" ", strip=True), series_title, include)
    heading.clear()
    heading.string = title
    return str(soup)


def undecorate_post(raw, plug, series_title=None):
    """Remove only the Series furniture Blynger owns from a former member."""
    raw = _remove_old_next(clean_managed(raw), plug)
    return _set_headline(raw, series_title, include=False) if series_title else raw


def decorate_post(raw, series, next_member=None, homepage_only_title=False):
    raw = _remove_old_next(clean_managed(raw), series["plug"])
    style = STYLE_START + '<style>.blynger-series-title{text-align:right}</style>' + STYLE_END
    raw = raw.replace("</head>", style + "</head>", 1)
    soup = BeautifulSoup(raw, "html.parser")
    article = soup.find("article")
    heading = article.find("h1") if article else None
    if not heading:
        raise ValueError("A series post needs one article headline.")
    # Older Blynger builds emitted the same Series subtitle without managed
    # boundary comments. Absorb that exact legacy furniture before adding the
    # durable managed form so a later installment cannot duplicate it.
    for node in list(article.select("h3.blynger-series-title")):
        link = node.find("a", href=True)
        link_path = urlsplit(link.get("href", "")).path.lstrip("/") if link else ""
        if link_path == series["page"] and node.get_text(" ", strip=True).casefold() == series["title"].strip().casefold():
            node.decompose()
    title = canonical_title(
        heading.get_text(" ", strip=True),
        series["title"],
        include=False,
    )
    heading.clear()
    heading.string = title
    subtitle = BeautifulSoup(
        SUBTITLE_START
        + '<h3 class="blynger-series-title"><i><a href="/'
        + html.escape(series["page"], quote=True)
        + '">'
        + html.escape(series["title"])
        + "</a></i></h3>"
        + SUBTITLE_END,
        "html.parser",
    )
    heading.insert_after(subtitle)
    if next_member:
        label = "Next " + series["plug"] + ": "
        navigation = BeautifulSoup(
            NEXT_START
            + '<p class="blynger-series-next"><b>'
            + html.escape(label)
            + '</b><a href="/'
            + html.escape(next_member["name"], quote=True)
            + '">'
            + html.escape(next_member["title"])
            + "</a></p>"
            + NEXT_END,
            "html.parser",
        )
        versions = article.find(string=lambda value: isinstance(value, str) and "blynger-versions-start" in value)
        if versions:
            versions.insert_before(navigation)
        else:
            article.append(navigation)
    return str(soup)


def series_entries(members, series_title=None):
    rows = []
    for member in members:
        detail = " — " + html.escape(member["attribute"]) if member.get("attribute") else ""
        rows.append(
            '<li><a href="/'
            + html.escape(member["name"], quote=True)
            + '">'
            + html.escape(canonical_title(member["title"], series_title, include=False) if series_title else member["title"])
            + "</a>"
            + detail
            + "</li>"
        )
    return (
        ENTRIES_START
        + '<ol class="blynger-series-entries">'
        + "".join(rows)
        + "</ol>"
        + ENTRIES_END
    )


def series_body(series, members):
    description = "".join(str(node) for node in BeautifulSoup(series["description"], "html.parser").contents)
    return (
        '<section class="blynger-series-description">'
        + description
        + "</section>"
        + series_entries(members, series["title"])
    )


def update_series_page(raw, members, series_title=None):
    """Replace only Blynger's managed installment list, preserving authored prose."""
    entries = series_entries(members, series_title)
    pattern = re.escape(ENTRIES_START) + r".*?" + re.escape(ENTRIES_END)
    if re.search(pattern, raw, flags=re.S):
        return re.sub(pattern, lambda _: entries, raw, count=1, flags=re.S)
    soup = BeautifulSoup(raw, "html.parser")
    old = soup.select_one("ol.blynger-series-entries")
    replacement = BeautifulSoup(entries, "html.parser")
    if old:
        old.replace_with(replacement)
    else:
        article = soup.find("article") or soup.body
        if not article:
            raise ValueError("The series page has no editable content area.")
        article.append(replacement)
    return str(soup)
