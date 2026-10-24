"""Discover endpoints and deliver one bounded outbound Webmention."""

import json
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from reader_network import fetch_bounded, post_bounded, public_url

from .shared import (
    CANDIDATE_FIELDS,
    RETRY_DELAYS,
    _absolute_url,
    _candidate,
    _origin,
)


def _event(value):
    if not isinstance(value, dict) or not CANDIDATE_FIELDS.issubset(value):
        raise ValueError("Invalid Webmention discovery candidate.")
    return _candidate({name: value[name] for name in CANDIDATE_FIELDS})


def _header(headers, name):
    return next(
        (value for key, value in (headers or {}).items() if str(key).lower() == name.lower()),
        None,
    )


def _webmention_link(header):
    if not isinstance(header, str):
        return None
    for match in re.finditer(r"<([^>]*)>\s*((?:;\s*[^,]*)*)", header):
        parameters = match.group(2)
        rel = re.search(r"(?:^|;)\s*rel\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^;\s,]*))", parameters, re.I)
        if rel and "webmention" in next(value for value in rel.groups() if value is not None).lower().split():
            return match.group(1).strip()
    return None


def _html_webmention(body):
    soup = BeautifulSoup(body, "html.parser")
    for element in soup.find_all(("link", "a")):
        rel = element.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()
        if any(str(value).lower() == "webmention" for value in rel) and element.get("href"):
            return element["href"].strip()
    return None


def _json_document(body, label):
    try:
        value = json.loads(body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object.")
    return value


def _item_url(manifest_url, manifest, item_id):
    template = manifest.get("item", "items/{id}.json")
    if not isinstance(template, str):
        raise ValueError("The target Blyg item template is invalid.")
    variables = re.findall(r"\{([^{}]+)\}", template)
    if variables != ["id"] or template.count("{") != 1 or template.count("}") != 1:
        raise ValueError("The target Blyg item template must contain only {id}.")
    return _absolute_url(urljoin(manifest_url, template.replace("{id}", item_id)), keep_fragment=False)


def _guarded_endpoint(value, base, endpoint_guard):
    endpoint = _absolute_url(urljoin(base, value), keep_fragment=False)
    endpoint_guard(endpoint)
    return endpoint


def _w3c_endpoint(target, fetcher, endpoint_guard):
    try:
        final, _, headers, _ = fetcher(target, method="HEAD", limit=0)
    except ValueError:
        final = headers = None
    if final:
        found = _webmention_link(_header(headers, "link"))
        if found:
            return _guarded_endpoint(found, final, endpoint_guard), "http-link"
    final, body, headers, _ = fetcher(target, method="GET", limit=1024 * 1024)
    found = _webmention_link(_header(headers, "link"))
    if found:
        return _guarded_endpoint(found, final, endpoint_guard), "http-link"
    found = _html_webmention(body)
    if found:
        return _guarded_endpoint(found, final, endpoint_guard), "html"
    return None


def discover_endpoint(candidate, fetcher=fetch_bounded, endpoint_guard=public_url):
    """Discover an endpoint and exact target without sending a Webmention.

    The default transport validates and pins public addresses at every redirect.
    Tests may inject a non-network fetcher and endpoint guard.
    """
    event = _event(candidate)
    target = event["target_url"]
    manifest = None
    manifest_url = None
    manifest_endpoint = None

    if event["target_origin"] is not None:
        expected_manifest = event["target_origin"] + "blyg.json"
        try:
            final, body, _, _ = fetcher(expected_manifest, method="GET", limit=256 * 1024)
            if _absolute_url(final, keep_fragment=False) != _absolute_url(expected_manifest, keep_fragment=False):
                raise ValueError("The target Blyg manifest redirected outside its asserted origin.")
            manifest = _json_document(body, "The target Blyg manifest")
            if not re.fullmatch(r"0\.\d+", str(manifest.get("blyg", ""))):
                raise ValueError("The target Blyg manifest has an unsupported protocol version.")
            manifest_url = final
            if "webmention" in manifest:
                if not isinstance(manifest["webmention"], str) or not manifest["webmention"].strip():
                    raise ValueError("The target Blyg Webmention endpoint is invalid.")
                manifest_endpoint = manifest["webmention"]
        except ValueError:
            if target is None:
                raise
            manifest = manifest_url = manifest_endpoint = None

    if target is None:
        if manifest is None or manifest_url is None:
            return None
        expected_item = _item_url(manifest_url, manifest, event["target_id"])
        final, body, _, _ = fetcher(expected_item, method="GET", limit=1024 * 1024)
        if _absolute_url(final, keep_fragment=False) != expected_item:
            raise ValueError("The target item document redirected away from its manifest location.")
        item = _json_document(body, "The target item document")
        if item.get("id") != event["target_id"]:
            raise ValueError("The target item document has the wrong identity.")
        if _origin(item.get("origin") or event["target_origin"]) != event["target_origin"]:
            raise ValueError("The target item document has the wrong origin.")
        page = item.get("page")
        if not isinstance(page, str) or not page.strip():
            raise ValueError("The target item document has no public page.")
        target = _absolute_url(urljoin(event["target_origin"], page))

    if manifest_endpoint is not None:
        endpoint = _guarded_endpoint(manifest_endpoint, manifest_url, endpoint_guard)
        return {"endpoint": endpoint, "target": target, "method": "manifest"}

    found = _w3c_endpoint(target, fetcher, endpoint_guard)
    if found is None:
        return None
    endpoint, method = found
    return {"endpoint": endpoint, "target": target, "method": method}


def _delivery_result(status, *, attempt, error=None):
    """Classify one POST result without changing durable queue state."""
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Webmention delivery attempt must be a positive integer.")
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("Invalid Webmention HTTP status.")
    if status is not None and 200 <= status < 300:
        return {
            "status": "delivered",
            "http_status": status,
            "error": None,
            "retry_after": None,
        }
    retryable = status is None or status == 429 or 500 <= status < 600
    if retryable and attempt <= len(RETRY_DELAYS):
        return {
            "status": "retrying",
            "http_status": status,
            "error": error or (f"HTTP {status}" if status is not None else "Network error"),
            "retry_after": RETRY_DELAYS[attempt - 1],
        }
    if retryable:
        state = "abandoned"
    else:
        state = "rejected"
    return {
        "status": state,
        "http_status": status,
        "error": error or (f"HTTP {status}" if status is not None else "Network error"),
        "retry_after": None,
    }


def deliver_webmention(candidate, discovery, *, attempt=1, poster=post_bounded):
    """POST the W3C source/target form for one already-discovered event.

    A withdrawal uses the same pair once, with no private flag on the wire; the
    receiver discovers the withdrawal by re-fetching the published source.
    This helper returns queue-ready classification data and never mutates the
    outbox itself.
    """
    event = _event(candidate)
    if not isinstance(discovery, dict) or not {"endpoint", "target"}.issubset(discovery):
        raise ValueError("Invalid Webmention discovery result.")
    endpoint = _absolute_url(discovery["endpoint"], keep_fragment=False)
    target = _absolute_url(discovery["target"])
    if event["source"] == target:
        raise ValueError("Webmention source and target must differ.")
    body = urlencode({"source": event["source"], "target": target}).encode("ascii")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "User-Agent": "Blynger Webmention",
    }
    try:
        response = poster(endpoint, body, headers=headers, limit=64 * 1024, timeout=5)
        status = response[3]
        return _delivery_result(status, attempt=attempt)
    except ValueError as error:
        return _delivery_result(None, attempt=attempt, error=str(error))
