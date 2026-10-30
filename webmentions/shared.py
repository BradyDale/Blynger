"""Shared validation and redaction for outbound Webmentions."""

import copy
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


ID = re.compile(r"^[0-7][0-9a-hjkmnp-tv-z]{25}$")
RELATIONS = ("stub", "transclusion", "fork", "source", "link")
STATUSES = ("pending", "retrying", "delivered", "rejected", "no_endpoint", "abandoned")
TERMINAL_STATUSES = ("delivered", "rejected", "no_endpoint", "abandoned")
RETRY_DELAYS = (15 * 60, 60 * 60, 4 * 60 * 60, 12 * 60 * 60, 24 * 60 * 60)
STATUS_ENTRY_LIMIT = 200
CANDIDATE_FIELDS = {
    "key",
    "source",
    "source_id",
    "source_version",
    "target_url",
    "target_origin",
    "target_id",
    "relations",
    "target_versions",
    "withdrawal",
}
RECORD_FIELDS = CANDIDATE_FIELDS | {
    "status",
    "created_at",
    "updated_at",
    "attempts",
    "endpoint",
    "error",
    "next_attempt_at",
}


def _status_url(value):
    """Return a useful URL for local status without exposing credentials."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        host = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return None


def _status_error(value):
    if not isinstance(value, str) or not value:
        return None
    # Network errors may echo a URL. Keep the useful origin/path while removing
    # query credentials before the message crosses the private status API.
    cleaned = re.sub(
        r"https?://[^\s<>\"']+",
        lambda match: _status_url(match.group(0)) or "remote URL",
        value,
    )
    return cleaned[:500]


def _status_entry(row):
    return {
        "key": row["key"],
        "status": row["status"],
        "source": _status_url(row["source"]),
        "source_id": row["source_id"],
        "target": _status_url(row["target_url"]),
        "target_origin": _status_url(row["target_origin"]),
        "target_id": row["target_id"],
        "relations": list(row["relations"]),
        "withdrawal": row["withdrawal"],
        "attempts": row["attempts"],
        "endpoint": _status_url(row["endpoint"]),
        "error": _status_error(row["error"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "next_attempt_at": row["next_attempt_at"],
    }


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _absolute_url(value, *, keep_fragment=True):
    if not isinstance(value, str):
        raise ValueError("URL is not text.")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("URL must be an absolute public HTTP(S) URL.")
    host = parsed.hostname.lower()
    if parsed.port and parsed.port != (443 if parsed.scheme == "https" else 80):
        host += f":{parsed.port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            host,
            parsed.path or "/",
            parsed.query,
            parsed.fragment if keep_fragment else "",
        )
    )


def _origin(value):
    result = _absolute_url(value, keep_fragment=False)
    parsed = urlsplit(result)
    if parsed.query:
        raise ValueError("Blyg origins cannot contain a query string.")
    return result.rstrip("/") + "/"


def _candidate(value):
    if not isinstance(value, dict) or set(value) != CANDIDATE_FIELDS:
        raise ValueError("Invalid Webmention candidate fields.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("key", ""))):
        raise ValueError("Invalid Webmention candidate key.")
    unsigned = {name: copy.deepcopy(value[name]) for name in CANDIDATE_FIELDS if name != "key"}
    if _digest(unsigned) != value["key"]:
        raise ValueError("Invalid Webmention candidate checksum.")
    _absolute_url(value["source"], keep_fragment=False)
    if not ID.fullmatch(str(value["source_id"])):
        raise ValueError("Invalid Webmention candidate source id.")
    if type(value["source_version"]) is not int or value["source_version"] < 1:
        raise ValueError("Invalid Webmention candidate source version.")
    if value["target_url"] is not None:
        _absolute_url(value["target_url"])
    if value["target_origin"] is not None:
        _origin(value["target_origin"])
        if not ID.fullmatch(str(value["target_id"])):
            raise ValueError("Invalid Webmention candidate target id.")
    elif value["target_id"] is not None or value["target_url"] is None:
        raise ValueError("Invalid Webmention candidate target.")
    relations = value["relations"]
    if (
        not isinstance(relations, list)
        or not relations
        or len(relations) != len(set(relations))
        or any(relation not in RELATIONS for relation in relations)
    ):
        raise ValueError("Invalid Webmention candidate relations.")
    if not isinstance(value["target_versions"], dict) or set(value["target_versions"]) != set(relations):
        raise ValueError("Invalid Webmention candidate target versions.")
    for version in value["target_versions"].values():
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("Invalid Webmention candidate target version.")
    if type(value["withdrawal"]) is not bool:
        raise ValueError("Invalid Webmention candidate withdrawal flag.")
    return copy.deepcopy(value)


def _record(value):
    if not isinstance(value, dict) or set(value) != RECORD_FIELDS:
        raise ValueError("Invalid Webmention outbox record fields.")
    candidate = _candidate({name: value[name] for name in CANDIDATE_FIELDS})
    if value["status"] not in STATUSES:
        raise ValueError("Invalid Webmention outbox status.")
    for name in ("created_at", "updated_at"):
        if not isinstance(value[name], str) or not value[name]:
            raise ValueError("Invalid Webmention outbox timestamp.")
    if type(value["attempts"]) is not int or value["attempts"] < 0:
        raise ValueError("Invalid Webmention outbox attempt count.")
    for name in ("endpoint", "error", "next_attempt_at"):
        if value[name] is not None and not isinstance(value[name], str):
            raise ValueError(f"Invalid Webmention outbox {name}.")
    return {**candidate, **{name: copy.deepcopy(value[name]) for name in RECORD_FIELDS - CANDIDATE_FIELDS}}
