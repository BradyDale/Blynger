"""Inactive, bounded structural verifier for queued inbound Webmentions.

This module is deliberately not imported by the application package root.  It
is host-worker code: it fetches untrusted public sources, records only bounded
metadata, and never touches Git, drafts, subscriptions, or public pages.
"""

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from reader_network import HTTPStatusError, fetch_bounded

from .inbound_contract import _request_url
from .inbound_targets import ID, validate_target_registry


BODY_LIMIT = 1024 * 1024
FETCH_LIMIT = 3
BATCH_LIMIT = 20
RETRY_DELAYS = (15 * 60, 60 * 60, 4 * 60 * 60, 12 * 60 * 60, 24 * 60 * 60)
RECORD_LIMIT = 16 * 1024
AUTHOR_LIMIT = 4096
AUTHOR_DEPTH_LIMIT = 8
AUTHOR_NODE_LIMIT = 128
AUTHOR_KEY_LIMIT = 128
AUTHOR_STRING_LIMIT = 2048
AUTHOR_NAME_LIMIT = 200
EXPORT_LIMIT = 16 * 1024 * 1024
EXPORT_RECORDS = 2000
RELATIONS = ("stub", "transclusion", "fork", "source", "link")
MENTION_CLASSES = ("response", "notice")
ERRORS = {
    "fetch_failed",
    "source_gone",
    "invalid_source",
    "invalid_document",
    "wrong_location",
    "no_relation",
    "unpublished_fork",
}


class VerificationFailure(ValueError):
    def __init__(self, code):
        if code not in ERRORS:
            raise ValueError("Invalid inbound verification error.")
        super().__init__(code)
        self.code = code


def _author_copy(value):
    """Return bounded JSON-like author metadata without recursive traversal.

    Remote JSON may be small in bytes while still being deep enough to crash
    ``deepcopy`` or another recursive encoder.  Walk it iteratively first, then
    copy only after its shape is known to be shallow and bounded.
    """
    if not isinstance(value, dict):
        raise ValueError("Invalid author metadata.")
    stack = [(value, 0)]
    containers = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > AUTHOR_NODE_LIMIT or depth > AUTHOR_DEPTH_LIMIT:
            raise ValueError("Invalid author metadata.")
        if isinstance(current, (dict, list)):
            identity = id(current)
            if identity in containers:
                raise ValueError("Invalid author metadata.")
            containers.add(identity)
        if isinstance(current, dict):
            for key, child in current.items():
                if type(key) is not str or len(key.encode("utf-8")) > AUTHOR_KEY_LIMIT:
                    raise ValueError("Invalid author metadata.")
                if depth == 0 and key == "name" and (
                    type(child) is not str or len(child.encode("utf-8")) > AUTHOR_NAME_LIMIT
                ):
                    raise ValueError("Invalid author metadata.")
                if depth == 0 and key == "url" and type(child) is not str:
                    raise ValueError("Invalid author metadata.")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
        elif type(current) is str:
            if len(current.encode("utf-8")) > AUTHOR_STRING_LIMIT:
                raise ValueError("Invalid author metadata.")
        elif current is None or type(current) is bool:
            pass
        elif type(current) is int:
            if not -(2**63) <= current < 2**63:
                raise ValueError("Invalid author metadata.")
        elif type(current) is float:
            if not math.isfinite(current):
                raise ValueError("Invalid author metadata.")
        else:
            raise ValueError("Invalid author metadata.")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(encoded) > AUTHOR_LIMIT:
            raise ValueError("Invalid author metadata.")
        return copy.deepcopy(value)
    except (OverflowError, RecursionError, UnicodeError, ValueError) as error:
        raise ValueError("Invalid author metadata.") from error


class _AlternateParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None

    def handle_starttag(self, tag, attrs):
        if self.href is not None or tag.lower() != "link":
            return
        values = {str(name).lower(): value for name, value in attrs}
        relations = str(values.get("rel", "")).lower().split()
        media = str(values.get("type", "")).split(";", 1)[0].strip().lower()
        if "alternate" in relations and media == "application/json" and values.get("href"):
            self.href = values["href"]


def _json(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise VerificationFailure("invalid_document") from error


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), "")


def _origin(value):
    try:
        value, _ = _request_url(value, "source")
    except Exception as error:
        raise VerificationFailure("invalid_document") from error
    parsed = urlsplit(value)
    if parsed.query:
        raise VerificationFailure("invalid_document")
    return value.rstrip("/") + "/"


def _absolute(value, base):
    try:
        return _url(urljoin(base, value))
    except (TypeError, ValueError) as error:
        raise VerificationFailure("invalid_document") from error


def _url(value):
    try:
        result, _ = _request_url(value, "source")
        return result
    except Exception as error:
        raise VerificationFailure("invalid_document") from error


def _template(manifest):
    value = manifest.get("item", "items/{id}.json")
    if (
        manifest.get("blyg") != "0.4"
        or not isinstance(value, str)
        or value.count("{id}") != 1
        or re.search(r"\{(?!id\})|(?<!\{id)\}", value)
    ):
        raise VerificationFailure("wrong_location")
    return value


def _reference(value, target_origin, target_id, *, source_origin, require_origin=False):
    if not isinstance(value, dict):
        return False
    if value.get("id") != target_id or type(value.get("version")) is not int or value["version"] < 1:
        return False
    origin = value.get("origin")
    if origin is None:
        if require_origin:
            return False
        origin = source_origin
    try:
        return _origin(origin) == target_origin
    except VerificationFailure:
        return False


def _link_reference(value, target_origin, target_id, source_origin):
    if not isinstance(value, dict) or set(value) - {"id", "origin"} or value.get("id") != target_id:
        return False
    try:
        return _origin(value.get("origin") or source_origin) == target_origin
    except VerificationFailure:
        return False


def _has_authored_words(document):
    """Ignore transclusion directives and their attached selection quotes."""
    markdown = document.get("content_md")
    if not isinstance(markdown, str):
        return True
    directive = re.compile(
        r"^\s*!\[\[[0-7][0-9a-hjkmnp-tv-z]{25}(?:\s*\|\s*[^\]\r\n]+)?\]\]\s*$"
    )
    after_directive = False
    for line in markdown.splitlines():
        if directive.fullmatch(line):
            after_directive = True
            continue
        if after_directive and (not line.strip() or re.match(r"^\s*>", line)):
            continue
        after_directive = False
        if line.strip():
            return True
    return False


def _relation(document, target, receiver_origin):
    source_origin = _origin(document["origin"])
    target_id = target["id"]
    stub = document.get("stub_of")
    if document["kind"] == "thread" and _reference(
        stub, receiver_origin, target_id, source_origin=source_origin, require_origin=True
    ):
        return "stub"
    transclusions = document.get("transclusions", [])
    if isinstance(transclusions, list) and any(
        _reference(value, receiver_origin, target_id, source_origin=source_origin)
        for value in transclusions
    ):
        return "transclusion"
    fork = document.get("forked_from")
    if _reference(fork, receiver_origin, target_id, source_origin=source_origin, require_origin=True):
        if fork["version"] not in target["pins"]:
            raise VerificationFailure("unpublished_fork")
        return "fork"
    generated = document.get("generated", [])
    if document.get("blyg") == "0.4" and isinstance(generated, list):
        for span in generated:
            sources = span.get("sources", []) if isinstance(span, dict) else []
            if isinstance(sources, list) and any(
                _reference(value, receiver_origin, target_id, source_origin=source_origin)
                for value in sources
            ):
                return "source"
    links = document.get("links", [])
    if document.get("blyg") == "0.4" and isinstance(links, list) and any(
        _link_reference(value, receiver_origin, target_id, source_origin)
        for value in links
    ):
        return "link"
    raise VerificationFailure("no_relation")


def _mention_class(document, relation):
    if relation == "link":
        return "notice"
    if relation in ("stub", "transclusion") and not _has_authored_words(document):
        return "notice"
    return "response"


def _target(registry, url):
    for row in registry["items"]:
        if url in (row["page"], row["document"]):
            return row
        if any(
            url in (target["page"], target["document"])
            for target in row.get("pin_targets", [])
        ):
            return row
    raise VerificationFailure("invalid_source")


class StructuralVerifier:
    def __init__(self, registry, fetcher=fetch_bounded, clock=time.time):
        self.registry = validate_target_registry(registry)
        self.fetcher = fetcher
        self.clock = clock
        self.fetches = 0

    def _fetch(self, url, *, source_request=False):
        if self.fetches >= FETCH_LIMIT:
            raise VerificationFailure("fetch_failed")
        self.fetches += 1
        try:
            return self.fetcher(
                url,
                method="GET",
                limit=BODY_LIMIT,
                redirects=3,
                timeout=5,
            )
        except HTTPStatusError as error:
            if source_request and error.status in (404, 410):
                raise VerificationFailure("source_gone") from error
            raise VerificationFailure("fetch_failed") from error
        except (OSError, ValueError) as error:
            raise VerificationFailure("fetch_failed") from error

    def _document(self, source):
        final, body, headers, _ = self._fetch(source, source_request=True)
        media = _header(headers, "Content-Type").split(";", 1)[0].strip().lower()
        direct = None
        if media in ("application/json", "application/ld+json") or body.lstrip().startswith(b"{"):
            candidate = _json(body)
            if isinstance(candidate, dict) and "blyg" in candidate:
                direct = candidate
        if direct is not None:
            return direct, _url(final), None
        try:
            parser = _AlternateParser()
            parser.feed(body.decode("utf-8"))
            parser.close()
        except (UnicodeError, ValueError) as error:
            raise VerificationFailure("invalid_source") from error
        if not parser.href:
            raise VerificationFailure("invalid_source")
        document_url = _absolute(parser.href, final)
        document_final, document_body, _, _ = self._fetch(document_url)
        document = _json(document_body)
        return document, _url(document_final), _url(final)

    def verify(self, row):
        self.fetches = 0
        target = _target(self.registry, row["target"])
        document, document_url, fetched_page = self._document(row["source"])
        if not isinstance(document, dict) or document.get("blyg") not in ("0.3", "0.4"):
            raise VerificationFailure("invalid_document")
        iid = document.get("id")
        version = document.get("version")
        kind = document.get("kind")
        if (
            not isinstance(iid, str)
            or not ID.fullmatch(iid)
            or type(version) is not int
            or version < 1
            or kind not in ("fragment", "thread", "withdrawn")
        ):
            raise VerificationFailure("invalid_document")
        source_origin = _origin(document.get("origin"))
        default = _absolute("items/" + iid + ".json", source_origin)
        if document_url != default:
            manifest_url = _absolute("blyg.json", source_origin)
            final, body, _, _ = self._fetch(manifest_url)
            if _url(final) != manifest_url:
                raise VerificationFailure("wrong_location")
            manifest = _json(body)
            if not isinstance(manifest, dict):
                raise VerificationFailure("wrong_location")
            expected = _absolute(_template(manifest).replace("{id}", iid), manifest_url)
            if document_url != expected:
                raise VerificationFailure("wrong_location")
        page_value = document.get("page")
        if page_value is None:
            page = _absolute(("f/" if kind == "fragment" else "t/") + iid + "/", source_origin)
        elif isinstance(page_value, str) and page_value:
            page = _absolute(page_value, source_origin)
        else:
            raise VerificationFailure("invalid_document")
        if fetched_page is not None and fetched_page != page:
            raise VerificationFailure("invalid_source")
        relation = _relation(document, target, self.registry["origin"])
        author = document.get("author")
        if author is not None:
            try:
                author = _author_copy(author)
            except ValueError as error:
                raise VerificationFailure("invalid_document") from error
        return {
            "relation": relation,
            "mention_class": _mention_class(document, relation),
            "source_item_id": iid,
            "source_origin": source_origin,
            "source_version": version,
            "source_kind": kind,
            "source_author": author,
            "source_page": page,
            "verified_at": int(self.clock()),
        }


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_verification_record(value):
    legacy_fields = {
        "schema", "key", "source", "target", "status", "phase", "receipt_count",
        "relation", "source_item_id", "source_origin", "source_version", "source_kind",
        "source_author", "source_page", "verified_at", "error",
    }
    fields = legacy_fields | {"checked_at", "attempt_error"}
    current_fields = fields | {"mention_class"}
    if not isinstance(value, dict) or value.get("schema") not in (1, 2, 3):
        raise ValueError("Invalid inbound verification record.")
    if value["schema"] == 1 and set(value) == legacy_fields:
        value = {**value, "checked_at": value["verified_at"], "attempt_error": value["error"]}
    if value["schema"] in (1, 2) and set(value) == fields:
        value = {**value, "schema": 3, "mention_class": "response" if value["status"] == "verified" else None}
    elif value["schema"] != 3 or set(value) != current_fields:
        raise ValueError("Invalid inbound verification record.")
    if value["phase"] not in ("provisional", "final") or value["status"] not in ("verified", "gone", "failed"):
        raise ValueError("Invalid inbound verification record.")
    try:
        source, _ = _request_url(value["source"], "source")
        target, _ = _request_url(value["target"], "target")
    except Exception as error:
        raise ValueError("Invalid inbound verification record.") from error
    expected = hashlib.sha256((source + "\0" + target).encode()).hexdigest()
    if value["source"] != source or value["target"] != target or value["key"] != expected:
        raise ValueError("Invalid inbound verification record.")
    if type(value["receipt_count"]) is not int or value["receipt_count"] < 1:
        raise ValueError("Invalid inbound verification record.")
    if type(value["verified_at"]) is not int or value["verified_at"] < 0:
        raise ValueError("Invalid inbound verification record.")
    if type(value["checked_at"]) is not int or value["checked_at"] < value["verified_at"]:
        raise ValueError("Invalid inbound verification record.")
    if value["attempt_error"] is not None and value["attempt_error"] not in ERRORS:
        raise ValueError("Invalid inbound verification record.")
    if value["status"] == "verified":
        if value["relation"] not in RELATIONS or value["mention_class"] not in MENTION_CLASSES or value["error"] is not None:
            raise ValueError("Invalid inbound verification record.")
        if (
            not isinstance(value["source_item_id"], str)
            or not ID.fullmatch(value["source_item_id"])
            or type(value["source_version"]) is not int
            or value["source_version"] < 1
            or value["source_kind"] not in ("fragment", "thread", "withdrawn")
        ):
            raise ValueError("Invalid inbound verification record.")
        if _origin(value["source_origin"]) != value["source_origin"]:
            raise ValueError("Invalid inbound verification record.")
        try:
            page, _ = _request_url(value["source_page"], "source")
        except Exception as error:
            raise ValueError("Invalid inbound verification record.") from error
        if page != value["source_page"]:
            raise ValueError("Invalid inbound verification record.")
        author = value["source_author"]
        if author is not None:
            try:
                _author_copy(author)
            except ValueError as error:
                raise ValueError("Invalid inbound verification record.") from error
    elif value["error"] not in ERRORS:
        raise ValueError("Invalid inbound verification record.")
    elif value["status"] == "gone" and value["mention_class"] not in (None,) + MENTION_CLASSES:
        raise ValueError("Invalid inbound verification record.")
    elif any(
        value[name] is not None
        for name in (
            "relation", "source_item_id", "source_origin", "source_version",
            "source_kind", "source_author", "source_page",
        )
    ):
        raise ValueError("Invalid inbound verification record.")
    elif value["status"] == "failed" and value["mention_class"] is not None:
        raise ValueError("Invalid inbound verification record.")
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(encoded) > RECORD_LIMIT:
        raise ValueError("Oversized inbound verification record.")
    return copy.deepcopy(value)


class VerificationStore:
    """Owner-only bounded metadata records; hostile response bodies never enter."""

    def __init__(self, root):
        self.root = Path(root)
        if self.root.exists() and self.root.is_symlink():
            raise ValueError("Unsafe inbound verification directory.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def _path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", str(key)):
            raise ValueError("Invalid inbound verification key.")
        return self.root / (key + ".json")

    def read(self, key):
        path = self._path(key)
        if not path.exists():
            return None
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_mode & 0o177:
            raise ValueError("Unsafe inbound verification record.")
        if details.st_size > RECORD_LIMIT:
            raise ValueError("Oversized inbound verification record.")
        def unique(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError("Duplicate inbound verification field.")
                result[name] = value
            return result

        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")),
        )
        return self._validate(value)

    def _validate(self, value):
        return validate_verification_record(value)

    def write(self, value):
        value = self._validate(value)
        data = (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode()
        _atomic(self._path(value["key"]), data)
        return value

    def delete(self, key):
        path = self._path(key)
        if path.exists():
            current = self.read(key)
            path.unlink()
            directory = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return current
        return None

    def entries(self):
        rows = []
        for path in sorted(self.root.glob("*.json")):
            # The authoritative aggregate may live beside the private records
            # on the host so it can be pulled over SSH.  It is not itself a
            # mention record.  Reject all other unexpected JSON filenames.
            if path.name == "export.json":
                continue
            if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
                raise ValueError("Unexpected inbound verification file.")
            rows.append(self.read(path.stem))
        return rows


def _canonical_records(records):
    return json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def validate_verification_export(value):
    if not isinstance(value, dict) or set(value) != {"schema", "generated_at", "records", "records_sha256"}:
        raise ValueError("Invalid inbound verification export.")
    if value["schema"] != 1 or type(value["generated_at"]) is not int or value["generated_at"] < 0:
        raise ValueError("Invalid inbound verification export.")
    if not isinstance(value["records"], list) or len(value["records"]) > EXPORT_RECORDS:
        raise ValueError("Invalid inbound verification export.")
    original_records = value["records"]
    records = [validate_verification_record(row) for row in original_records]
    if any(row["phase"] != "final" for row in records):
        raise ValueError("Inbound verification export contains unfinished work.")
    if records != sorted(records, key=lambda row: row["key"]) or len({row["key"] for row in records}) != len(records):
        raise ValueError("Invalid inbound verification export ordering.")
    digest = "sha256:" + hashlib.sha256(_canonical_records(records)).hexdigest()
    legacy_digest = "sha256:" + hashlib.sha256(_canonical_records(original_records)).hexdigest()
    if value["records_sha256"] not in (digest, legacy_digest):
        raise ValueError("Inbound verification export checksum does not match.")
    result = {"schema": 1, "generated_at": value["generated_at"], "records": records, "records_sha256": digest}
    if len((json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()) > EXPORT_LIMIT:
        raise ValueError("Inbound verification export exceeds its size limit.")
    return result


def _read_verification_export(path):
    path = Path(path)
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_mode & 0o177
        or details.st_size > EXPORT_LIMIT
    ):
        raise ValueError("Unsafe inbound verification export.")

    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate inbound verification export field.")
            result[name] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")),
    )
    return validate_verification_export(value)


def write_verification_export(path, store, clock=time.time):
    path = Path(path)
    prior_revision = -1
    if path.exists() or path.is_symlink():
        prior_revision = _read_verification_export(path)["generated_at"]
    records = sorted(
        (row for row in store.entries() if row["phase"] == "final"),
        key=lambda row: row["key"],
    )
    value = {
        "schema": 1,
        # This is both the creation time and the strictly increasing export
        # revision.  Advancing beyond the installed export makes same-second
        # writes ordered and lets clients reject delayed or replayed snapshots.
        "generated_at": max(int(clock()), prior_revision + 1),
        "records": records,
        "records_sha256": "sha256:" + hashlib.sha256(_canonical_records(records)).hexdigest(),
    }
    value = validate_verification_export(value)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _atomic(path, data)
    return value


def _blank(row, status, error, clock):
    checked = int(clock())
    return {
        "schema": 3,
        "key": row["key"],
        "source": row["source"],
        "target": row["target"],
        "status": status,
        "phase": "provisional",
        "receipt_count": row["received_count"],
        "relation": None,
        "mention_class": None,
        "source_item_id": None,
        "source_origin": None,
        "source_version": None,
        "source_kind": None,
        "source_author": None,
        "source_page": None,
        "verified_at": checked,
        "checked_at": checked,
        "attempt_error": error,
        "error": error,
    }


class InboundVerifierWorker:
    def __init__(
        self,
        queue,
        registry,
        verified_root,
        *,
        fetcher=fetch_bounded,
        clock=time.time,
        batch=BATCH_LIMIT,
        export_path=None,
    ):
        if type(batch) is not int or not 0 < batch <= BATCH_LIMIT:
            raise ValueError("Invalid inbound verification batch limit.")
        self.queue = queue
        self.registry = validate_target_registry(registry)
        self.store = VerificationStore(verified_root)
        self.fetcher = fetcher
        self.clock = clock
        self.batch = batch
        self.lock_path = self.store.root / "worker.lock"
        self.export_path = Path(export_path) if export_path is not None else None

    def _record(self, row):
        prior = self.store.read(row["key"])
        verifier = StructuralVerifier(self.registry, self.fetcher, self.clock)
        try:
            details = verifier.verify(row)
            result = _blank(row, "verified", None, self.clock)
            result.update(details)
        except VerificationFailure as error:
            deterministic = error.code != "fetch_failed"
            if not deterministic and prior and prior["status"] in ("verified", "gone"):
                result = copy.deepcopy(prior)
                result.update(
                    schema=3,
                    phase="provisional",
                    receipt_count=row["received_count"],
                    checked_at=int(self.clock()),
                    attempt_error=error.code,
                )
            else:
                status = "gone" if deterministic and prior and prior["status"] in ("verified", "gone") else "failed"
                result = _blank(row, status, error.code, self.clock)
                if status == "gone":
                    result["mention_class"] = prior.get("mention_class")
            if not deterministic:
                result["phase"] = "final"
                self.store.write(result)
                retried = self.queue.retry(
                    row["key"],
                    received_count=row["received_count"],
                    delays=RETRY_DELAYS,
                )
                return retried is not None and retried["status"] == "failed"
        self.store.write(result)
        completed = self.queue.complete(
            row["key"], result["status"], received_count=row["received_count"]
        )
        if completed is not None:
            result["phase"] = "final"
            self.store.write(result)
        return completed is not None

    def _reconcile(self):
        queue = {row["key"]: row for row in self.queue.entries()}
        for record in self.store.entries():
            row = queue.get(record["key"])
            # Intake owns terminal retention.  Once it deliberately prunes an
            # old pair, remove the matching derived record before rebuilding
            # the complete export so verified storage cannot grow forever.
            if row is None:
                self.store.delete(record["key"])
                continue
            if record["phase"] != "provisional":
                continue
            if row and row["received_count"] == record["receipt_count"] and row["status"] == record["status"]:
                record["phase"] = "final"
                self.store.write(record)
            elif row["status"] == "pending":
                self.store.delete(record["key"])

    def run(self):
        handle = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(handle, "r+") as lock:
                details = os.fstat(lock.fileno())
                if (
                    not stat.S_ISREG(details.st_mode)
                    or details.st_nlink != 1
                    or details.st_mode & 0o777 != 0o600
                ):
                    raise ValueError("Unsafe inbound verification worker lock.")
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 0
                self._reconcile()
                count = 0
                for row in self.queue.due()[: self.batch]:
                    count += int(self._record(row))
                if self.export_path is not None:
                    write_verification_export(self.export_path, self.store, self.clock)
                return count
        finally:
            # fdopen owns the descriptor on the normal path.
            try:
                os.close(handle)
            except OSError:
                pass
