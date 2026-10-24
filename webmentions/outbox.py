"""Durable private storage for planned outbound Webmentions."""

import copy
import fcntl
import json
import os
import re
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .shared import (
    RECORD_FIELDS,
    STATUSES,
    TERMINAL_STATUSES,
    _absolute_url,
    _candidate,
    _record,
)


_UNSET = object()
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
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


def _shared_lock(path):
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class _FileLock:
    """Serialize one local outbox across Blynger processes."""

    def __init__(self, path, thread_lock):
        self.path = Path(path)
        self.thread_lock = thread_lock
        self.stream = None

    def __enter__(self):
        self.thread_lock.acquire()
        try:
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or details.st_mode & 0o777 != 0o600
            ):
                os.close(descriptor)
                raise ValueError("Unsafe Webmention outbox lock.")
            self.stream = os.fdopen(descriptor, "r+")
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX)
            return self
        except Exception:
            self.thread_lock.release()
            raise

    def __exit__(self, *_):
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
        finally:
            self.stream = None
            self.thread_lock.release()


class OutboundQueue:
    """Inactive, durable storage for planned outgoing Webmentions."""

    def __init__(self, root, clock=_now):
        self.root = Path(root)
        self.file = self.root / "webmentions-outbox.json"
        self.backup = self.root / "webmentions-outbox.backup.json"
        self.lock_file = self.root / "webmentions-outbox.lock"
        self.clock = clock
        self.root.mkdir(parents=True, exist_ok=True)
        self.thread_lock = _shared_lock(self.lock_file)
        self.recovery_notice = ""
        self.damaged_file = None
        self.read_only = False
        self.state = {"schema": 2, "paused": False, "entries": {}}
        with self._locked():
            self._open()

    def _locked(self):
        return _FileLock(self.lock_file, self.thread_lock)

    def _load(self, path):
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") not in (1, 2):
            raise ValueError("Invalid Webmention outbox document.")
        if data["schema"] == 1:
            if set(data) != {"schema", "entries"}:
                raise ValueError("Invalid Webmention outbox document.")
            paused = False
        else:
            if set(data) != {"schema", "paused", "entries"} or not isinstance(data["paused"], bool):
                raise ValueError("Invalid Webmention outbox document.")
            paused = data["paused"]
        if not isinstance(data["entries"], dict):
            raise ValueError("Invalid Webmention outbox entries.")
        entries = {}
        for key, value in data["entries"].items():
            record = _record(value)
            if key != record["key"]:
                raise ValueError("Webmention outbox key does not match its record.")
            entries[key] = record
        return {"schema": 2, "paused": paused, "entries": entries}

    def _preserve(self, path):
        if not path.exists():
            return None
        stamp = re.sub(r"[^0-9]", "", str(self.clock())) or "unknown"
        candidate = self.root / f"webmentions-outbox.damaged-{stamp}.json"
        suffix = 1
        while candidate.exists():
            candidate = self.root / f"webmentions-outbox.damaged-{stamp}-{suffix}.json"
            suffix += 1
        _atomic(candidate, path.read_text(encoding="utf-8", errors="replace"))
        return candidate

    def _open(self):
        if not self.file.exists():
            if self.backup.exists():
                try:
                    self.state = self._load(self.backup)
                except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                    self.read_only = True
                    self.recovery_notice = (
                        "The Webmention outbox is missing and its backup is not usable. "
                        "The outbox is read-only."
                    )
                    return
                _atomic(self.file, self._render(self.state))
                self.read_only = False
                self.recovery_notice = (
                    "The Webmention outbox recovered after its main file disappeared."
                )
            return
        try:
            self.state = self._load(self.file)
            self.read_only = False
            return
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self.damaged_file = self._preserve(self.file)
        try:
            self.state = self._load(self.backup)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self.read_only = True
            self.recovery_notice = (
                "The Webmention outbox is damaged and no verified backup is available. "
                "The damaged data was preserved and the outbox is read-only."
            )
            return
        _atomic(self.file, self._render(self.state))
        self.read_only = False
        self.recovery_notice = (
            "The Webmention outbox recovered from its last verified backup. "
            "The damaged data was preserved."
        )

    def _refresh(self):
        if not self.file.exists():
            self._open()
            return
        try:
            self.state = self._load(self.file)
            self.read_only = False
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self._open()

    def _render(self, state=None):
        selected = self.state if state is None else state
        return json.dumps(selected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _save(self, state):
        if self.read_only:
            raise ValueError("The damaged Webmention outbox is read-only.")
        if self.file.exists():
            try:
                prior = self._load(self.file)
                _atomic(self.backup, self._render(prior))
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                self.damaged_file = self._preserve(self.file)
                self.recovery_notice = (
                    "Blynger preserved a damaged Webmention outbox before saving verified in-memory state."
                )
        _atomic(self.file, self._render(state))
        # Keep a second complete copy of the state whose successful enqueue may
        # already have allowed publication reconciliation to finish.
        _atomic(self.backup, self._render(state))

    def enqueue(self, candidates):
        with self._locked():
            self._refresh()
            if self.read_only:
                raise ValueError("The damaged Webmention outbox is read-only.")
            validated = [_candidate(candidate) for candidate in candidates]
            added = []
            now = str(self.clock())
            state = copy.deepcopy(self.state)
            for candidate in validated:
                key = candidate["key"]
                if key in state["entries"]:
                    continue
                state["entries"][key] = {
                    **candidate,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "attempts": 0,
                    "endpoint": None,
                    "error": None,
                    "next_attempt_at": None,
                }
                added.append(key)
            if added:
                self._save(state)
                self.state = state
            return added

    def paused(self):
        with self._locked():
            self._refresh()
            return bool(self.state["paused"])

    def set_paused(self, value):
        if not isinstance(value, bool):
            raise ValueError("Webmention pause state must be true or false.")
        with self._locked():
            self._refresh()
            if self.read_only:
                raise ValueError("The damaged Webmention outbox is read-only.")
            if self.state["paused"] == value:
                return value
            state = copy.deepcopy(self.state)
            state["paused"] = value
            self._save(state)
            self.state = state
            return value

    def update(
        self,
        key,
        status,
        *,
        endpoint=_UNSET,
        error=_UNSET,
        next_attempt_at=_UNSET,
    ):
        with self._locked():
            self._refresh()
            if self.read_only:
                raise ValueError("The damaged Webmention outbox is read-only.")
            if status not in STATUSES:
                raise ValueError("Unknown Webmention outbox status.")
            if key not in self.state["entries"]:
                raise KeyError(key)
            current = self.state["entries"][key]
            if current["status"] in TERMINAL_STATUSES and current["status"] != status:
                raise ValueError("A terminal Webmention outbox record cannot change status.")
            if endpoint is not _UNSET and endpoint is not None:
                _absolute_url(endpoint, keep_fragment=False)
            for name, value in (("error", error), ("next_attempt_at", next_attempt_at)):
                if value is not _UNSET and value is not None and not isinstance(value, str):
                    raise ValueError(f"Invalid Webmention outbox {name}.")
            updated = copy.deepcopy(current)
            updated.update({"status": status, "updated_at": str(self.clock())})
            for name, value in (
                ("endpoint", endpoint),
                ("error", error),
                ("next_attempt_at", next_attempt_at),
            ):
                if value is not _UNSET:
                    updated[name] = value
            if status == "retrying":
                updated["attempts"] += 1
            state = copy.deepcopy(self.state)
            state["entries"][key] = _record(updated)
            self._save(state)
            self.state = state
            return copy.deepcopy(updated)

    def entries(self, status=None):
        with self._locked():
            self._refresh()
            if status is not None and status not in STATUSES:
                raise ValueError("Unknown Webmention outbox status.")
            rows = self.state["entries"].values()
            if status is not None:
                rows = (row for row in rows if row["status"] == status)
            return sorted((copy.deepcopy(row) for row in rows), key=lambda row: (row["created_at"], row["key"]))
