"""Inactive durable intake and rate state for inbound Webmention claims."""

import copy
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
import tempfile
import threading
import time
from pathlib import Path

from .inbound_contract import (
    InboundClaim,
    InboundContractError,
    LIMITS,
    _policy_domain,
    _request_url,
    capacity_error,
    require_published_target,
)


INBOUND_STATUSES = ("pending", "verified", "gone", "failed")
TERMINAL_INBOUND_STATUSES = ("verified", "gone", "failed")
ENTRY_FIELDS = {
    "key",
    "source",
    "target",
    "source_host",
    "source_group",
    "status",
    "first_received_at",
    "last_received_at",
    "updated_at",
    "received_count",
    "retry_count",
    "retry_at",
}
LEGACY_ENTRY_FIELDS = ENTRY_FIELDS - {"retry_count", "retry_at"}
_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class InboundStoreError(RuntimeError):
    """The intake store cannot safely accept work."""


def open_shared_lock(path):
    """Create once with the shared mode; thereafter validate without chmod.

    The receiver and verifier intentionally run as different identities. Each
    may open a group-writable lock, but neither may chmod a file owned by the
    other identity.
    """
    path = Path(path)
    base = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        try:
            descriptor = os.open(path, base | os.O_CREAT | os.O_EXCL, 0o660)
            created = True
            os.fchmod(descriptor, 0o660)
        except FileExistsError:
            descriptor = os.open(path, base)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o660
        ):
            raise InboundStoreError("Inbound Webmention lock has unsafe permissions.")
        return descriptor
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _thread_lock(path):
    key = str(Path(path).resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _atomic(path, text, mode=0o660):
    _atomic_bytes(path, text.encode("utf-8"), mode)


def _atomic_bytes(path, data, mode=0o660):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _regular_file(path, *, require_private=True):
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise InboundStoreError("Inbound Webmention state is not a private regular file.")
    if require_private and details.st_mode & 0o117:
        raise ValueError("Inbound Webmention state has unsafe permissions.")
    return details


def _entry_key(source, target):
    return hashlib.sha256((source + "\0" + target).encode()).hexdigest()


def _rate_key(scope, identity, window):
    material = f"{scope}\0{window}\0{identity}".encode()
    return hashlib.sha256(material).hexdigest()


def _record(value):
    if not isinstance(value, dict) or set(value) not in (ENTRY_FIELDS, LEGACY_ENTRY_FIELDS):
        raise ValueError("Invalid inbound Webmention record fields.")
    if set(value) == LEGACY_ENTRY_FIELDS:
        value = {**value, "retry_count": 0, "retry_at": 0}
    source, source_host = _request_url(value["source"], "source")
    target, _ = _request_url(value["target"], "target")
    if value["key"] != _entry_key(source, target):
        raise ValueError("Invalid inbound Webmention record key.")
    if value["source_host"] != source_host:
        raise ValueError("Invalid inbound Webmention source host.")
    try:
        address = ipaddress.ip_address(source_host)
    except ValueError:
        group = _policy_domain(value["source_group"])
        if source_host != group and not source_host.endswith("." + group):
            raise ValueError("Invalid inbound Webmention source group.")
    else:
        group = address.compressed
        if value["source_group"] != group:
            raise ValueError("Invalid inbound Webmention source group.")
    if value["status"] not in INBOUND_STATUSES:
        raise ValueError("Invalid inbound Webmention status.")
    for name in ("first_received_at", "last_received_at", "updated_at"):
        if type(value[name]) is not int or value[name] < 0:
            raise ValueError("Invalid inbound Webmention timestamp.")
    if type(value["received_count"]) is not int or value["received_count"] < 1:
        raise ValueError("Invalid inbound Webmention receipt count.")
    if type(value["retry_count"]) is not int or not 0 <= value["retry_count"] <= 100:
        raise ValueError("Invalid inbound Webmention retry count.")
    if type(value["retry_at"]) is not int or value["retry_at"] < 0:
        raise ValueError("Invalid inbound Webmention retry timestamp.")
    if value["status"] != "pending" and (value["retry_count"] or value["retry_at"]):
        raise ValueError("Terminal inbound Webmention work cannot retain a retry schedule.")
    return copy.deepcopy(value)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key in inbound Webmention state.")
        result[key] = value
    return result


class InboundQueue:
    """Cross-process, bounded storage; it performs no source fetches."""

    def __init__(self, root, clock=time.time, limits=None):
        self.root = Path(root)
        self.file = self.root / "inbound-state.json"
        self.backup = self.root / "inbound-state.backup.json"
        self.lock_file = self.root / "inbound-state.lock"
        self.clock = clock
        self.limits = dict(LIMITS)
        if limits:
            for name, value in limits.items():
                numeric = (
                    type(value) in (int, float)
                    if name == "lock_seconds"
                    else type(value) is int
                )
                if name not in self.limits or not numeric or value <= 0:
                    raise ValueError("Invalid inbound Webmention limit override.")
                if value > self.limits[name]:
                    raise ValueError("Inbound Webmention limits may only be lowered.")
                self.limits[name] = value
        self.thread_lock = _thread_lock(self.lock_file)
        self.recovery_notice = ""
        self.damaged_file = None
        self.root.mkdir(parents=True, exist_ok=True, mode=0o770)
        with self._locked():
            self._open()

    def _empty(self):
        return {"schema": 1, "entries": {}, "rates": {}}

    def _locked(self):
        return _FileLock(self.lock_file, self.thread_lock, self.limits["lock_seconds"])

    def _render(self, state):
        text = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        if len(text.encode()) > self.limits["state_bytes"]:
            raise capacity_error("storage")
        return text

    def _load(self, path):
        details = _regular_file(path)
        if details.st_size > self.limits["state_bytes"]:
            raise ValueError("Inbound Webmention state exceeds its size limit.")
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_object)
        if not isinstance(data, dict) or set(data) != {"schema", "entries", "rates"}:
            raise ValueError("Invalid inbound Webmention state document.")
        if data["schema"] != 1 or not isinstance(data["entries"], dict) or not isinstance(data["rates"], dict):
            raise ValueError("Invalid inbound Webmention state document.")
        entries = {}
        for key, value in data["entries"].items():
            row = _record(value)
            if key != row["key"]:
                raise ValueError("Inbound Webmention state key does not match its record.")
            entries[key] = row
        if len(entries) > LIMITS["stored_pairs"]:
            raise ValueError("Inbound Webmention state exceeds its record limit.")
        if sum(row["status"] == "pending" for row in entries.values()) > LIMITS["pending_pairs"]:
            raise ValueError("Inbound Webmention state exceeds its pending limit.")
        rates = {}
        for key, values in data["rates"].items():
            if not re.fullmatch(r"[0-9a-f]{64}", str(key)) or not isinstance(values, list):
                raise ValueError("Invalid inbound Webmention rate state.")
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError("Invalid inbound Webmention rate timestamp.")
            rates[key] = sorted(values)
        if len(rates) > 5000 or sum(map(len, rates.values())) > 10000:
            raise ValueError("Inbound Webmention rate state exceeds its limit.")
        return {"schema": 1, "entries": entries, "rates": rates}

    def _preserve(self):
        if not self.file.exists() or self.file.is_symlink():
            return None
        details = _regular_file(self.file, require_private=False)
        if details.st_size > self.limits["state_bytes"]:
            # The original remains in place as the preserved evidence. Copying
            # an attacker-sized file would compound the storage exhaustion.
            raise InboundStoreError("Oversized inbound Webmention state was left untouched.")
        payload = self.file.read_bytes()
        fingerprint = hashlib.sha256(payload).hexdigest()[:16]
        candidate = self.root / f"inbound-state.damaged-{fingerprint}.json"
        if candidate.exists():
            try:
                existing = _regular_file(candidate)
                matches = existing.st_size == len(payload) and candidate.read_bytes() == payload
            except (OSError, ValueError, InboundStoreError):
                matches = False
            if not matches:
                _atomic_bytes(candidate, payload)
        else:
            _atomic_bytes(candidate, payload)
        self.damaged_file = candidate
        return candidate

    def _open(self):
        if not self.file.exists():
            if self.backup.exists():
                try:
                    self.state = self._load(self.backup)
                except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as error:
                    raise InboundStoreError(
                        "Inbound Webmention state is missing and its backup is not usable."
                    ) from error
                _atomic(self.file, self._render(self.state))
                self.recovery_notice = "Inbound Webmention state recovered after its main file disappeared."
                return
            self.state = self._empty()
            return
        try:
            self.state = self._load(self.file)
            return
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
            self._preserve()
        try:
            self.state = self._load(self.backup)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as error:
            raise InboundStoreError(
                "Inbound Webmention state is damaged and no verified backup is available."
            ) from error
        _atomic(self.file, self._render(self.state))
        self.recovery_notice = (
            "Inbound Webmention state recovered from its last verified backup; damaged data was preserved."
        )

    def _save(self, state, prior):
        try:
            if self.file.exists():
                _regular_file(self.file)
                _atomic(self.backup, self._render(prior))
            _atomic(self.file, self._render(state))
        except InboundContractError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise capacity_error("storage") from error
        self.state = state

    def _refresh(self):
        self._open()

    def _rules(self, peer, host, group):
        return (
            ("ip-minute", peer, 60, int(self.limits["ip_per_minute"])),
            ("ip-hour", peer, 3600, int(self.limits["ip_per_hour"])),
            ("host-minute", host, 60, int(self.limits["source_host_per_minute"])),
            ("host-hour", host, 3600, int(self.limits["source_host_per_hour"])),
            ("group-hour", group, 3600, int(self.limits["source_group_per_hour"])),
            ("group-day", group, 86400, int(self.limits["source_group_per_day"])),
            ("global-minute", "*", 60, int(self.limits["global_per_minute"])),
            ("global-hour", "*", 3600, int(self.limits["global_per_hour"])),
            ("global-day", "*", 86400, int(self.limits["global_per_day"])),
        )

    def _charge(self, state, peer, host, group, now):
        active = {}
        for scope, identity, window, limit in self._rules(peer, host, group):
            key = _rate_key(scope, identity, window)
            values = [value for value in state["rates"].get(key, ()) if value > now - window]
            if len(values) >= limit:
                raise capacity_error("rate")
            active[key] = values
        state["rates"] = {
            key: [value for value in values if value > now - 86400]
            for key, values in state["rates"].items()
            if any(value > now - 86400 for value in values)
        }
        for key, values in active.items():
            state["rates"][key] = values + [now]

    def _source_group(self, claim, group):
        try:
            address = ipaddress.ip_address(claim.source_host)
        except ValueError:
            normalized = _policy_domain(group)
            if claim.source_host != normalized and not claim.source_host.endswith("." + normalized):
                raise ValueError("Source group does not contain the source host.")
            return normalized
        if str(group) != address.compressed:
            raise ValueError("An IP source must group as itself.")
        return address.compressed

    def _peer(self, value):
        try:
            return ipaddress.ip_address(value).compressed
        except ValueError as error:
            raise ValueError("Invalid Webmention peer address.") from error

    def _prune_terminal(self, state, now, needed=1):
        cutoff = now - int(self.limits["terminal_retention_days"] * 86400)
        eligible = sorted(
            (
                row for row in state["entries"].values()
                if row["status"] in TERMINAL_INBOUND_STATUSES and row["updated_at"] <= cutoff
            ),
            key=lambda row: (row["updated_at"], row["key"]),
        )
        for row in eligible[:needed]:
            del state["entries"][row["key"]]

    def accept(self, claim, *, peer, source_group, published_targets):
        """Charge, validate the target, and durably create or refresh one pair."""
        if not isinstance(claim, InboundClaim):
            raise ValueError("Invalid inbound Webmention claim.")
        peer = self._peer(peer)
        source_group = self._source_group(claim, source_group)
        now = int(self.clock())
        key = _entry_key(claim.source, claim.target)
        with self._locked():
            try:
                self._refresh()
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as error:
                raise InboundStoreError("Inbound Webmention state became unreadable.") from error
            prior = copy.deepcopy(self.state)
            state = copy.deepcopy(self.state)
            self._charge(state, peer, claim.source_host, source_group, now)
            try:
                require_published_target(claim, published_targets)
            except InboundContractError:
                self._save(state, prior)
                raise
            current = state["entries"].get(key)
            pending = sum(row["status"] == "pending" for row in state["entries"].values())
            reopening = current is not None and current["status"] != "pending"
            if current is None and len(state["entries"]) >= int(self.limits["stored_pairs"]):
                self._prune_terminal(state, now)
                if len(state["entries"]) >= int(self.limits["stored_pairs"]):
                    self._save(state, prior)
                    raise capacity_error("storage")
            if (current is None or reopening) and pending >= int(self.limits["pending_pairs"]):
                self._save(state, prior)
                raise capacity_error("queue")
            if current is None:
                row = {
                    "key": key,
                    "source": claim.source,
                    "target": claim.target,
                    "source_host": claim.source_host,
                    "source_group": source_group,
                    "status": "pending",
                    "first_received_at": now,
                    "last_received_at": now,
                    "updated_at": now,
                    "received_count": 1,
                    "retry_count": 0,
                    "retry_at": 0,
                }
            else:
                row = copy.deepcopy(current)
                row.update(
                    {
                        "source_group": source_group,
                        "status": "pending",
                        "last_received_at": now,
                        "updated_at": now,
                        "received_count": current["received_count"] + 1,
                        "retry_count": 0,
                        "retry_at": 0,
                    }
                )
            state["entries"][key] = _record(row)
            self._save(state, prior)
            return copy.deepcopy(row)

    def set_status(self, key, status):
        """Stage-5 seam used now only to test retention and re-verification."""
        if status not in INBOUND_STATUSES:
            raise ValueError("Invalid inbound Webmention status.")
        now = int(self.clock())
        with self._locked():
            self._refresh()
            if key not in self.state["entries"]:
                raise KeyError(key)
            prior = copy.deepcopy(self.state)
            state = copy.deepcopy(self.state)
            row = copy.deepcopy(state["entries"][key])
            row.update({"status": status, "updated_at": now, "retry_count": 0, "retry_at": 0})
            state["entries"][key] = _record(row)
            self._save(state, prior)
            return copy.deepcopy(row)

    def complete(self, key, status, *, received_count):
        """Finish only the exact receipt snapshot a verifier processed.

        A duplicate received during verification leaves the row pending so the
        newer claim is fetched again rather than being hidden by stale work.
        """
        if status not in TERMINAL_INBOUND_STATUSES:
            raise ValueError("Invalid terminal inbound Webmention status.")
        if type(received_count) is not int or received_count < 1:
            raise ValueError("Invalid inbound Webmention receipt count.")
        now = int(self.clock())
        with self._locked():
            self._refresh()
            if key not in self.state["entries"]:
                raise KeyError(key)
            current = self.state["entries"][key]
            if current["status"] != "pending" or current["received_count"] != received_count:
                return None
            prior = copy.deepcopy(self.state)
            state = copy.deepcopy(self.state)
            row = copy.deepcopy(state["entries"][key])
            row.update({"status": status, "updated_at": now, "retry_count": 0, "retry_at": 0})
            state["entries"][key] = _record(row)
            self._save(state, prior)
            return copy.deepcopy(row)

    def retry(self, key, *, received_count, delays):
        """Durably defer one exact pending receipt, or exhaust its retry budget."""
        if (
            type(received_count) is not int
            or received_count < 1
            or not isinstance(delays, tuple)
            or not delays
            or any(type(delay) is not int or delay <= 0 for delay in delays)
        ):
            raise ValueError("Invalid inbound Webmention retry request.")
        now = int(self.clock())
        with self._locked():
            self._refresh()
            if key not in self.state["entries"]:
                raise KeyError(key)
            current = self.state["entries"][key]
            if current["status"] != "pending" or current["received_count"] != received_count:
                return None
            prior = copy.deepcopy(self.state)
            state = copy.deepcopy(self.state)
            row = copy.deepcopy(state["entries"][key])
            attempt = row["retry_count"] + 1
            if attempt > len(delays):
                row.update({"status": "failed", "updated_at": now, "retry_count": 0, "retry_at": 0})
            else:
                row.update({"retry_count": attempt, "retry_at": now + delays[attempt - 1], "updated_at": now})
            state["entries"][key] = _record(row)
            self._save(state, prior)
            return copy.deepcopy(row)

    def due(self):
        """Return pending work whose durable retry delay has elapsed."""
        now = int(self.clock())
        return sorted(
            (row for row in self.entries("pending") if row["retry_at"] <= now),
            key=lambda row: (row["retry_at"], row["first_received_at"], row["key"]),
        )

    def entries(self, status=None):
        if status is not None and status not in INBOUND_STATUSES:
            raise ValueError("Invalid inbound Webmention status.")
        with self._locked():
            self._refresh()
            rows = self.state["entries"].values()
            if status is not None:
                rows = (row for row in rows if row["status"] == status)
            return sorted(
                (copy.deepcopy(row) for row in rows),
                key=lambda row: (row["first_received_at"], row["key"]),
            )


class _FileLock:
    def __init__(self, path, thread_lock, timeout):
        self.path = Path(path)
        self.thread_lock = thread_lock
        self.timeout = float(timeout)
        self.handle = None

    def __enter__(self):
        if not self.thread_lock.acquire(timeout=self.timeout):
            raise capacity_error("lock")
        try:
            descriptor = open_shared_lock(self.path)
            self.handle = os.fdopen(descriptor, "a+")
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise capacity_error("lock")
                    time.sleep(min(0.01, self.timeout))
        except Exception as error:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            self.thread_lock.release()
            if isinstance(error, (InboundContractError, InboundStoreError)):
                raise
            if isinstance(error, OSError):
                raise capacity_error("storage") from error
            raise

    def __exit__(self, *_):
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
        finally:
            self.handle = None
            self.thread_lock.release()
