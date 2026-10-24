"""Build the immutable accepted-target registry for an inbound receiver."""

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .inbound_contract import _request_url


ID = re.compile(r"[0-7][0-9a-hjkmnp-tv-z]{25}")
KINDS = {"fragment", "thread", "withdrawn"}
MAX_ITEMS = 10_000


def _origin(value):
    normalized, _ = _request_url(value, "target")
    if urlsplit(normalized).query:
        raise ValueError("The Blyg origin cannot contain a query.")
    return normalized.rstrip("/") + "/"


def _inside(origin, value):
    normalized, _ = _request_url(value, "target")
    if not normalized.startswith(origin):
        raise ValueError("An inbound target lies outside the Blyg origin.")
    return normalized


def _same_site(origin, value):
    """Accept a legacy page URL only on the manifest's exact web origin."""
    normalized, _ = _request_url(value, "target")
    expected = urlsplit(origin)
    actual = urlsplit(normalized)
    if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise ValueError("An inbound target lies outside the Blyg site.")
    return normalized


def _item_template(manifest):
    template = manifest.get("item", "items/{id}.json")
    if not isinstance(template, str) or template.count("{id}") != 1:
        raise ValueError("The Blyg item template is invalid.")
    if re.search(r"\{(?!id\})|(?<!\{id)\}", template):
        raise ValueError("The Blyg item template is invalid.")
    if manifest.get("blyg") != "0.4" and template != "items/{id}.json":
        raise ValueError("Custom item templates require Blyg 0.4.")
    return template


def build_target_registry(origin, manifest, documents):
    """Return a deterministic registry from exact current item documents."""
    origin = _origin(origin)
    if not isinstance(manifest, dict) or manifest.get("site") != origin:
        raise ValueError("The manifest does not identify this Blyg origin.")
    if manifest.get("blyg") not in ("0.3", "0.4"):
        raise ValueError("The manifest has an unsupported Blyg version.")
    template = _item_template(manifest)
    if not isinstance(documents, (list, tuple)) or len(documents) > MAX_ITEMS:
        raise ValueError("The target registry item set is invalid or too large.")
    seen = set()
    targets = set()
    items = []
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("A current Blyg item is not an object.")
        iid = document.get("id")
        if not isinstance(iid, str) or not ID.fullmatch(iid) or iid in seen:
            raise ValueError("A current Blyg item has an invalid or duplicate id.")
        seen.add(iid)
        if document.get("kind") not in KINDS:
            raise ValueError("A current Blyg item has an invalid kind.")
        if _origin(document.get("origin", origin)) != origin:
            raise ValueError("A current Blyg item belongs to another origin.")
        page = document.get("page")
        if isinstance(page, str) and page.strip():
            page_url = _inside(origin, urljoin(origin, page))
        else:
            # Blynger initially emitted absolute same-site `url` values before
            # Blyg standardized `page`.  Keep those immutable historical item
            # documents addressable without rewriting them or permitting an
            # arbitrary external target into the receiver registry.
            legacy = document.get("url")
            if document.get("blyg") not in ("0.2", "0.3") or not isinstance(legacy, str) or not legacy.strip():
                raise ValueError("A current Blyg item has no page.")
            page_url = _same_site(origin, legacy)
        document_url = _inside(origin, urljoin(origin, template.replace("{id}", iid)))
        pins = []
        for entry in document.get("changelog", []):
            if isinstance(entry, dict) and entry.get("pinned") is True:
                version = entry.get("version")
                if type(version) is int and version > 0:
                    pins.append(version)
        pins = sorted(set(pins))
        targets.update((page_url, document_url))
        items.append(
            {
                "id": iid,
                "kind": document["kind"],
                "page": page_url,
                "document": document_url,
                "pins": pins,
            }
        )
    if len(targets) != len(seen) * 2:
        raise ValueError("Current Blyg items do not have distinct target URLs.")
    return {
        "schema": 2,
        "origin": origin,
        "item_count": len(seen),
        "targets": sorted(targets),
        "items": sorted(items, key=lambda row: row["id"]),
    }


def validate_target_registry(value, expected_origin=None):
    if not isinstance(value, dict) or set(value) != {"schema", "origin", "item_count", "targets", "items"}:
        raise ValueError("Invalid inbound target registry.")
    origin = _origin(value["origin"])
    if expected_origin is not None and origin != _origin(expected_origin):
        raise ValueError("The target registry has the wrong origin.")
    if value["schema"] != 2 or type(value["item_count"]) is not int or value["item_count"] < 0:
        raise ValueError("Invalid inbound target registry.")
    if not isinstance(value["targets"], list) or len(value["targets"]) != value["item_count"] * 2:
        raise ValueError("Invalid inbound target registry.")
    targets = [_request_url(target, "target")[0] for target in value["targets"]]
    if targets != sorted(set(targets)):
        raise ValueError("Invalid inbound target registry.")
    if not isinstance(value["items"], list) or len(value["items"]) != value["item_count"]:
        raise ValueError("Invalid inbound target registry.")
    items = []
    ids = set()
    derived = set()
    for row in value["items"]:
        if not isinstance(row, dict) or set(row) != {"id", "kind", "page", "document", "pins"}:
            raise ValueError("Invalid inbound target registry item.")
        iid = row["id"]
        if not isinstance(iid, str) or not ID.fullmatch(iid) or iid in ids:
            raise ValueError("Invalid inbound target registry item.")
        if row["kind"] not in KINDS:
            raise ValueError("Invalid inbound target registry item.")
        page = _same_site(origin, row["page"])
        document = _inside(origin, row["document"])
        pins = row["pins"]
        if (
            not isinstance(pins, list)
            or pins != sorted(set(pins))
            or any(type(version) is not int or version < 1 for version in pins)
        ):
            raise ValueError("Invalid inbound target registry item.")
        ids.add(iid)
        derived.update((page, document))
        items.append({"id": iid, "kind": row["kind"], "page": page, "document": document, "pins": pins})
    if items != sorted(items, key=lambda row: row["id"]) or derived != set(targets):
        raise ValueError("Invalid inbound target registry.")
    return {"schema": 2, "origin": origin, "item_count": value["item_count"], "targets": targets, "items": items}


def write_target_registry(path, registry):
    """Atomically replace an owner-written, web-readable registry."""
    path = Path(path)
    registry = validate_target_registry(registry)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if path.exists() or path.is_symlink():
        details = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("The target registry path is unsafe.")
    data = (json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
