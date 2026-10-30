"""Inactive one-way SSH synchronization for finalized inbound Webmentions."""

import copy
import fcntl
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .inbound_verifier import EXPORT_LIMIT, validate_verification_export, validate_verification_record
from .inbound_activity import ACTIVITY_KINDS, classify_activity, semantic_fingerprint


REMOTE_EXPORT = "/home/protected/webmentions/verified/export.json"
REMOTE_COMMAND = "cat " + REMOTE_EXPORT
ARCHIVE_LIMIT = 64 * 1024 * 1024
ARCHIVE_RECORDS = 10_000
SSH_TIMEOUT = 20
SYNC_INTERVAL = 10 * 60
STARTUP_DELAY = 5
SYNC_ERRORS = {
    "unavailable",
    "timeout",
    "oversized",
    "invalid_export",
    "conflict",
    "local_store",
}
_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class InboundSyncError(RuntimeError):
    def __init__(self, code):
        if code not in SYNC_ERRORS:
            raise ValueError("Invalid inbound synchronization error.")
        super().__init__(code)
        self.code = code


def _thread_lock(path):
    key = str(Path(path).resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


class _ArchiveLock:
    def __init__(self, path, thread_lock):
        self.path = Path(path)
        self.thread_lock = thread_lock
        self.stream = None

    def __enter__(self):
        self.thread_lock.acquire()
        try:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags, 0o600)
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_mode & 0o177:
                os.close(descriptor)
                raise InboundSyncError("local_store")
            self.stream = os.fdopen(descriptor, "r+")
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX)
            return self
        except Exception as error:
            self.thread_lock.release()
            if isinstance(error, InboundSyncError):
                raise
            raise InboundSyncError("local_store") from error

    def __exit__(self, *_):
        try:
            if self.stream is not None:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
                self.stream.close()
                self.stream = None
        finally:
            self.thread_lock.release()


def _atomic(path, data):
    path = Path(path)
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


def _private_regular(path):
    details = Path(path).lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_mode & 0o177:
        raise ValueError("Unsafe inbound mention archive file.")
    return details


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _loads(payload):
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise InboundSyncError("invalid_export") from error


def _run_ssh(args, limit=EXPORT_LIMIT, timeout=SSH_TIMEOUT):
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise InboundSyncError("unavailable") from error
    selector = selectors.DefaultSelector()
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InboundSyncError("timeout")
            events = selector.select(remaining)
            if not events:
                raise InboundSyncError("timeout")
            chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > limit:
                raise InboundSyncError("oversized")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InboundSyncError("timeout")
        if process.wait(timeout=remaining) != 0:
            raise InboundSyncError("unavailable")
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        raise InboundSyncError("timeout") from error
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if process.stdout is not None:
            process.stdout.close()


class SSHExportReader:
    """Read one fixed protected file without password or interaction prompts."""

    def __init__(self, *, hostname, username, ssh_key="", runner=_run_ssh):
        if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", hostname) or hostname.startswith("-"):
            raise ValueError("Invalid synchronization hostname.")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", username) or username.startswith("-"):
            raise ValueError("Invalid synchronization username.")
        self.hostname = hostname
        self.username = username
        self.ssh_key = str(Path(ssh_key).expanduser()) if ssh_key else ""
        self.runner = runner

    def command(self):
        args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=yes",
        ]
        if self.ssh_key:
            args.extend(("-i", self.ssh_key))
        args.extend((self.username + "@" + self.hostname, REMOTE_COMMAND))
        return args

    def read(self):
        return self.runner(self.command(), EXPORT_LIMIT, SSH_TIMEOUT)


class InboundMentionArchive:
    """Private last-known-good local archive, independent of Reader and drafts."""

    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.file = self.root / "inbound-mentions.json"
        self.backup = self.root / "inbound-mentions.backup.json"
        self.lock_file = self.root / "inbound-mentions.lock"
        self.clock = clock
        self.recovery_notice = ""
        self.damaged_file = None
        if self.root.exists() and self.root.is_symlink():
            raise ValueError("Unsafe inbound mention archive directory.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.thread_lock = _thread_lock(self.lock_file)
        with self._locked():
            self.state = self._open()

    def _locked(self):
        return _ArchiveLock(self.lock_file, self.thread_lock)

    def _refresh(self):
        self.state = self._open()

    def _empty(self):
        return {
            "schema": 3,
            "records": {},
            "activities": {},
            "acknowledged": {},
            "last_attempt_at": None,
            "last_success_at": None,
            "remote_generated_at": None,
            "last_error": None,
        }

    def _validate(self, value):
        legacy = {"schema", "records", "last_attempt_at", "last_success_at", "remote_generated_at", "last_error"}
        schema_two = legacy | {"activities"}
        fields = schema_two | {"acknowledged"}
        if not isinstance(value, dict):
            raise ValueError("Invalid inbound mention archive.")
        if value.get("schema") == 1 and set(value) == legacy:
            value = {**value, "schema": 2, "activities": {}}
        if value.get("schema") == 2 and set(value) == schema_two:
            acknowledged = {
                key: row["fingerprint"]
                for key, row in value["activities"].items()
                if isinstance(row, dict) and row.get("unread") is False and isinstance(row.get("fingerprint"), str)
            }
            activities = {
                key: {name: item for name, item in row.items() if name != "unread"}
                for key, row in value["activities"].items()
                if isinstance(row, dict)
            }
            value = {**value, "schema": 3, "activities": activities, "acknowledged": acknowledged}
        if (
            set(value) != fields
            or value.get("schema") != 3
            or not isinstance(value["records"], dict)
            or not isinstance(value["activities"], dict)
            or not isinstance(value["acknowledged"], dict)
        ):
            raise ValueError("Invalid inbound mention archive.")
        if len(value["records"]) > ARCHIVE_RECORDS:
            raise ValueError("Inbound mention archive has too many records.")
        records = {}
        for key, row in value["records"].items():
            verified = validate_verification_record(row)
            if key != verified["key"] or verified["phase"] != "final":
                raise ValueError("Invalid inbound mention archive record.")
            records[key] = verified
        activities = {}
        for key, row in value["activities"].items():
            if (
                key not in records
                or not isinstance(row, dict)
                or set(row) != {"fingerprint", "kind", "at"}
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("fingerprint", "")))
                or row.get("kind") not in ACTIVITY_KINDS
                or type(row.get("at")) is not int
                or row["at"] < 0
            ):
                raise ValueError("Invalid inbound mention activity.")
            activities[key] = copy.deepcopy(row)
        acknowledged = {}
        for key, fingerprint in value["acknowledged"].items():
            if key not in activities or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(fingerprint)):
                raise ValueError("Invalid inbound mention read ledger.")
            acknowledged[key] = fingerprint
        for name in ("last_attempt_at", "last_success_at", "remote_generated_at"):
            if value[name] is not None and (type(value[name]) is not int or value[name] < 0):
                raise ValueError("Invalid inbound mention archive timestamp.")
        if value["last_error"] is not None and value["last_error"] not in SYNC_ERRORS:
            raise ValueError("Invalid inbound mention archive diagnostic.")
        result = {**value, "records": records, "activities": activities, "acknowledged": acknowledged}
        self._render(result)
        return copy.deepcopy(result)

    def _render(self, value):
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(data) > ARCHIVE_LIMIT:
            raise ValueError("Inbound mention archive exceeds its size limit.")
        return data

    def _read(self, path):
        details = _private_regular(path)
        if details.st_size > ARCHIVE_LIMIT:
            raise ValueError("Inbound mention archive exceeds its size limit.")
        return self._validate(_loads(path.read_bytes()))

    def _preserve(self):
        if not self.file.exists() or self.file.is_symlink():
            return None
        details = _private_regular(self.file)
        if details.st_size > ARCHIVE_LIMIT:
            return None
        payload = self.file.read_bytes()
        fingerprint = hashlib.sha256(payload).hexdigest()[:16]
        path = self.root / ("inbound-mentions.damaged-" + fingerprint + ".json")
        if not path.exists():
            _atomic(path, payload)
        self.damaged_file = path
        return path

    def _open(self):
        if self.file.is_symlink() or self.backup.is_symlink():
            raise InboundSyncError("local_store")
        if not self.file.exists():
            if self.backup.exists():
                try:
                    state = self._read(self.backup)
                except (OSError, ValueError, InboundSyncError, RecursionError) as error:
                    raise InboundSyncError("local_store") from error
                _atomic(self.file, self._render(state))
                self.recovery_notice = "Inbound mention archive recovered after its main file disappeared."
                return state
            return self._empty()
        try:
            return self._read(self.file)
        except (OSError, ValueError, InboundSyncError, RecursionError):
            try:
                self._preserve()
            except (OSError, ValueError, InboundSyncError) as error:
                raise InboundSyncError("local_store") from error
        try:
            state = self._read(self.backup)
        except (OSError, ValueError, InboundSyncError, RecursionError) as error:
            raise InboundSyncError("local_store") from error
        _atomic(self.file, self._render(state))
        self.recovery_notice = "Inbound mention archive recovered from its last good backup."
        return state

    def _save(self, state):
        state = self._validate(state)
        data = self._render(state)
        _atomic(self.file, data)
        _atomic(self.backup, data)
        self.state = state
        return copy.deepcopy(state)

    def failure(self, code):
        if code not in SYNC_ERRORS:
            code = "local_store"
        with self._locked():
            self._refresh()
            state = copy.deepcopy(self.state)
            state["last_attempt_at"] = int(self.clock())
            state["last_error"] = code
            return self._save(state)

    def merge(self, export):
        export = validate_verification_export(export)
        with self._locked():
            self._refresh()
            state = copy.deepcopy(self.state)
            records = state["records"]
            prior_revision = state["remote_generated_at"]
            if prior_revision is not None and export["generated_at"] < prior_revision:
                raise InboundSyncError("conflict")
            incoming_records = {row["key"]: row for row in export["records"]}
            if prior_revision is not None and export["generated_at"] == prior_revision:
                if incoming_records != records:
                    raise InboundSyncError("conflict")
            else:
                # A newer export is an authoritative snapshot.  Intake owns
                # retention, so remove records it has deliberately expired,
                # along with their local activity/read state.
                for removed in set(records) - set(incoming_records):
                    records.pop(removed, None)
                    state["activities"].pop(removed, None)
                    state["acknowledged"].pop(removed, None)
            for incoming in export["records"]:
                current = records.get(incoming["key"])
                if current is None or incoming["receipt_count"] > current["receipt_count"]:
                    kind = classify_activity(current, incoming)
                    records[incoming["key"]] = incoming
                    if kind is not None:
                        state["activities"][incoming["key"]] = {
                            "fingerprint": semantic_fingerprint(incoming),
                            "kind": kind,
                            "at": incoming["checked_at"],
                        }
                elif incoming["receipt_count"] < current["receipt_count"]:
                    raise InboundSyncError("conflict")
                elif incoming != current:
                    raise InboundSyncError("conflict")
            if len(records) > ARCHIVE_RECORDS:
                raise InboundSyncError("local_store")
            now = int(self.clock())
            state.update(
                {
                    "last_attempt_at": now,
                    "last_success_at": now,
                    "remote_generated_at": export["generated_at"],
                    "last_error": None,
                }
            )
            return self._save(state)

    def records(self):
        with self._locked():
            self._refresh()
            return [copy.deepcopy(self.state["records"][key]) for key in sorted(self.state["records"])]

    def snapshot(self):
        with self._locked():
            self._refresh()
            return copy.deepcopy(self.state)

    def activities(self, unread_only=False):
        with self._locked():
            self._refresh()
            rows=[]
            for key,activity in self.state["activities"].items():
                unread=self.state["acknowledged"].get(key)!=activity["fingerprint"]
                if unread_only and not unread:continue
                rows.append({"key":key,**copy.deepcopy(activity),"unread":unread,"record":copy.deepcopy(self.state["records"][key])})
            return sorted(rows,key=lambda row:(row["at"],row["key"]),reverse=True)

    def mark_read(self, key, fingerprint=None):
        with self._locked():
            self._refresh();state=copy.deepcopy(self.state)
            if key not in state["activities"]:return False
            current=state["activities"][key]["fingerprint"]
            fingerprint=current if fingerprint is None else fingerprint
            if fingerprint != current:return False
            state["acknowledged"][key]=fingerprint
            self._save(state);return True


class InboundSynchronizer:
    def __init__(self, reader, archive):
        self.reader = reader
        self.archive = archive

    def sync(self):
        try:
            payload = self.reader.read()
            if not isinstance(payload, bytes) or len(payload) > EXPORT_LIMIT:
                raise InboundSyncError("oversized")
            export = validate_verification_export(_loads(payload))
        except InboundSyncError as error:
            return self._failure(error.code)
        except Exception:
            return self._failure("invalid_export")
        try:
            state = self.archive.merge(export)
            return {"ok": True, "records": len(state["records"]), "error": None}
        except InboundSyncError as error:
            return self._failure(error.code)
        except Exception:
            return self._failure("local_store")

    def _failure(self, code):
        try:
            state = self.archive.failure(code)
        except Exception:
            return {"ok": False, "records": len(self.archive.state["records"]), "error": "local_store"}
        return {"ok": False, "records": len(state["records"]), "error": code}


def _timestamp(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


class DisabledInboundSyncService:
    """Safe no-network service used until inbound receiving is deployed."""

    def __init__(self, error=None):
        self.error = error

    def start(self):
        return False

    def wake(self):
        return False

    def stop(self):
        return False

    def mark_read(self, key, fingerprint):
        return False

    def status(self):
        return {
            "enabled": False,
            "running": False,
            "syncing": False,
            "last_attempt_at": None,
            "last_success_at": None,
            "remote_generated_at": None,
            "last_error": self.error,
            "record_count": 0,
            "activity_count": 0,
            "unread_count": 0,
            "notice_count": 0,
            "unread_notice_count": 0,
            "activities": [],
            "availability": "unavailable" if self.error else "not_enabled",
        }


class InboundSyncService:
    """Single background pull loop; UI and publication threads never do SSH."""

    def __init__(self, synchronizer, archive, *, interval=SYNC_INTERVAL, startup_delay=STARTUP_DELAY):
        self.synchronizer = synchronizer
        self.archive = archive
        self.interval = interval
        self.startup_delay = startup_delay
        self.guard = threading.Condition(threading.RLock())
        self.thread = None
        self.stopping = False
        self.requested = False
        self.syncing = False
        self.last_result = None

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return False
            self.stopping = False
            self.thread = threading.Thread(target=self._run, daemon=True, name="Blynger incoming Webmentions")
            self.thread.start()
            return True

    def wake(self):
        self.start()
        with self.guard:
            self.requested = True
            self.guard.notify_all()
        return True

    def stop(self):
        with self.guard:
            thread = self.thread
            if not thread:
                return False
            self.stopping = True
            self.guard.notify_all()
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        return True

    def _run(self):
        with self.guard:
            if not self.requested and not self.stopping:
                self.guard.wait(timeout=self.startup_delay)
        while True:
            with self.guard:
                if self.stopping:
                    self.syncing = False
                    return
                self.requested = False
                self.syncing = True
            result = self.synchronizer.sync()
            with self.guard:
                self.last_result = copy.deepcopy(result)
                self.syncing = False
                if self.stopping:
                    return
                if self.requested:
                    continue
                self.guard.wait_for(lambda: self.requested or self.stopping, timeout=self.interval)

    def status(self):
        state = self.archive.snapshot()
        activities = []
        for key, activity in state["activities"].items():
            record = state["records"][key]
            author = record.get("source_author")
            author_name = author.get("name") if isinstance(author, dict) and isinstance(author.get("name"), str) else None
            if author_name is not None:
                author_name = " ".join(author_name.split())[:200] or None
            activities.append({
                "key": key,
                "fingerprint": activity["fingerprint"],
                "kind": activity["kind"],
                "at": _timestamp(activity["at"]),
                "unread": state["acknowledged"].get(key) != activity["fingerprint"],
                "status": record["status"],
                "relation": record["relation"],
                "mention_class": record["mention_class"],
                "source": record["source"],
                "source_page": record["source_page"],
                "source_origin": record["source_origin"],
                "source_author": author_name,
                "target": record["target"],
            })
        activities.sort(key=lambda row: (row["at"], row["key"]), reverse=True)
        responses = [row for row in activities if row["mention_class"] != "notice"]
        notices = [row for row in activities if row["mention_class"] == "notice"]
        with self.guard:
            running = bool(self.thread and self.thread.is_alive() and not self.stopping)
            syncing = self.syncing
        if state["last_success_at"] is None:
            availability = "unavailable" if state["last_error"] else "not_synchronized"
        elif time.time() - state["last_success_at"] > self.interval * 2:
            availability = "stale"
        else:
            availability = "current"
        return {
            "enabled": True,
            "running": running,
            "syncing": syncing,
            "last_attempt_at": _timestamp(state["last_attempt_at"]),
            "last_success_at": _timestamp(state["last_success_at"]),
            "remote_generated_at": _timestamp(state["remote_generated_at"]),
            "last_error": state["last_error"],
            "record_count": len(state["records"]),
            "activity_count": len(responses),
            "unread_count": sum(1 for row in responses if row["unread"]),
            "notice_count": len(notices),
            "unread_notice_count": sum(1 for row in notices if row["unread"]),
            "activities": activities,
            "availability": availability,
        }

    def mark_read(self, key, fingerprint):
        return self.archive.mark_read(key, fingerprint)


def open_inbound_sync_service(data_root, config):
    """Construct local synchronization without activating a public receiver."""
    if not config.get("webmentions", {}).get("inbound_sync_enabled", False):
        return DisabledInboundSyncService()
    publishing = config.get("publishing", {})
    try:
        reader = SSHExportReader(
            hostname=publishing.get("hostname", ""),
            username=publishing.get("ssh_user", ""),
            ssh_key=publishing.get("ssh_key", ""),
        )
        archive = InboundMentionArchive(Path(data_root) / "inbound-webmentions")
        return InboundSyncService(InboundSynchronizer(reader, archive), archive)
    except (InboundSyncError, OSError, ValueError):
        return DisabledInboundSyncService("configuration")
