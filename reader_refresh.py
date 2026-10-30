"""Background Reader refresh with isolated downloads and conflict-safe adoption."""

import copy
import os
import secrets
import shutil
import tempfile
import threading
from pathlib import Path

from core import atomic


_MISSING = object()


def merge_refresh(before, downloaded, current):
    """Keep concurrent local edits; reject incompatible edits to the same value."""
    if downloaded == before:
        return current
    if current == before or current == downloaded:
        return downloaded
    if all(isinstance(value, dict) for value in (before, downloaded, current)):
        result = {}
        for key in before.keys() | downloaded.keys() | current.keys():
            value = merge_refresh(
                before.get(key, _MISSING),
                downloaded.get(key, _MISSING),
                current.get(key, _MISSING),
            )
            if value is not _MISSING:
                result[key] = value
        return result
    raise ValueError('Reader changed during refresh. Your changes are safe; refresh again to download the latest items.')


def copy_asset(source, destination):
    # Cached media is immutable and content-addressed. Atomic writes replace
    # directory entries, so staging can share existing bytes safely.
    try:
        os.link(source, destination)
    except FileNotFoundError:
        # Live cleanup may remove an unneeded asset after the state snapshot.
        # The working Reader will download it again if it still needs it.
        return
    except OSError:
        try:
            shutil.copy2(source, destination)
        except FileNotFoundError:
            return


class ReaderRefreshJob:
    def __init__(self, server):
        self.server = server
        self.guard = threading.Lock()
        self.job = {'state': 'idle'}

    def status(self):
        with self.guard:
            return copy.deepcopy(self.job)

    def start(self, subscription=None):
        with self.guard:
            if self.job['state'] == 'running':
                return copy.deepcopy(self.job)
            self.job = {'id': secrets.token_urlsafe(12), 'state': 'running',
                        'message': 'Checking subscriptions…'}
            result = copy.deepcopy(self.job)
            threading.Thread(target=self._run, args=(subscription,),
                             daemon=True, name='Blynger Reader refresh').start()
            return result

    def _run(self, subscription):
        reader = self.server.studio.reader
        try:
            with tempfile.TemporaryDirectory(prefix='blynger-reader-refresh-') as folder:
                working = copy.copy(reader)
                working.root = Path(folder)
                working.assets = working.root / 'assets'
                working.file = working.root / 'reader.json'
                working.backup = working.root / 'reader.backup.json'
                working._state_lock = threading.RLock()
                working._sync_lock = threading.Lock()
                with self.server.reader_lock, reader._state_lock:
                    before = copy.deepcopy(reader.state)
                    working.state = copy.deepcopy(before)
                # Cloud-backed cached files can also take time to materialize.
                # Copying them must not hold up local Reader access either.
                shutil.copytree(reader.assets, working.assets, copy_function=copy_asset)

                # No live Reader or Studio lock is held during network I/O.
                result = working.sync(subscription)

                with self.server.reader_lock, reader._state_lock:
                    merged = merge_refresh(before, working.state, reader.state)
                    referenced = {name for item in merged['items'].values()
                                  for name in item.get('assets', {}).values()}
                    for name in referenced:
                        source = working.asset_path(name)
                        destination = reader.asset_path(name)
                        if not destination.exists() and source.is_file():
                            atomic(destination, source.read_bytes())
                    reader.state = merged
                    reader.save()
                outcome = {'state': 'succeeded', 'message': result['message']}
        except Exception as exc:
            outcome = {'state': 'failed', 'message': str(exc)}
        with self.guard:
            self.job.update(outcome)
