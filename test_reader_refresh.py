"""Exercise Reader refresh through HTTP while feeds are deliberately stalled."""

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from app import Handler
from reader import Reader
from reader_refresh import ReaderRefreshJob
from test_reader import IID, ORIGIN, Net, doc


class ReaderRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = Net()
        self.net.add()
        self.reader = Reader(Path(self.tmp.name), self.net)
        self.reader.subscribe(ORIGIN)
        self.key = self.reader.key(ORIGIN, IID)
        self.entered = threading.Event()
        self.release = threading.Event()

        def slow_fetch(*args, **kwargs):
            self.entered.set()
            if not self.release.wait(10):
                raise ValueError('Test feed was not released')
            return self.net(*args, **kwargs)

        self.net.add(items=[doc(version=2, text='Updated remote words')])
        self.reader.fetch = slow_fetch
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.token = 'test-token'
        self.server.studio = SimpleNamespace(reader=self.reader)
        self.server.reader_lock = threading.RLock()
        self.server.reader_refresh = ReaderRefreshJob(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.release.set()
        self.wait_finished()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, data=None):
        request = urllib.request.Request(
            f'http://127.0.0.1:{self.server.server_port}/api/{path}',
            data=json.dumps(data).encode() if data is not None else None,
            headers={'X-Blynger-Token': 'test-token'},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.load(response)

    def wait_finished(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.server.reader_refresh.status()
            if job['state'] != 'running':
                return job
            time.sleep(.01)
        self.fail('Reader refresh never finished')

    def test_slow_refresh_keeps_cached_reader_and_markers_available(self):
        started = self.request('reader-sync', {})
        self.assertEqual(started['state'], 'running')
        self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.request('reader-sync', {})['id'], started['id'])
        self.assertEqual(self.request('reader-sync-status')['state'], 'running')
        self.assertEqual(len(self.request('reader')['items']), 1)
        self.request('reader-mark', {'key': self.key, 'field': 'saved', 'value': True})
        self.request('reader-react', {'key': self.key, 'reaction': '💭'})
        self.release.set()
        self.assertEqual(self.wait_finished()['state'], 'succeeded')
        item = self.reader.state['items'][self.key]
        self.assertEqual(item['doc']['version'], 2)
        self.assertTrue(item['saved'])
        self.assertIn('💭', item['reactions'])
        self.assertTrue(self.reader.state['interactions'])
        persisted = json.loads(self.reader.file.read_text())
        self.assertEqual(persisted, self.reader.state)

    def test_unsubscribe_during_refresh_cannot_resurrect_removed_items(self):
        self.request('reader-sync', {})
        self.assertTrue(self.entered.wait(2))
        sid = self.reader.state['items'][self.key]['subscription']
        self.request('reader-unsubscribe', {'subscription': sid})
        self.release.set()
        self.assertEqual(self.wait_finished()['state'], 'failed')
        self.assertNotIn(self.key, self.reader.state['items'])
        self.assertFalse(self.reader.state['subscriptions'][sid]['active'])

    def test_failed_refresh_preserves_existing_cache_and_can_retry(self):
        result = self.request('reader-sync', {'subscription': 'missing'})
        self.assertEqual(result['state'], 'running')
        self.assertEqual(self.wait_finished()['state'], 'failed')
        self.assertEqual(self.reader.state['items'][self.key]['doc']['version'], 1)
        self.release.set()
        self.request('reader-sync', {})
        self.assertEqual(self.wait_finished()['state'], 'succeeded')
