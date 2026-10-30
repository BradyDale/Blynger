"""Bounded, explicit import of one user-supplied ChatGPT share link."""
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from reader_network import fetch_bounded


_SHARE_PATH = re.compile(r"^/share/[0-9a-fA-F-]{32,64}/?$")
_ENQUEUE = "window.__reactRouterContext.streamController.enqueue("


def _valid_share_url(url):
    if not isinstance(url, str):
        raise ValueError("Paste a ChatGPT share link.")
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "chatgpt.com"
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _SHARE_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("Use a complete https://chatgpt.com/share/… link.")
    return url.strip()


def _inflate(values):
    """Inflate React Router's bounded flattened share-page payload."""
    if not isinstance(values, list) or not values or len(values) > 100_000:
        raise ValueError("ChatGPT returned an unfamiliar share-page format.")
    memo = {}

    def reference(value):
        if type(value) is int:
            if value < 0:
                return None
            return hydrate(value)
        return value

    def hydrate(index):
        if type(index) is not int or not 0 <= index < len(values):
            raise ValueError("ChatGPT returned an invalid share-page reference.")
        if index in memo:
            return memo[index]
        value = values[index]
        if isinstance(value, dict):
            result = {}
            memo[index] = result
            for encoded_key, encoded_value in value.items():
                key = encoded_key
                if encoded_key.startswith("_") and encoded_key[1:].isdigit():
                    key = hydrate(int(encoded_key[1:]))
                result[str(key)] = reference(encoded_value)
            return result
        if isinstance(value, list):
            result = []
            memo[index] = result
            result.extend(reference(item) for item in value)
            return result
        memo[index] = value
        return value

    return hydrate(0)


def _share_data(html):
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        source = (script.string or "").strip()
        if not source.startswith(_ENQUEUE):
            continue
        if not source.endswith(");"):
            continue
        try:
            payload = json.loads(source[len(_ENQUEUE) : -2])
            serialized = next(line for line in payload.splitlines() if line.startswith("["))
            root = _inflate(json.loads(serialized))
            loader = root.get("loaderData", {})
            for route in loader.values():
                if not isinstance(route, dict):
                    continue
                data = (route.get("serverResponse") or {}).get("data")
                if isinstance(data, dict) and isinstance(data.get("linear_conversation"), list):
                    return data
        except (ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
            continue
    raise ValueError("Blynger could not read that ChatGPT share page.")


def _turns(data):
    turns = []
    for record in data.get("linear_conversation", []):
        if not isinstance(record, dict):
            continue
        message = record.get("message", record)
        if not isinstance(message, dict):
            continue
        author = message.get("author") or {}
        if not isinstance(author, dict):
            continue
        role = author.get("role")
        if role not in ("user", "assistant") or message.get("recipient") not in (None, "all"):
            continue
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        if metadata.get("is_visually_hidden_from_conversation"):
            continue
        content = message.get("content") or {}
        if not isinstance(content, dict):
            continue
        if content.get("content_type") != "text":
            continue
        # Search/reasoning preambles can be assistant-authored text in the
        # payload, but they are not the final response shown in the shared chat.
        if role == "assistant" and not (
            message.get("end_turn") is True
            or metadata.get("finish_details")
            or metadata.get("is_complete") is True
        ):
            continue
        parts = [part for part in (content.get("parts") or []) if isinstance(part, str)]
        text = "\n\n".join(part.strip() for part in parts if part.strip())
        if text:
            turns.append({"role": "assistant" if role == "assistant" else "author", "text": text})
    if not turns or not any(turn["role"] == "assistant" for turn in turns):
        raise ValueError("That shared chat does not contain an importable dialogue.")
    if len(turns) > 200 or len(str(turns)) > 300_000:
        raise ValueError("That shared chat is too large to import at once.")
    return turns


def parse_share_html(html):
    if not isinstance(html, (bytes, str)):
        raise ValueError("ChatGPT returned an invalid share page.")
    return _turns(_share_data(html))


def import_share(url, fetcher=fetch_bounded):
    requested = _valid_share_url(url)
    final, body, headers, _ = fetcher(
        requested,
        headers={"Accept": "text/html"},
        limit=6 * 1024 * 1024,
        redirects=0,
        timeout=12,
    )
    _valid_share_url(final)
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), ""
    )
    if content_type and "html" not in content_type.lower():
        raise ValueError("ChatGPT did not return a share page.")
    return {"turns": parse_share_html(body), "url": final}
