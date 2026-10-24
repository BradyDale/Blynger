"""Owner-only control path for the remote inbound Webmention policy."""

import copy
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .inbound_contract import ReceiverPolicy
from .inbound_endpoint import load_configuration


REMOTE_COMMAND = "/home/private/blynger-webmentions/bin/manage-receiver-policy"
SSH_TIMEOUT = 20
CONFIG_LIMIT = 64 * 1024


def validate_policy_snapshot(value):
    if not isinstance(value, dict) or set(value) != {"mode", "domains"}:
        raise ValueError("Invalid receiver policy response.")
    if not isinstance(value["domains"], list) or len(value["domains"]) > 1000:
        raise ValueError("Invalid receiver policy response.")
    policy = ReceiverPolicy(value["mode"], tuple(value["domains"]))
    return {"mode": policy.mode, "domains": list(policy.domains)}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate receiver policy field.")
        result[key] = value
    return result


def _write_configuration(path, value):
    path = Path(path)
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_mode & 0o027:
        raise ValueError("Unsafe receiver policy file.")
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > CONFIG_LIMIT:
        raise ValueError("Receiver policy configuration is too large.")
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(details.st_mode))
        os.chown(temporary, details.st_uid, details.st_gid)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_receiver_policy(path, request):
    """Validate one bounded owner request and atomically update one fixed file."""

    path = Path(path)
    if not isinstance(request, dict) or request.get("schema") != 1:
        raise ValueError("Invalid receiver policy request.")
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    loaded = load_configuration(path)
    current = {"mode": loaded["policy"].mode, "domains": list(loaded["policy"].domains)}
    action = request.get("action")
    if action == "status" and set(request) == {"schema", "action"}:
        return current
    if action == "set" and set(request) == {"schema", "action", "mode", "domains"}:
        incoming = validate_policy_snapshot({"mode": request["mode"], "domains": request["domains"]})
    elif action == "block" and set(request) == {"schema", "action", "domain"}:
        if current["mode"] != "denylist":
            raise ValueError("Blocking requires denylist mode.")
        incoming = validate_policy_snapshot(
            {"mode": "denylist", "domains": current["domains"] + [request["domain"]]}
        )
    else:
        raise ValueError("Invalid receiver policy request.")
    updated = copy.deepcopy(raw)
    updated["policy"] = incoming
    _write_configuration(path, updated)
    # Re-open through the receiver's own validator before confirming success.
    verified = load_configuration(path)["policy"]
    return {"mode": verified.mode, "domains": list(verified.domains)}


class SSHInboundPolicyManager:
    """Send bounded JSON to one fixed owner-controlled remote helper."""

    def __init__(self, *, hostname, username, ssh_key="", runner=subprocess.run):
        if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", hostname) or hostname.startswith("-"):
            raise ValueError("Invalid inbound policy hostname.")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", username) or username.startswith("-"):
            raise ValueError("Invalid inbound policy username.")
        self.hostname = hostname
        self.username = username
        self.ssh_key = str(Path(ssh_key).expanduser()) if ssh_key else ""
        self.runner = runner

    def command(self):
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no", "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes",
        ]
        if self.ssh_key:
            command.extend(("-i", self.ssh_key))
        command.extend((self.username + "@" + self.hostname, REMOTE_COMMAND))
        return command

    def _request(self, value):
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(payload) > CONFIG_LIMIT:
            raise ValueError("Receiver policy request is too large.")
        try:
            result = self.runner(self.command(), input=payload, capture_output=True, timeout=SSH_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("Receiver policy connection failed.") from error
        if result.returncode or len(result.stdout) > CONFIG_LIMIT:
            raise ValueError("Receiver policy update was not confirmed.")
        try:
            return validate_policy_snapshot(json.loads(result.stdout))
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Receiver policy returned an invalid confirmation.") from error

    def status(self):
        return self._request({"schema": 1, "action": "status"})

    def set_policy(self, mode, domains):
        policy = validate_policy_snapshot({"mode": mode, "domains": domains})
        return self._request({"schema": 1, "action": "set", **policy})

    def block(self, source):
        parsed = urlsplit(source)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Choose a verified public source to block.")
        domain = ReceiverPolicy("denylist", (parsed.hostname,)).domains[0]
        return self._request({"schema": 1, "action": "block", "domain": domain})


class DisabledInboundPolicyManager:
    def __init__(self, error="not configured"):
        self.error = error

    def status(self):
        return {"available": False, "error": self.error, "mode": "off", "domains": []}

    def set_policy(self, mode, domains):
        raise ValueError("Inbound Webmention policy is unavailable.")

    def block(self, source):
        raise ValueError("Inbound Webmention policy is unavailable.")


def open_inbound_policy_manager(config):
    publishing = config.get("publishing", {})
    try:
        return SSHInboundPolicyManager(
            hostname=publishing.get("hostname", ""),
            username=publishing.get("ssh_user", ""),
            ssh_key=publishing.get("ssh_key", ""),
        )
    except (OSError, ValueError) as error:
        return DisabledInboundPolicyManager(str(error) or error.__class__.__name__)
