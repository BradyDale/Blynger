"""Inactive background runner for durable exact-commit registry refresh work."""

import json
import re
import subprocess
import threading
from pathlib import Path

from .inbound_registry import ARTIFACT_LIMIT, validate_registry_artifact


REMOTE_COMMAND = "/home/private/blynger-webmentions/bin/install-target-registry"
SSH_TIMEOUT = 20


class SSHRegistryInstaller:
    """Send one artifact to one fixed owner-controlled remote helper."""

    def __init__(self, *, hostname, username, ssh_key="", runner=subprocess.run):
        if not isinstance(hostname,str) or not re.fullmatch(r"[A-Za-z0-9.-]+",hostname) or hostname.startswith("-"):
            raise ValueError("Invalid registry refresh hostname.")
        if not isinstance(username,str) or not re.fullmatch(r"[A-Za-z0-9._-]+",username) or username.startswith("-"):
            raise ValueError("Invalid registry refresh username.")
        self.hostname,self.username,self.ssh_key,self.runner=(
            hostname,
            username,
            str(Path(ssh_key).expanduser()) if ssh_key else "",
            runner,
        )

    def command(self):
        args=["ssh","-o","BatchMode=yes","-o","PasswordAuthentication=no",
              "-o","KbdInteractiveAuthentication=no","-o","IdentitiesOnly=yes",
              "-o","ConnectTimeout=10","-o","StrictHostKeyChecking=yes"]
        if self.ssh_key:args.extend(("-i",self.ssh_key))
        args.extend((self.username+"@"+self.hostname,REMOTE_COMMAND))
        return args

    def install(self,artifact):
        artifact=validate_registry_artifact(artifact)
        payload=(json.dumps(artifact,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
        if len(payload)>ARTIFACT_LIMIT:raise ValueError("Inbound target registry artifact is too large.")
        try:
            result=self.runner(self.command(),input=payload,capture_output=True,timeout=SSH_TIMEOUT)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise ValueError("Registry refresh connection failed.") from error
        if result.returncode or len(result.stdout)>4096:
            raise ValueError("Registry refresh was not confirmed.")
        try:receipt=json.loads(result.stdout)
        except (UnicodeError,ValueError,json.JSONDecodeError) as error:
            raise ValueError("Registry refresh returned an invalid confirmation.") from error
        return receipt


class RegistryRefreshWorker:
    """Single-flight runner; durable work remains in Studio across failures."""

    def __init__(self,studio,installer):
        self.studio,self.installer=studio,installer
        self.guard=threading.Lock();self.thread=None;self.last_error=None

    def run(self):
        if not self.guard.acquire(blocking=False):return False
        try:
            self.studio.reconcile_inbound_registry(self.installer)
            self.last_error=None
            return True
        except BaseException as error:
            self.last_error=str(error) or error.__class__.__name__
            return False
        finally:self.guard.release()

    def wake(self):
        if self.thread is not None and self.thread.is_alive():return False
        self.thread=threading.Thread(target=self.run,name="Blynger registry refresh",daemon=True)
        self.thread.start();return True

    def join(self,timeout=None):
        if self.thread is not None:self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()


class DisabledRegistryRefreshWorker:
    """No-network placeholder when inbound receiving is not configured."""

    def __init__(self, error=None):
        self.last_error = error

    def run(self):
        return False

    def wake(self):
        return False

    def join(self, timeout=None):
        return True


def open_registry_refresh_worker(studio, config):
    """Construct the owner-side refresher without making app startup fragile."""

    publishing = config.get("publishing", {})
    try:
        installer = SSHRegistryInstaller(
            hostname=publishing.get("hostname", ""),
            username=publishing.get("ssh_user", ""),
            ssh_key=publishing.get("ssh_key", ""),
        )
        return RegistryRefreshWorker(studio, installer)
    except (OSError, ValueError) as error:
        return DisabledRegistryRefreshWorker(str(error) or error.__class__.__name__)
