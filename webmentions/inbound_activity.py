"""Semantic activity classification for verified inbound relationships."""

import hashlib
import json

from .inbound_verifier import validate_verification_record


ACTIVITY_KINDS = ("new", "update", "withdrawal")


def semantic_fingerprint(record):
    """Ignore receipts, check times, and transient diagnostics."""
    record = validate_verification_record(record)
    if record["status"] == "failed":
        return None
    value = {
        "source": record["source"],
        "target": record["target"],
        "status": record["status"],
        "relation": record["relation"],
        "mention_class": record["mention_class"],
        "source_item_id": record["source_item_id"],
        "source_origin": record["source_origin"],
        "source_version": record["source_version"],
        "source_kind": record["source_kind"],
        "source_author": record["source_author"],
        "source_page": record["source_page"],
    }
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_activity(previous, incoming):
    """Return a user-visible activity kind, or None for diagnostic/duplicate work."""
    incoming = validate_verification_record(incoming)
    before = semantic_fingerprint(previous) if previous is not None else None
    after = semantic_fingerprint(incoming)
    if after is None or after == before:
        return None
    if incoming["status"] == "gone":
        return "withdrawal" if previous is not None and previous["status"] == "verified" else None
    if before is None:
        return "new"
    return "update"
