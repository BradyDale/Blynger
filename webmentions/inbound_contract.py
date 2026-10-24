"""Inactive, side-effect-free contract for a future inbound Webmention endpoint.

This module deliberately performs no network access and no persistence.  It is
the executable specification shared by the later host receiver and its tests;
importing it cannot make Blynger receive or advertise Webmentions.
"""

from dataclasses import dataclass
import ipaddress
import re
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit, urlunsplit


LIMITS = MappingProxyType(
    {
        "body_bytes": 8 * 1024,
        "url_characters": 2048,
        "state_bytes": 16 * 1024 * 1024,
        "active_writers": 4,
        "lock_seconds": 2,
        "pending_pairs": 200,
        "stored_pairs": 2000,
        "terminal_retention_days": 90,
        "ip_per_minute": 10,
        "ip_per_hour": 50,
        "source_host_per_minute": 10,
        "source_host_per_hour": 50,
        "source_group_per_hour": 25,
        "source_group_per_day": 100,
        "global_per_minute": 30,
        "global_per_hour": 100,
        "global_per_day": 500,
    }
)
POLICY_MODES = ("off", "open", "denylist", "allowlist")


class InboundContractError(ValueError):
    """A public receiver response, expressed without reflecting hostile input."""

    def __init__(self, status, code, message, *, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after

    @property
    def headers(self):
        headers = response_headers()
        if self.status == 405:
            headers["Allow"] = "POST"
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        return headers


@dataclass(frozen=True)
class InboundClaim:
    source: str
    target: str
    source_host: str

    @property
    def key(self):
        return (self.source, self.target)


@dataclass(frozen=True)
class ReceiverPolicy:
    mode: str = "open"
    domains: tuple = ()

    def __post_init__(self):
        if self.mode not in POLICY_MODES:
            raise ValueError("Invalid inbound Webmention policy mode.")
        normalized = tuple(sorted({_policy_domain(value) for value in self.domains}))
        object.__setattr__(self, "domains", normalized)

    def permits(self, host):
        if self.mode == "off":
            return False
        matched = any(host == domain or host.endswith("." + domain) for domain in self.domains)
        if self.mode == "allowlist":
            return matched
        if self.mode == "denylist":
            return not matched
        return True


def _policy_domain(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid inbound Webmention policy domain.")
    value = value.strip().lower().rstrip(".")
    try:
        return ipaddress.ip_address(value.strip("[]")).compressed
    except ValueError:
        pass
    if "://" in value or "/" in value or ":" in value:
        raise ValueError("Policy entries must be host names, not URLs.")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("Invalid inbound Webmention policy domain.") from error
    if len(value) > 253 or any(not label or len(label) > 63 for label in value.split(".")):
        raise ValueError("Invalid inbound Webmention policy domain.")
    return value


def _request_url(value, label):
    if not isinstance(value, str) or not value or len(value) > LIMITS["url_characters"]:
        raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.") from error
    if (
        parsed.scheme.lower() not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.") from error
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        labels = host.split(".")
        if len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in labels
        ):
            raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.")
    else:
        if not address.is_global:
            raise InboundContractError(400, "invalid_" + label, f"Invalid {label} URL.")
        host = address.compressed
        if address.version == 6:
            host = "[" + host + "]"
    default = 443 if parsed.scheme.lower() == "https" else 80
    authority = host if port in (None, default) else f"{host}:{port}"
    normalized = urlunsplit(
        (parsed.scheme.lower(), authority, parsed.path or "/", parsed.query, "")
    )
    return normalized, host.strip("[]")


def _media_type(value):
    if not isinstance(value, str):
        return None
    parts = [part.strip() for part in value.split(";")]
    if parts[0].lower() != "application/x-www-form-urlencoded":
        return None
    for parameter in parts[1:]:
        name, separator, setting = parameter.partition("=")
        if not separator or name.strip().lower() != "charset" or setting.strip(' "').lower() != "utf-8":
            return None
    return parts[0].lower()


def parse_inbound_request(*, method, content_type, body, own_origin, policy=None):
    """Parse through policy; return None when policy silently suppresses it."""
    policy = policy or ReceiverPolicy()
    if policy.mode == "off":
        raise InboundContractError(
            503, "receiver_disabled", "Webmention receiving is temporarily disabled.", retry_after=3600
        )
    if method != "POST":
        raise InboundContractError(405, "method_not_allowed", "POST required.")
    if _media_type(content_type) is None:
        raise InboundContractError(415, "unsupported_media_type", "Form encoding required.")
    if not isinstance(body, bytes) or len(body) > LIMITS["body_bytes"]:
        raise InboundContractError(413, "request_too_large", "Request is too large.")
    try:
        text = body.decode("utf-8", "strict")
        if re.search(r"%(?![0-9a-fA-F]{2})", text):
            raise ValueError("Invalid percent escape.")
        pairs = parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=3,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeError, ValueError) as error:
        raise InboundContractError(400, "invalid_form", "Invalid form body.") from error
    if len(pairs) != 2 or {name for name, _ in pairs} != {"source", "target"}:
        raise InboundContractError(400, "invalid_form", "Exactly one source and target are required.")
    values = dict(pairs)
    source, source_host = _request_url(values["source"], "source")
    if not policy.permits(source_host):
        return None
    target, _ = _request_url(values["target"], "target")
    own, _ = _request_url(own_origin, "target")
    if urlsplit(own).query:
        raise ValueError("The configured Blyg identity origin cannot contain a query.")
    if not own.endswith("/"):
        own += "/"
    if source == target:
        raise InboundContractError(400, "same_source_target", "Source and target must differ.")
    if not target.startswith(own):
        raise InboundContractError(400, "foreign_target", "Target is not part of this blyg.")
    return InboundClaim(source, target, source_host)


def require_published_target(claim, published_targets):
    """Apply exact registry membership after the caller has charged rate state."""
    allowed = {_request_url(value, "target")[0] for value in published_targets}
    if claim.target not in allowed:
        raise InboundContractError(400, "unknown_target", "Target is not a published item.")
    return claim


def parse_inbound_claim(*, method, content_type, body, own_origin, published_targets, policy=None):
    """Convenience composition for callers that do not own rate state."""
    claim = parse_inbound_request(
        method=method,
        content_type=content_type,
        body=body,
        own_origin=own_origin,
        policy=policy,
    )
    if claim is None:
        return None
    return require_published_target(claim, published_targets)


def capacity_error(kind):
    """Return the fixed response for a later rate/queue/concurrency refusal."""
    if kind == "rate":
        return InboundContractError(429, "rate_limited", "Too many Webmentions.", retry_after=3600)
    if kind in ("queue", "storage", "lock", "writers"):
        return InboundContractError(
            503, "receiver_busy", "Webmention receiving is temporarily unavailable.", retry_after=600
        )
    raise ValueError("Unknown inbound Webmention capacity condition.")


def response_headers():
    """Headers required on every future receiver response."""
    return {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
    }
