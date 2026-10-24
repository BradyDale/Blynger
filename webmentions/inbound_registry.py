"""Exact-commit artifacts and atomic storage for an inbound target registry."""

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .inbound_targets import build_target_registry, validate_target_registry


COMMIT = re.compile(r"[0-9a-f]{40,64}")
ARTIFACT_LIMIT = 8 * 1024 * 1024


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def build_registry_artifact(commit, previous_commit, origin, manifest, documents):
    """Build a registry identified by the exact hosted Git commit it describes."""
    registry = build_target_registry(origin, manifest, documents)
    value = {
        "schema": 1,
        "commit": commit,
        "previous_commit": previous_commit,
        "registry_sha256": "sha256:" + hashlib.sha256(_canonical(registry)).hexdigest(),
        "registry": registry,
    }
    return validate_registry_artifact(value)


def validate_registry_artifact(value):
    fields = {"schema", "commit", "previous_commit", "registry_sha256", "registry"}
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != 1:
        raise ValueError("Invalid inbound target registry artifact.")
    commit = value["commit"]
    previous = value["previous_commit"]
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("Invalid inbound target registry commit.")
    if not isinstance(previous, str) or not COMMIT.fullmatch(previous) or previous == commit:
        raise ValueError("Invalid inbound target registry predecessor.")
    registry = validate_target_registry(value["registry"])
    digest = "sha256:" + hashlib.sha256(_canonical(registry)).hexdigest()
    if value["registry_sha256"] != digest:
        raise ValueError("Inbound target registry digest does not match.")
    result = {
        "schema": 1,
        "commit": commit,
        "previous_commit": previous,
        "registry_sha256": digest,
        "registry": registry,
    }
    if len(_canonical(result)) > ARTIFACT_LIMIT:
        raise ValueError("Inbound target registry artifact is too large.")
    return copy.deepcopy(result)


def installation_action(current, incoming, is_ancestor):
    """Return install/already/superseded while refusing unrelated histories."""
    incoming = validate_registry_artifact(incoming)
    if current is None:
        return "install"
    current = validate_registry_artifact(current)
    if current["commit"] == incoming["commit"]:
        if current != incoming:
            raise ValueError("The installed registry conflicts with the same commit.")
        return "already"
    if is_ancestor(current["commit"], incoming["commit"]):
        return "install"
    if is_ancestor(incoming["commit"], current["commit"]):
        return "superseded"
    raise ValueError("The inbound target registry commits are unrelated.")


def _atomic(path, data, mode=0o640):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
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


def _regular(path, mode):
    details = Path(path).lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_mode & (0o777 ^ mode)
    ):
        raise ValueError("Unsafe inbound target registry file.")
    return details


def _directory_mode(mode):
    """Keep a host-administered setgid inheritance boundary when present."""
    return 0o2750 if mode & stat.S_ISGID else 0o750


class RegistryArtifactStore:
    """Host-side atomic last-good store; safe to call repeatedly after uncertainty."""

    def __init__(self, root):
        self.root = Path(root)
        if self.root.exists() and self.root.is_symlink():
            raise ValueError("Unsafe inbound target registry directory.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        # A deployed shared-group directory uses setgid so each atomic
        # replacement remains readable by the web process.  Preserve that
        # owner-configured inheritance bit instead of silently stripping it.
        os.chmod(self.root, _directory_mode(self.root.stat().st_mode))
        self.current = self.root / "targets.json"
        self.backup = self.root / "targets.backup.json"
        self.lock = self.root / "targets.lock"

    def _read(self, path):
        details = _regular(path, 0o640)
        if details.st_size > ARTIFACT_LIMIT:
            raise ValueError("Inbound target registry artifact is too large.")
        return validate_registry_artifact(json.loads(path.read_text(encoding="utf-8")))

    def installed(self):
        return self._read(self.current) if self.current.exists() else None

    def install(self, incoming, is_ancestor, checkpoint=None):
        incoming = validate_registry_artifact(incoming)
        descriptor = os.open(
            self.lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "r+") as lock:
            details = os.fstat(lock.fileno())
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or details.st_mode & 0o777 != 0o600
            ):
                raise ValueError("Unsafe inbound target registry lock.")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self.installed()
            action = installation_action(current, incoming, is_ancestor)
            if checkpoint is not None:
                checkpoint("before_registry_install", action)
            if action == "install":
                payload = _canonical(incoming) + b"\n"
                if current is not None:
                    _atomic(self.backup, _canonical(current) + b"\n")
                _atomic(self.current, payload)
                if checkpoint is not None:
                    checkpoint("after_registry_install", action)
            confirmed = self.installed()
            expected = incoming if action != "superseded" else current
            if confirmed != expected:
                raise ValueError("Inbound target registry installation was not confirmed.")
            return {
                "status": action,
                "commit": confirmed["commit"],
                "registry_sha256": confirmed["registry_sha256"],
            }
