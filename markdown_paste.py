"""Convert pasted Markdown to safe, ordinary Blynger editor markup."""
import markdown

from core import clean


def render_pasted_markdown(text):
    if not isinstance(text, str):
        raise ValueError("Paste Markdown as text.")
    if len(text) > 500_000:
        raise ValueError("That Markdown paste is too large. Paste it in smaller sections.")
    rendered = markdown.markdown(
        text.replace("\r\n", "\n").replace("\r", "\n"),
        extensions=["extra", "sane_lists"],
    )
    return clean(rendered)
