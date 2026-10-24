"""Inactive CGI intake valve for inbound Webmentions.

Nothing imports or advertises this module from the Blynger application.  A host
may execute it only after the later deployment and security checkpoints.
"""

import fcntl
import ipaddress
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .inbound_contract import (
    InboundContractError,
    LIMITS,
    ReceiverPolicy,
    _media_type,
    _request_url,
    capacity_error,
    parse_inbound_request,
    response_headers,
)
from .inbound_queue import InboundQueue, InboundStoreError, open_shared_lock
from .inbound_targets import validate_target_registry
from .inbound_registry import validate_registry_artifact


STATUS_TEXT = {202: "Accepted", 400: "Bad Request", 405: "Method Not Allowed", 413: "Payload Too Large", 415: "Unsupported Media Type", 429: "Too Many Requests", 503: "Service Unavailable"}


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key.")
        value[key] = item
    return value


def _safe_json(path, *, maximum, private):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Unsafe receiver data path.")
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size > maximum:
        raise ValueError("Unsafe receiver data file.")
    forbidden = 0o027 if private else 0o022
    if details.st_mode & forbidden:
        raise ValueError("Unsafe receiver data permissions.")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)


def load_configuration(path):
    value = _safe_json(path, maximum=64 * 1024, private=True)
    required = {"schema", "origin", "policy", "registry", "queue", "public_suffixes"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"limits"}:
        raise ValueError("Invalid receiver configuration.")
    policy = value["policy"]
    if value["schema"] != 1 or not isinstance(policy, dict) or set(policy) != {"mode", "domains"}:
        raise ValueError("Invalid receiver configuration.")
    if not isinstance(policy["domains"], list) or len(policy["domains"]) > 1000:
        raise ValueError("Invalid receiver configuration.")
    origin, _ = _request_url(value["origin"], "target")
    if urlsplit(origin).query:
        raise ValueError("The configured Blyg origin cannot contain a query.")
    origin = origin.rstrip("/") + "/"
    result = {
        "origin": origin,
        "policy": ReceiverPolicy(policy["mode"], tuple(policy["domains"])),
        "registry": Path(value["registry"]),
        "queue": Path(value["queue"]),
        "public_suffixes": Path(value["public_suffixes"]),
        "limits": value.get("limits") or {},
    }
    if any(not path.is_absolute() for path in (result["registry"], result["queue"], result["public_suffixes"])):
        raise ValueError("Receiver paths must be absolute.")
    queue = result["queue"]
    if queue.is_symlink() or not queue.is_dir() or queue.stat().st_mode & 0o007:
        raise ValueError("The inbound queue directory is unsafe.")
    return result


def load_registry(path, origin):
    value = _safe_json(path, maximum=8 * 1024 * 1024, private=True)
    if isinstance(value, dict) and value.get("schema") == 1 and "registry" in value:
        value = validate_registry_artifact(value)["registry"]
    return validate_target_registry(value, origin)


class PublicSuffixList:
    """Small PSL parser; the deployed configuration points at a bundled snapshot."""

    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Unsafe public suffix snapshot path.")
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size > 2 * 1024 * 1024 or details.st_mode & 0o022:
            raise ValueError("Unsafe public suffix snapshot.")
        exact, wildcard, exception = set(), set(), set()
        version = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("// VERSION:"):
                version = line.partition(":")[2].strip()
            if not line or line.startswith("//"):
                continue
            kind, rule = (exception, line[1:]) if line.startswith("!") else (wildcard, line[2:]) if line.startswith("*.") else (exact, line)
            normalized = rule.strip(".").lower().encode("idna").decode("ascii")
            if normalized:
                kind.add(tuple(normalized.split(".")))
        if not version or not exact:
            raise ValueError("The public suffix snapshot is unversioned or empty.")
        self.version, self.exact, self.wildcard, self.exception = version, exact, wildcard, exception

    def registrable(self, host):
        try:
            return ipaddress.ip_address(host).compressed
        except ValueError:
            labels = tuple(host.lower().rstrip(".").split("."))
        exception = max((len(rule) for rule in self.exception if labels[-len(rule):] == rule), default=0)
        if exception:
            suffix = exception - 1
        else:
            exact = max((len(rule) for rule in self.exact if labels[-len(rule):] == rule), default=1)
            wildcard = max((len(rule) + 1 for rule in self.wildcard if len(labels) > len(rule) and labels[-len(rule):] == rule), default=0)
            suffix = max(exact, wildcard)
        return ".".join(labels[-min(len(labels), suffix + 1):])


class WriterSlot:
    def __init__(self, root, count):
        self.root, self.count, self.handle = Path(root), int(count), None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o770)
        for number in range(self.count):
            path = self.root / f"inbound-writer-{number}.lock"
            descriptor = open_shared_lock(path)
            handle = os.fdopen(descriptor, "a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.handle = handle
                return self
            except BlockingIOError:
                handle.close()
        raise capacity_error("writers")

    def __exit__(self, *_):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None


def _read_body(environment, stream):
    try:
        length = int(environment.get("CONTENT_LENGTH", ""))
    except (TypeError, ValueError) as error:
        raise InboundContractError(400, "invalid_form", "Invalid form body.") from error
    if length < 0:
        raise InboundContractError(400, "invalid_form", "Invalid form body.")
    if length > LIMITS["body_bytes"]:
        raise InboundContractError(413, "request_too_large", "Request is too large.")
    body = stream.read(length)
    if len(body) != length:
        raise InboundContractError(400, "invalid_form", "Invalid form body.")
    return body


def receive(environment, stream):
    config_path = environment.get("BLYNGER_WEBMENTION_CONFIG")
    if not config_path:
        raise ValueError("Receiver configuration is unavailable.")
    config = load_configuration(config_path)
    if config["policy"].mode == "off":
        raise InboundContractError(503, "receiver_disabled", "Webmention receiving is temporarily disabled.", retry_after=3600)
    if environment.get("REQUEST_METHOD", "") != "POST":
        raise InboundContractError(405, "method_not_allowed", "POST required.")
    if _media_type(environment.get("CONTENT_TYPE", "")) is None:
        raise InboundContractError(415, "unsupported_media_type", "Form encoding required.")
    body = _read_body(environment, stream)
    claim = parse_inbound_request(
        method=environment.get("REQUEST_METHOD", ""),
        content_type=environment.get("CONTENT_TYPE", ""),
        body=body,
        own_origin=config["origin"],
        policy=config["policy"],
    )
    if claim is None:
        return
    peer = environment.get("REMOTE_ADDR", "")
    suffixes = PublicSuffixList(config["public_suffixes"])
    registry = load_registry(config["registry"], config["origin"])
    writers = config["limits"].get("active_writers", LIMITS["active_writers"])
    if type(writers) is not int or not 0 < writers <= LIMITS["active_writers"]:
        raise ValueError("Invalid receiver writer limit.")
    with WriterSlot(config["queue"], writers):
        queue = InboundQueue(config["queue"], limits=config["limits"])
        queue.accept(
            claim,
            peer=peer,
            source_group=suffixes.registrable(claim.source_host),
            published_targets=registry["targets"],
        )


def _emit(status, message, headers=None, output=None):
    output = output or sys.stdout
    all_headers = response_headers()
    all_headers.update(headers or {})
    output.write(f"Status: {status} {STATUS_TEXT[status]}\r\n")
    for name, value in all_headers.items():
        output.write(f"{name}: {value}\r\n")
    output.write("\r\n" + message + "\n")


def main(environment=None, stream=None, output=None):
    environment = os.environ if environment is None else environment
    stream = sys.stdin.buffer if stream is None else stream
    try:
        receive(environment, stream)
        _emit(202, "Webmention accepted for processing.", output=output)
        return 0
    except InboundContractError as error:
        _emit(error.status, error.message, error.headers, output)
        return 0
    except Exception:
        error = capacity_error("storage")
        _emit(error.status, error.message, error.headers, output)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
