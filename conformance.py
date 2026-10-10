"""Independent checks for Blynger's generated Blyg 0.3 publication surface.

This module deliberately does not import publication transitions or projectors
from core.py.  It observes the final static artifacts through a root directory
plus an optional in-memory overlay, just as a reader would observe them.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

NS = "https://blygger.org/ns/0.1"
ID = re.compile(r"^[0-7][0-9a-hjkmnp-tv-z]{25}$")
UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
DIRECTIVE = re.compile(r"^\s*!\[\[([0-7][0-9a-hjkmnp-tv-z]{25})\]\]\s*$")


class ConformanceError(ValueError):
    """One or more final publication artifacts violate a required invariant."""

    def __init__(self, problems):
        self.problems = list(problems)
        preview = "; ".join(self.problems[:3])
        if len(self.problems) > 3:
            preview += f"; and {len(self.problems) - 3} more"
        super().__init__("Blyg publication checks failed: " + preview)


@dataclass(frozen=True)
class Report:
    items: int
    pins: int
    feed_events: int
    warnings: tuple[str, ...] = ()

    def public(self):
        return {"items": self.items, "pins": self.pins, "feed_events": self.feed_events,
                "warnings": list(self.warnings)}


class Surface:
    def __init__(self, root, overlay=None):
        self.root = Path(root)
        self.overlay = overlay or {}

    def bytes(self, name):
        if name in self.overlay:
            value = self.overlay[name]
            return value if isinstance(value, bytes) else value.encode()
        path = self.root / name
        return path.read_bytes() if path.is_file() else None

    def text(self, name):
        value = self.bytes(name)
        return value.decode("utf-8") if value is not None else None

    def changed(self, name):
        if name not in self.overlay:
            return False
        value = self.overlay[name]
        payload = value if isinstance(value, bytes) else value.encode()
        path = self.root / name
        return not path.is_file() or path.read_bytes() != payload


def _json(surface, name, problems):
    raw = surface.text(name)
    if raw is None:
        problems.append(name + " is missing")
        return None
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        problems.append(name + " is not valid UTF-8 JSON: " + str(error))
        return None
    if not isinstance(value, dict):
        problems.append(name + " must contain a JSON object")
        return None
    return value


def _utc(value):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _reference(ref, path, problems, origin_required=False):
    if not isinstance(ref, dict):
        problems.append(path + " must be an object")
        return
    if set(ref) in ({"url"}, {"url", "cited"}):
        if urlsplit(ref.get("url", "")).scheme not in ("http", "https"):
            problems.append(path + ".url must be an absolute HTTP(S) URL")
        cited=ref.get("cited")
        if cited is not None:
            if not isinstance(cited,dict):problems.append(path + ".cited must be an object")
            elif not _utc(cited.get("retrieved")):problems.append(path + ".cited.retrieved must be ISO 8601 UTC")
        return
    required = {"id", "version"} | ({"origin"} if origin_required else set())
    if not required <= set(ref):
        problems.append(path + " is missing " + ", ".join(sorted(required - set(ref))))
    if not ID.fullmatch(str(ref.get("id", ""))):
        problems.append(path + ".id is not a Blyg id")
    if not isinstance(ref.get("version"), int) or ref.get("version", 0) < 1:
        problems.append(path + ".version must be a positive integer")
    if "origin" in ref and urlsplit(str(ref["origin"])).scheme not in ("http", "https"):
        problems.append(path + ".origin must be an absolute HTTP(S) URL")


def _directives(markdown):
    """Whole-item directives outside fenced and indented code, in document order."""
    found, fence = [], None
    for line in str(markdown).replace("\r\n", "\n").split("\n"):
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if marker:
            token = marker.group(1)[0]
            fence = None if fence == token else token if fence is None else fence
            continue
        if fence or line.startswith(("    ", "\t")):
            continue
        match = DIRECTIVE.fullmatch(line)
        if match:
            found.append(match.group(1))
    return found


def _absolute_html(doc, path, problems):
    soup = BeautifulSoup(doc.get("content_html", ""), "html.parser")
    for node in soup.find_all(True):
        for attr in ("href", "src", "poster"):
            value = node.get(attr)
            if value and not urlsplit(value).scheme:
                problems.append(f"{path}.content_html has relative {attr}={value!r}")
    if soup.select("[data-blynger-quote], [data-blynger-selector]"):
        problems.append(path + ".content_html contains private editor metadata")
    return soup


def _item(doc, path, expected_origin, problems, warnings=None, strict=True):
    sink = problems if strict else (warnings if warnings is not None else problems)
    required = {"id", "kind", "origin", "created", "updated", "version",
                "content_md", "content_html", "content_hash", "changelog"}
    missing = required - set(doc)
    if missing:
        sink.append(path + " is missing " + ", ".join(sorted(missing)))
        return
    if not re.fullmatch(r"0\.\d+", str(doc.get("blyg", ""))):
        sink.append(path + ".blyg must declare a 0.x protocol version")
    if not ID.fullmatch(str(doc["id"])):
        sink.append(path + ".id is not a Blyg id")
    if doc["kind"] not in ("fragment", "thread", "withdrawn"):
        sink.append(path + ".kind is not a Blyg 0.3 kind")
    if doc["origin"] != expected_origin:
        sink.append(path + ".origin does not match the publication origin")
    for field in ("created", "updated"):
        if not _utc(doc[field]):
            sink.append(path + "." + field + " must be ISO 8601 UTC")
    if not isinstance(doc["version"], int) or doc["version"] < 1:
        sink.append(path + ".version must be a positive integer")
    actual = "sha256:" + hashlib.sha256(str(doc["content_md"]).encode()).hexdigest()
    if doc["content_hash"] != actual:
        sink.append(path + ".content_hash does not match content_md")
    changes = doc["changelog"]
    if not isinstance(changes, list) or not changes:
        sink.append(path + ".changelog must be nonempty")
    else:
        versions = [entry.get("version") for entry in changes if isinstance(entry, dict)]
        if versions != list(range(1, doc["version"] + 1)):
            sink.append(path + ".changelog versions must be contiguous through current version")
        if not isinstance(changes[-1], dict) or doc["updated"] != changes[-1].get("at"):
            sink.append(path + ".updated must equal the last changelog time")
        for index, entry in enumerate(changes):
            if not isinstance(entry, dict) or not _utc(entry.get("at")):
                sink.append(f"{path}.changelog[{index}].at must be ISO 8601 UTC")
    page = doc.get("page")
    if page is not None and (not isinstance(page, str) or not page or urlsplit(page).scheme or page.startswith("/")):
        sink.append(path + ".page must be a nonempty origin-relative path")
    soup = _absolute_html(doc, path, sink)
    transclusions = doc.get("transclusions")
    if doc["kind"] == "fragment" and ("transclusions" in doc or "stub_of" in doc):
        sink.append(path + ": fragments cannot carry transclusions or stub_of")
    if doc["kind"] == "thread" and not isinstance(transclusions, list):
        sink.append(path + ": threads must carry transclusions[]")
        transclusions = []
    if doc["kind"] == "withdrawn":
        if doc["content_md"] != "" or doc["content_html"] != "" or doc.get("media") not in (None, []):
            sink.append(path + ": a withdrawal must have empty content and media")
        if doc.get("transclusions") not in (None, []) or "stub_of" in doc or "generated" in doc:
            sink.append(path + ": a withdrawal cannot retain response or generation content")
    transclusions = transclusions if isinstance(transclusions, list) else []
    for index, ref in enumerate(transclusions):
        _reference(ref, f"{path}.transclusions[{index}]", sink)
    wrappers = [node for node in soup.select("blockquote.blyg-transclusion[data-blyg-id]")
                if node.find_parent("blockquote", class_="blyg-transclusion") is None]
    directives = _directives(doc["content_md"])
    wrapper_keys = [(node.get("data-blyg-id"), int(node.get("data-blyg-version", "0")) if str(node.get("data-blyg-version", "")).isdigit() else 0,
                     node.get("data-blyg-origin", expected_origin)) for node in wrappers]
    reference_keys = [(ref.get("id"), ref.get("version"), ref.get("origin", expected_origin))
                      for ref in transclusions if isinstance(ref, dict)]
    if directives != [key[0] for key in reference_keys]:
        sink.append(path + ": whole-item directives do not match transclusions[] in order")
    if wrapper_keys != reference_keys:
        sink.append(path + ": baked transclusion wrappers do not match transclusions[]")
    if "stub_of" in doc:
        stub = doc["stub_of"]
        _reference(stub, path + ".stub_of", sink, origin_required="url" not in stub if isinstance(stub, dict) else True)
        if isinstance(stub, dict) and "id" in stub:
            match = next((ref for ref in transclusions if isinstance(ref, dict) and
                          ref.get("id") == stub.get("id") and
                          ref.get("origin", expected_origin) == stub.get("origin")), None)
            if match and match.get("version") != stub.get("version"):
                sink.append(path + ": stub_of.version disagrees with its baked target")
    if "forked_from" in doc:
        _reference(doc["forked_from"], path + ".forked_from", sink, origin_required=True)
    generated = doc.get("generated")
    generated_nodes = soup.select(".blyg-tk-gen")
    if generated is not None and (not isinstance(generated, list) or not generated):
        sink.append(path + ".generated must be a nonempty array when present")
    if generated_nodes and not generated:
        sink.append(path + ": generated HTML has no generated[] provenance")
    if generated and len(generated_nodes) != len(generated):
        sink.append(path + ": generated[] does not match generated HTML spans")


def validate_surface(root, origin, overlay=None, strict_existing=True):
    """Validate final static artifacts; raise ConformanceError on MUST failures."""
    origin = origin.rstrip("/") + "/"
    surface = Surface(root, overlay)
    problems, warnings = [], []
    manifest = _json(surface, "blyg/blyg.json", problems)
    index = _json(surface, "blyg/items/index.json", problems)
    if manifest:
        for key in ("blyg", "level", "generator", "site", "title", "feed", "items", "updated"):
            if key not in manifest:
                problems.append("blyg/blyg.json is missing " + key)
        if manifest.get("blyg") != "0.3" or manifest.get("level") != 2:
            problems.append("blyg/blyg.json must declare Blyg 0.3 Level 2")
        if manifest.get("site") != origin or manifest.get("feed") != "feed.xml" or manifest.get("items") != "items/index.json":
            problems.append("blyg/blyg.json advertises the wrong publication surfaces")
        if not manifest.get("generator_url"):
            warnings.append("manifest omits recommended generator_url")
    rows = index.get("items", []) if index else []
    if not isinstance(rows, list):
        problems.append("blyg/items/index.json.items must be an array")
        rows = []
    docs = {}
    for number, row in enumerate(rows):
        if not isinstance(row, dict) or not ID.fullmatch(str(row.get("id", ""))):
            problems.append(f"blyg/items/index.json.items[{number}] has no valid id")
            continue
        iid = row["id"]
        if iid in docs:
            problems.append("blyg/items/index.json repeats " + iid)
            continue
        path = f"blyg/items/{iid}.json"
        doc = _json(surface, path, problems)
        if doc:
            docs[iid] = doc
            _item(doc, path, origin, problems, warnings,
                  strict=strict_existing or surface.changed(path))
            if doc.get("id") != iid:
                problems.append(path + " does not match its filename")
            expected = {key: doc.get(key) for key in ("id", "kind", "created", "updated", "version")}
            if row != expected:
                problems.append(path + " does not match its archive-index row")
    if rows != sorted(rows, key=lambda row: (row.get("updated", ""), row.get("id", "")), reverse=True):
        problems.append("blyg/items/index.json is not ordered by updated descending")
    if index and rows:
        if index.get("updated") != rows[0].get("updated"):
            problems.append("blyg/items/index.json.updated does not match its newest item")
    if manifest and index and manifest.get("updated") != index.get("updated"):
        problems.append("manifest and archive index disagree about updated")

    pins = 0
    for iid, doc in docs.items():
        for entry in doc.get("changelog", []):
            if not isinstance(entry, dict) or not entry.get("pinned"):
                continue
            version = entry.get("version")
            path = f"blyg/items/{iid}/v{version}.json"
            pin = _json(surface, path, problems)
            if not pin:
                continue
            pins += 1
            if pin.get("id") != iid or pin.get("version") != version or pin.get("pinned") is not True:
                problems.append(path + " does not identify the promised pinned version")
            pin_sink = problems if strict_existing or surface.changed(path) else warnings
            if pin.get("kind") == "withdrawn" or "media" in pin:
                pin_sink.append(path + " is not a valid content-bearing pin")
            _item({**pin, "created": pin.get("created", pin.get("at")),
                   "updated": pin.get("updated", pin.get("at")),
                   "changelog": [{"version": n, "at": pin.get("at")} for n in range(1, int(version or 0) + 1)]},
                  path, origin, problems, warnings,
                  strict=strict_existing or surface.changed(path))

    feed_events = 0
    raw_feed = surface.bytes("blyg/feed.xml")
    if raw_feed is None:
        problems.append("blyg/feed.xml is missing")
    else:
        try:
            feed = ET.fromstring(raw_feed)
            channel = feed.find("channel")
            if channel is None:
                problems.append("blyg/feed.xml has no RSS channel")
            else:
                manifest_url = channel.find("{" + NS + "}manifest")
                if manifest_url is None or manifest_url.text != origin + "blyg.json":
                    problems.append("blyg/feed.xml has the wrong blyg:manifest hook")
                self_links = [node for node in channel.findall("{http://www.w3.org/2005/Atom}link") if node.get("rel") == "self"]
                if len(self_links) != 1 or self_links[0].get("href") != origin + "feed.xml":
                    problems.append("blyg/feed.xml has the wrong Atom self link")
                seen = set()
                for item in channel.findall("item"):
                    feed_events += 1
                    iid = item.findtext("{" + NS + "}id")
                    try:
                        version = int(item.findtext("{" + NS + "}version", "0"))
                    except ValueError:
                        version = 0
                    guid = item.findtext("guid")
                    key = (iid, version)
                    if key in seen:
                        problems.append("blyg/feed.xml repeats an event")
                    seen.add(key)
                    doc = docs.get(iid)
                    if not doc or version not in [c.get("version") for c in doc.get("changelog", [])]:
                        problems.append("blyg/feed.xml names an unknown publish event")
                        continue
                    if guid != f"blyg:{iid}:v{version}":
                        problems.append("blyg/feed.xml has a malformed per-version GUID")
                    if item.findtext("description", "") != doc.get("content_html", ""):
                        problems.append("blyg/feed.xml does not carry the current item HTML")
        except ET.ParseError as error:
            problems.append("blyg/feed.xml is not valid XML: " + str(error))
    if problems:
        raise ConformanceError(problems)
    return Report(len(docs), pins, feed_events, tuple(warnings))
