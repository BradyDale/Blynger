import copy
import http.client
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import ANY, patch

from reader_network import fetch_bounded, post_bounded, public_url
from webmentions import (
    OutboundQueue,
    OutboundService,
    OutboundWorker,
    deliver_webmention,
    discover_endpoint,
    open_outbound_service,
    plan_mentions,
)
from app import Handler


OWN = "https://mine.example/blyg/"
REMOTE = "https://remote.example/notes/"
SOURCE_ID = "0" * 25 + "1"
TARGET_ID = "0" * 25 + "2"
OTHER_ID = "0" * 25 + "3"


def document(version=1, kind="thread", blyg="0.4"):
    return {
        "blyg": blyg,
        "id": SOURCE_ID,
        "kind": kind,
        "origin": OWN,
        "version": version,
        "page": "t/" + SOURCE_ID + "/",
        "transclusions": [],
    }


def reference(iid=TARGET_ID, version=1, origin=REMOTE, url=None):
    row = {"origin": origin, "id": iid, "version": version}
    if url:
        row["cited"] = {"url": url, "retrieved": "2026-10-18T00:00:00Z"}
    return row


def _held_outbox_enqueue(root, event, ready, release):
    queue = OutboundQueue(root)
    save = queue._save

    def held(state):
        ready.set()
        if not release.wait(5):
            raise RuntimeError("Timed out waiting to release the outbox save.")
        return save(state)

    queue._save = held
    queue.enqueue([event])


def _plain_outbox_enqueue(root, event, finished):
    OutboundQueue(root).enqueue([event])
    finished.set()


class Net:
    def __init__(self):
        self.responses = {}
        self.calls = []

    def add(self, url, body=b"", headers=None, *, method="GET", final=None, status=200):
        self.responses[(method, url)] = (final or url, body, headers or {}, status)

    def __call__(self, url, *, method="GET", limit=None):
        self.calls.append((method, url, limit))
        if (method, url) not in self.responses:
            raise ValueError("HTTP 404 from " + url)
        final, body, headers, status = self.responses[(method, url)]
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        if limit is not None and len(body) > limit:
            raise ValueError("Remote response exceeds the test size limit.")
        return final, body, headers, status


class MentionPlanningTests(unittest.TestCase):
    def test_extracts_supported_remote_relations_and_groups_one_target(self):
        current = document()
        shared = reference(url=REMOTE + "t/" + TARGET_ID + "/")
        current["stub_of"] = copy.deepcopy(shared)
        current["transclusions"] = [
            copy.deepcopy(shared),
            copy.deepcopy(shared),
            reference(origin=OWN),
        ]
        current["forked_from"] = reference(OTHER_ID, 4)
        current["generated"] = [{"sources": [reference(OTHER_ID, 5)]}]
        result = plan_mentions(None, current, OWN)
        self.assertEqual(result["issues"], [])
        self.assertEqual(len(result["events"]), 2)
        by_target = {event["target_id"]: event for event in result["events"]}
        self.assertEqual(by_target[TARGET_ID]["relations"], ["stub", "transclusion"])
        self.assertEqual(by_target[TARGET_ID]["target_versions"], {"stub": 1, "transclusion": 1})
        self.assertEqual(by_target[OTHER_ID]["relations"], ["fork", "source"])
        self.assertEqual(by_target[OTHER_ID]["target_versions"], {"fork": 4, "source": 5})
        self.assertTrue(all(event["source"] == OWN + "t/" + SOURCE_ID + "/" for event in result["events"]))

    def test_plain_url_stub_is_eligible_but_ordinary_links_are_not_scanned(self):
        current = document(blyg="0.3")
        current["stub_of"] = {"url": "https://ordinary.example/article#answer"}
        current["content_html"] = '<a href="https://linked.example/">ordinary link</a>'
        result = plan_mentions(None, current, OWN)
        self.assertEqual(len(result["events"]), 1)
        event = result["events"][0]
        self.assertEqual(event["target_url"], "https://ordinary.example/article#answer")
        self.assertEqual(event["relations"], ["stub"])
        self.assertIsNone(event["target_origin"])

    def test_03_generation_sources_are_not_invented(self):
        current = document(blyg="0.3")
        current["generated"] = [{"sources": [reference()]}]
        self.assertEqual(plan_mentions(None, current, OWN), {"events": [], "issues": []})

    def test_unrelated_republication_is_silent_but_target_change_is_new(self):
        previous = document(version=1)
        previous["transclusions"] = [reference(version=2)]
        unrelated = copy.deepcopy(previous)
        unrelated["version"] = 2
        self.assertEqual(plan_mentions(previous, unrelated, OWN)["events"], [])
        changed = copy.deepcopy(unrelated)
        changed["transclusions"][0]["version"] = 3
        events = plan_mentions(previous, changed, OWN)["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target_versions"], {"transclusion": 3})

    def test_withdrawn_stub_plans_one_withdrawal(self):
        previous = document()
        previous["stub_of"] = reference()
        withdrawn = document(version=2, kind="withdrawn")
        withdrawn.pop("transclusions")
        result = plan_mentions(previous, withdrawn, OWN)
        self.assertEqual(len(result["events"]), 1)
        self.assertTrue(result["events"][0]["withdrawal"])
        self.assertEqual(result["events"][0]["relations"], ["stub"])
        self.assertEqual(plan_mentions(withdrawn, withdrawn, OWN)["events"], [])

    def test_malformed_references_are_isolated_and_same_origin_is_ignored(self):
        current = document()
        current["transclusions"] = [None, {"origin": REMOTE, "id": "bad", "version": 1}, reference(origin=OWN)]
        result = plan_mentions(None, current, OWN)
        self.assertEqual(result["events"], [])
        self.assertEqual(len(result["issues"]), 2)


class OutboundQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.times = iter(
            [
                "2026-10-18T01:00:00Z",
                "2026-10-18T01:01:00Z",
                "2026-10-18T01:02:00Z",
                "2026-10-18T01:03:00Z",
                "2026-10-18T01:04:00Z",
                "2026-10-18T01:05:00Z",
            ]
        )
        self.queue = OutboundQueue(self.root, lambda: next(self.times))
        current = document()
        current["stub_of"] = reference()
        self.event = plan_mentions(None, current, OWN)["events"][0]

    def tearDown(self):
        self.temporary.cleanup()

    def test_enqueue_is_durable_private_and_idempotent(self):
        self.assertEqual(self.queue.enqueue([self.event]), [self.event["key"]])
        self.assertEqual(self.queue.enqueue([self.event]), [])
        reloaded = OutboundQueue(self.root, lambda: "later")
        self.assertEqual(len(reloaded.entries("pending")), 1)
        self.assertEqual(reloaded.entries()[0]["attempts"], 0)
        self.assertEqual(self.queue.file.stat().st_mode & 0o777, 0o600)

    def test_status_and_retry_metadata_survive_reload(self):
        self.queue.enqueue([self.event])
        updated = self.queue.update(
            self.event["key"],
            "retrying",
            endpoint="https://remote.example/webmention?token=kept",
            error="HTTP 503",
            next_attempt_at="2026-10-18T02:01:00Z",
        )
        self.assertEqual(updated["attempts"], 1)
        updated = self.queue.update(self.event["key"], "retrying", error="HTTP 502")
        self.assertEqual(updated["attempts"], 2)
        self.assertEqual(updated["endpoint"], "https://remote.example/webmention?token=kept")
        self.assertEqual(updated["next_attempt_at"], "2026-10-18T02:01:00Z")
        reloaded = OutboundQueue(self.root, lambda: "later")
        row = reloaded.entries()[0]
        self.assertEqual(row["status"], "retrying")
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["next_attempt_at"], "2026-10-18T02:01:00Z")
        self.assertEqual(row["endpoint"], "https://remote.example/webmention?token=kept")

    def test_pause_is_durable_and_migrates_existing_outbox_without_losing_work(self):
        self.queue.enqueue([self.event])
        legacy = json.loads(self.queue.file.read_text(encoding="utf-8"))
        legacy["schema"] = 1
        legacy.pop("paused")
        self.queue.file.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = OutboundQueue(self.root, lambda: "2026-10-18T01:30:00Z")
        self.assertFalse(migrated.paused())
        self.assertTrue(migrated.set_paused(True))
        reloaded = OutboundQueue(self.root, lambda: "later")
        self.assertTrue(reloaded.paused())
        self.assertEqual([row["key"] for row in reloaded.entries()], [self.event["key"]])
        saved = json.loads(reloaded.file.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], 2)
        self.assertTrue(saved["paused"])

    def test_overlapping_enqueues_do_not_lose_candidates(self):
        queues = [
            OutboundQueue(self.root, lambda: "2026-10-18T02:30:00Z"),
            OutboundQueue(self.root, lambda: "2026-10-18T02:31:00Z"),
        ]
        events = []
        for final in "234567abcdefgh":
            current = document()
            current["stub_of"] = reference(iid="0" * 25 + final)
            events.extend(plan_mentions(None, current, OWN)["events"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda pair: queues[pair[0] % 2].enqueue([pair[1]]),
                    enumerate(events),
                )
            )
        reloaded = OutboundQueue(self.root, lambda: "later")
        self.assertEqual(len(reloaded.entries()), len(events))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for deterministic process overlap")
    def test_overlapping_processes_do_not_lose_candidates(self):
        first = copy.deepcopy(self.event)
        current = document()
        current["stub_of"] = reference(iid=OTHER_ID)
        second = plan_mentions(None, current, OWN)["events"][0]
        context = multiprocessing.get_context("fork")
        ready, release, finished = context.Event(), context.Event(), context.Event()
        holding = context.Process(
            target=_held_outbox_enqueue,
            args=(str(self.root), first, ready, release),
        )
        following = context.Process(
            target=_plain_outbox_enqueue,
            args=(str(self.root), second, finished),
        )
        holding.start()
        self.assertTrue(ready.wait(5))
        following.start()
        self.assertFalse(finished.wait(0.2), "a second process bypassed the outbox lock")
        release.set()
        holding.join(5)
        following.join(5)
        self.assertEqual((holding.exitcode, following.exitcode), (0, 0))
        self.assertEqual(
            {row["key"] for row in OutboundQueue(self.root).entries()},
            {first["key"], second["key"]},
        )

    def test_missing_main_recovers_current_verified_backup(self):
        self.queue.enqueue([self.event])
        self.queue.file.unlink()
        recovered = OutboundQueue(self.root, lambda: "later")
        self.assertIn("disappeared", recovered.recovery_notice)
        self.assertEqual([row["key"] for row in recovered.entries()], [self.event["key"]])
        self.assertTrue(recovered.file.exists())

    def test_outbox_refuses_unsafe_process_lock(self):
        target = self.root / "outside-lock"
        target.write_text("", encoding="utf-8")
        lock = self.root / "webmentions-outbox.lock"
        lock.unlink()
        lock.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            OutboundQueue(self.root)

    def test_damaged_main_recovers_verified_backup_and_preserves_damage(self):
        self.queue.enqueue([self.event])
        self.queue.update(self.event["key"], "retrying", error="temporary")
        self.queue.file.write_text("{broken", encoding="utf-8")
        recovered = OutboundQueue(self.root, lambda: "2026-10-18T03:00:00Z")
        self.assertIn("verified backup", recovered.recovery_notice)
        self.assertEqual(recovered.entries()[0]["status"], "retrying")
        self.assertEqual(recovered.damaged_file.read_text(encoding="utf-8"), "{broken")
        json.loads(recovered.file.read_text(encoding="utf-8"))

    def test_no_verified_copy_is_read_only_and_preserves_damage(self):
        self.root.joinpath("webmentions-outbox.json").write_text("{broken", encoding="utf-8")
        self.root.joinpath("webmentions-outbox.backup.json").write_text("[]", encoding="utf-8")
        damaged = OutboundQueue(self.root, lambda: "2026-10-18T04:00:00Z")
        self.assertTrue(damaged.read_only)
        self.assertIn("read-only", damaged.recovery_notice)
        with self.assertRaisesRegex(ValueError, "read-only"):
            damaged.enqueue([self.event])
        self.assertEqual(damaged.damaged_file.read_text(encoding="utf-8"), "{broken")

    def test_rejects_tampering_unknown_status_and_terminal_transition(self):
        bad = copy.deepcopy(self.event)
        bad["source_version"] = 999
        with self.assertRaisesRegex(ValueError, "candidate"):
            self.queue.enqueue([bad])
        self.queue.enqueue([self.event])
        with self.assertRaisesRegex(ValueError, "status"):
            self.queue.update(self.event["key"], "mystery")
        self.queue.update(self.event["key"], "delivered")
        with self.assertRaisesRegex(ValueError, "terminal"):
            self.queue.update(self.event["key"], "retrying")


class DiscoveryTests(unittest.TestCase):
    def event(self, *, target_url=None, plain=False):
        current = document()
        if plain:
            current["stub_of"] = {"url": target_url}
        else:
            current["transclusions"] = [reference(url=target_url)]
        return plan_mentions(None, current, OWN)["events"][0]

    def test_manifest_endpoint_and_custom_item_template_resolve_target(self):
        net = Net()
        manifest = {
            "blyg": "0.4",
            "item": "api/items/{id}?format=blyg",
            "webmention": "receive?channel=blyg",
        }
        item_url = REMOTE + "api/items/" + TARGET_ID + "?format=blyg"
        net.add(REMOTE + "blyg.json", manifest)
        net.add(
            item_url,
            {"id": TARGET_ID, "origin": REMOTE, "page": "essays/target/"},
        )
        checked = []
        found = discover_endpoint(self.event(), net, lambda url: checked.append(url))
        self.assertEqual(found["endpoint"], REMOTE + "receive?channel=blyg")
        self.assertEqual(found["target"], REMOTE + "essays/target/")
        self.assertEqual(found["method"], "manifest")
        self.assertEqual(checked, [found["endpoint"]])
        self.assertEqual(
            net.calls,
            [
                ("GET", REMOTE + "blyg.json", 256 * 1024),
                ("GET", item_url, 1024 * 1024),
            ],
        )

    def test_manifest_precedes_w3c_and_preserves_endpoint_query(self):
        target = REMOTE + "t/" + TARGET_ID + "/"
        net = Net()
        net.add(REMOTE + "blyg.json", {"blyg": "0.4", "webmention": "/wm?token=kept"})
        found = discover_endpoint(self.event(target_url=target), net, lambda url: None)
        self.assertEqual(
            found,
            {"endpoint": "https://remote.example/wm?token=kept", "target": target, "method": "manifest"},
        )
        self.assertEqual(len(net.calls), 1)

    def test_http_link_precedes_html_and_head_precedes_get(self):
        target = REMOTE + "t/" + TARGET_ID + "/"
        net = Net()
        net.add(REMOTE + "blyg.json", {"blyg": "0.4"})
        net.add(
            target,
            headers={"Link": '<https://remote.example/first>; rel="alternate", <../../wm?token=yes>; rel="webmention"'},
            method="HEAD",
        )
        found = discover_endpoint(self.event(target_url=target), net, lambda url: None)
        self.assertEqual(found["endpoint"], REMOTE + "wm?token=yes")
        self.assertEqual(found["method"], "http-link")
        self.assertEqual([call[0] for call in net.calls], ["GET", "HEAD"])

    def test_html_discovery_and_absent_endpoint(self):
        target = "https://ordinary.example/post"
        net = Net()
        net.add(target, method="HEAD")
        net.add(target, '<p>post</p><a rel="alternate webmention" href="/mentions?x=1">send</a>')
        found = discover_endpoint(self.event(target_url=target, plain=True), net, lambda url: None)
        self.assertEqual(
            found,
            {"endpoint": "https://ordinary.example/mentions?x=1", "target": target, "method": "html"},
        )
        net.responses[("GET", target)] = (target, b"<p>none</p>", {}, 200)
        self.assertIsNone(discover_endpoint(self.event(target_url=target, plain=True), net, lambda url: None))

    def test_manifest_failure_falls_back_to_w3c_when_cited_page_exists(self):
        target = REMOTE + "t/" + TARGET_ID + "/"
        net = Net()
        net.add(target, headers={"Link": "</wm>; rel=webmention"}, method="HEAD")
        found = discover_endpoint(self.event(target_url=target), net, lambda url: None)
        self.assertEqual(found["endpoint"], "https://remote.example/wm")

    def test_unsafe_or_non_http_endpoint_is_rejected(self):
        target = "https://ordinary.example/post"
        for endpoint in ("http://127.0.0.1/private", "file:///tmp/receiver"):
            with self.subTest(endpoint=endpoint):
                net = Net()
                net.add(target, headers={"Link": f"<{endpoint}>; rel=webmention"}, method="HEAD")

                def guard(url):
                    if "127.0.0.1" in url:
                        raise ValueError("Webmention endpoints must use public internet addresses.")

                with self.assertRaises(ValueError):
                    discover_endpoint(self.event(target_url=target, plain=True), net, guard)

    def test_bad_template_and_redirected_item_identity_are_rejected(self):
        net = Net()
        net.add(REMOTE + "blyg.json", {"blyg": "0.4", "item": "api/{other}"})
        with self.assertRaisesRegex(ValueError, "template"):
            discover_endpoint(self.event(), net, lambda url: None)

        net = Net()
        item_url = REMOTE + "items/" + TARGET_ID + ".json"
        net.add(REMOTE + "blyg.json", {"blyg": "0.4"})
        net.add(
            item_url,
            {"id": TARGET_ID, "origin": REMOTE, "page": "target/"},
            final="https://evil.example/items/" + TARGET_ID + ".json",
        )
        with self.assertRaisesRegex(ValueError, "redirected"):
            discover_endpoint(self.event(), net, lambda url: None)

    def test_default_transport_revalidates_redirect_and_honors_bound(self):
        responses = [
            (302, b"", {"Location": "https://second.example/end"}),
            (200, b"ok", {}),
        ]
        with patch(
            "reader_network.public_url",
            side_effect=[(None, ["203.0.113.1"]), (None, ["203.0.113.2"])],
        ) as validate, patch("reader_network.request_once", side_effect=responses):
            final, body, _, _ = fetch_bounded("https://first.example/start", redirects=1)
        self.assertEqual((final, body), ("https://second.example/end", b"ok"))
        self.assertEqual(validate.call_count, 2)

        looping = (302, b"", {"Location": "/again"})
        with patch("reader_network.public_url", return_value=(None, ["203.0.113.1"])), patch(
            "reader_network.request_once", return_value=looping
        ):
            with self.assertRaisesRegex(ValueError, "Too many redirects"):
                fetch_bounded("https://first.example/start", redirects=1)

        with patch(
            "reader_network.public_url",
            side_effect=[(None, ["203.0.113.1"]), ValueError("public internet addresses")],
        ), patch("reader_network.request_once", return_value=responses[0]):
            with self.assertRaisesRegex(ValueError, "public internet"):
                fetch_bounded("https://first.example/start", redirects=1)

    def test_default_transport_sends_head_and_rejects_private_dns(self):
        response = (200, b"", {})
        with patch("reader_network.public_url", return_value=(None, ["203.0.113.4"])), patch(
            "reader_network.request_once", return_value=response
        ) as request:
            fetch_bounded("https://remote.example/post", method="HEAD", limit=0)
        request.assert_called_once_with(
            "https://remote.example/post",
            "203.0.113.4",
            None,
            0,
            method="HEAD",
            timeout=5,
            deadline=ANY,
        )

        private = [(None, None, None, None, ("127.0.0.1", 443))]
        with patch("reader_network.socket.getaddrinfo", return_value=private):
            with self.assertRaisesRegex(ValueError, "public internet"):
                public_url("https://remote.example/post")


class DeliveryTests(unittest.TestCase):
    def event(self, *, withdrawal=False):
        before = document()
        before["stub_of"] = reference(url=REMOTE + "t/" + TARGET_ID + "/")
        if not withdrawal:
            return plan_mentions(None, before, OWN)["events"][0]
        after = document(version=2, kind="withdrawn")
        after.pop("transclusions")
        return plan_mentions(before, after, OWN)["events"][0]

    def test_disposable_endpoint_receives_exact_w3c_form_for_withdrawal(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received.update(
                    path=self.path,
                    content_type=self.headers.get("Content-Type"),
                    body=self.rfile.read(length),
                )
                self.send_response(202)
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def local_post(endpoint, body, *, headers, limit, timeout):
            parsed = urlsplit(endpoint)
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
            try:
                connection.request("POST", parsed.path + "?" + parsed.query, body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read(limit + 1)
                return endpoint, payload, dict(response.getheaders()), response.status
            finally:
                connection.close()

        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/receive?token=kept"
            result = deliver_webmention(
                self.event(withdrawal=True),
                {"endpoint": endpoint, "target": REMOTE + "t/" + TARGET_ID + "/"},
                poster=local_post,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(received["path"], "/receive?token=kept")
        self.assertEqual(received["content_type"], "application/x-www-form-urlencoded")
        self.assertEqual(
            parse_qs(received["body"].decode("ascii"), strict_parsing=True),
            {
                "source": [OWN + "t/" + SOURCE_ID + "/"],
                "target": [REMOTE + "t/" + TARGET_ID + "/"],
            },
        )
        self.assertNotIn(b"withdraw", received["body"])

    def test_response_classes_and_finite_retry_schedule(self):
        event = self.event()
        discovery = {
            "endpoint": REMOTE + "webmention",
            "target": REMOTE + "t/" + TARGET_ID + "/",
        }

        def response(status):
            return lambda *args, **kwargs: (args[0], b"", {}, status)

        for status in (200, 201, 202, 204, 299):
            with self.subTest(status=status):
                self.assertEqual(
                    deliver_webmention(event, discovery, poster=response(status))["status"],
                    "delivered",
                )
        for status in (300, 400, 404, 410, 499):
            with self.subTest(status=status):
                self.assertEqual(
                    deliver_webmention(event, discovery, poster=response(status))["status"],
                    "rejected",
                )
        expected = [900, 3600, 14400, 43200, 86400]
        for attempt, delay in enumerate(expected, 1):
            with self.subTest(attempt=attempt):
                result = deliver_webmention(event, discovery, attempt=attempt, poster=response(503))
                self.assertEqual((result["status"], result["retry_after"]), ("retrying", delay))
        self.assertEqual(
            deliver_webmention(event, discovery, attempt=6, poster=response(503))["status"],
            "abandoned",
        )
        self.assertEqual(
            deliver_webmention(event, discovery, poster=response(429))["status"],
            "retrying",
        )

    def test_network_failure_retries_then_abandons(self):
        event = self.event()
        discovery = {"endpoint": REMOTE + "webmention", "target": REMOTE + "target"}

        def unavailable(*args, **kwargs):
            raise ValueError("connection refused")

        first = deliver_webmention(event, discovery, attempt=1, poster=unavailable)
        last = deliver_webmention(event, discovery, attempt=6, poster=unavailable)
        self.assertEqual((first["status"], first["retry_after"]), ("retrying", 900))
        self.assertEqual((last["status"], last["retry_after"]), ("abandoned", None))
        self.assertIn("connection refused", last["error"])

    def test_default_post_transport_pins_address_and_bounds_response(self):
        response = (202, b"accepted", {"Content-Type": "text/plain"})
        body = b"source=https%3A%2F%2Fmine.example&target=https%3A%2F%2Fremote.example"
        with patch("reader_network.public_url", return_value=(None, ["203.0.113.8"])), patch(
            "reader_network.request_once", return_value=response
        ) as request:
            final, payload, _, status = post_bounded(
                "https://remote.example/webmention?token=kept",
                body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        self.assertEqual((final, payload, status), ("https://remote.example/webmention?token=kept", b"accepted", 202))
        request.assert_called_once_with(
            "https://remote.example/webmention?token=kept",
            "203.0.113.8",
            {"Content-Type": "application/x-www-form-urlencoded"},
            64 * 1024,
            method="POST",
            timeout=5,
            body=body,
            deadline=ANY,
        )


class OutboundWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = OutboundQueue(self.root, lambda: "2026-10-18T12:00:00Z")
        self.event = self.make_event(TARGET_ID)
        self.discovery = {
            "endpoint": REMOTE + "webmention?token=kept",
            "target": REMOTE + "t/" + TARGET_ID + "/",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def make_event(self, target_id):
        current = document()
        current["stub_of"] = reference(iid=target_id, url=REMOTE + "t/" + target_id + "/")
        return plan_mentions(None, current, OWN)["events"][0]

    @staticmethod
    def response(status):
        return lambda endpoint, body, **kwargs: (endpoint, b"", {}, status)

    def test_async_pass_returns_immediately_and_does_not_block_enqueue(self):
        self.queue.enqueue([self.event])
        entered = threading.Event()
        release = threading.Event()

        def slow_delivery(record, discovery, *, attempt):
            entered.set()
            self.assertTrue(release.wait(5))
            return deliver_webmention(
                record,
                discovery,
                attempt=attempt,
                poster=self.response(202),
            )

        worker = OutboundWorker(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=slow_delivery,
            clock=lambda: "2026-10-18T12:00:00Z",
        )
        started = time.monotonic()
        self.assertTrue(worker.start())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(entered.wait(2))

        later = self.make_event(OTHER_ID)
        enqueued = time.monotonic()
        self.assertEqual(self.queue.enqueue([later]), [later["key"]])
        self.assertLess(time.monotonic() - enqueued, 0.5)
        release.set()
        self.assertTrue(worker.join(3))
        self.assertIsNone(worker.last_error)
        states = {row["key"]: row["status"] for row in self.queue.entries()}
        self.assertEqual(states[self.event["key"]], "delivered")
        self.assertEqual(states[later["key"]], "pending")

    def test_retry_time_survives_restart_and_only_runs_when_due(self):
        self.queue.enqueue([self.event])
        first = OutboundWorker(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=lambda record, discovery, attempt: deliver_webmention(
                record,
                discovery,
                attempt=attempt,
                poster=self.response(503),
            ),
            clock=lambda: "2026-10-18T12:00:00Z",
        )
        first.run_due()
        row = self.queue.entries()[0]
        self.assertEqual((row["status"], row["attempts"]), ("retrying", 1))
        self.assertEqual(row["next_attempt_at"], "2026-10-18T12:15:00Z")

        reloaded = OutboundQueue(self.root, lambda: "2026-10-18T12:10:00Z")
        calls = []

        def accepted(record, discovery, *, attempt):
            calls.append(attempt)
            return deliver_webmention(
                record,
                discovery,
                attempt=attempt,
                poster=self.response(202),
            )

        early = OutboundWorker(
            reloaded,
            discoverer=lambda record: self.discovery,
            deliverer=accepted,
            clock=lambda: "2026-10-18T12:14:59Z",
        )
        self.assertEqual(early.run_due(), [])
        self.assertEqual(calls, [])
        due = OutboundWorker(
            reloaded,
            discoverer=lambda record: self.discovery,
            deliverer=accepted,
            clock=lambda: "2026-10-18T12:15:00Z",
        )
        due.run_due()
        self.assertEqual(calls, [2])
        self.assertEqual(reloaded.entries()[0]["status"], "delivered")

    def test_restart_retries_same_logical_event_after_remote_acceptance(self):
        self.queue.enqueue([self.event])
        accepted = []

        def delivery(record, discovery, *, attempt):
            accepted.append((record["key"], record["source"], discovery["target"]))
            return deliver_webmention(
                record,
                discovery,
                attempt=attempt,
                poster=self.response(202),
            )

        def crash_after_acceptance(*args):
            raise SystemExit("simulated process loss")

        interrupted = OutboundWorker(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=delivery,
            after_delivery=crash_after_acceptance,
            clock=lambda: "2026-10-18T12:00:00Z",
        )
        with self.assertRaisesRegex(SystemExit, "process loss"):
            interrupted.run_due()
        self.assertEqual(self.queue.entries()[0]["status"], "pending")

        reloaded = OutboundQueue(self.root, lambda: "2026-10-18T12:01:00Z")
        recovered = OutboundWorker(
            reloaded,
            discoverer=lambda record: self.discovery,
            deliverer=delivery,
            clock=lambda: "2026-10-18T12:01:00Z",
        )
        recovered.run_due()
        self.assertEqual(len(accepted), 2)
        self.assertEqual(accepted[0], accepted[1])
        self.assertEqual(len(reloaded.entries()), 1)
        self.assertEqual(reloaded.entries()[0]["status"], "delivered")

    def test_discovery_absence_is_terminal_and_failure_is_retryable(self):
        absent = self.event
        failed = self.make_event(OTHER_ID)
        self.queue.enqueue([absent, failed])

        def discovery(record):
            if record["key"] == absent["key"]:
                return None
            raise ValueError("temporary discovery outage")

        worker = OutboundWorker(
            self.queue,
            discoverer=discovery,
            clock=lambda: "2026-10-18T12:00:00Z",
        )
        worker.run_due()
        states = {row["key"]: row for row in self.queue.entries()}
        self.assertEqual(states[absent["key"]]["status"], "no_endpoint")
        self.assertEqual(states[failed["key"]]["status"], "retrying")
        self.assertEqual(states[failed["key"]]["next_attempt_at"], "2026-10-18T12:15:00Z")

    def test_worker_persists_five_retries_then_abandons(self):
        self.queue.enqueue([self.event])
        moments = iter(
            [
                "2026-10-18T12:00:00Z",
                "2026-10-18T12:15:00Z",
                "2026-10-18T13:15:00Z",
                "2026-10-18T17:15:00Z",
                "2026-10-19T05:15:00Z",
                "2026-10-20T05:15:00Z",
            ]
        )
        for _ in range(6):
            moment = next(moments)
            worker = OutboundWorker(
                self.queue,
                discoverer=lambda record: self.discovery,
                deliverer=lambda record, discovery, attempt: deliver_webmention(
                    record,
                    discovery,
                    attempt=attempt,
                    poster=self.response(503),
                ),
                clock=lambda moment=moment: moment,
            )
            worker.run_due()
        row = self.queue.entries()[0]
        self.assertEqual(row["status"], "abandoned")
        self.assertEqual(row["attempts"], 5)
        self.assertIsNone(row["next_attempt_at"])


class OutboundServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = OutboundQueue(self.root, lambda: "2026-10-18T15:00:00Z")
        current = document()
        current["stub_of"] = reference(iid=TARGET_ID, url=REMOTE + "t/" + TARGET_ID + "/")
        self.event = plan_mentions(None, current, OWN)["events"][0]
        self.discovery = {
            "endpoint": REMOTE + "webmention",
            "target": REMOTE + "t/" + TARGET_ID + "/",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def wait_for(self, predicate, timeout=3):
        limit = time.monotonic() + timeout
        while time.monotonic() < limit:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("background Webmention service did not reach the expected state")

    def test_start_returns_immediately_and_startup_pass_delivers(self):
        self.queue.enqueue([self.event])
        entered = threading.Event()
        release = threading.Event()

        def delayed(record, discovery, *, attempt):
            entered.set()
            self.assertTrue(release.wait(3))
            return {"status": "delivered", "error": None, "retry_after": None}

        service = OutboundService(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=delayed,
            check_interval=60,
        )
        started = time.monotonic()
        self.assertTrue(service.start())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(entered.wait(2))
        release.set()
        self.wait_for(lambda: self.queue.entries()[0]["status"] == "delivered")
        self.assertTrue(service.stop())

    def test_wake_delivers_work_enqueued_after_idle_start(self):
        service = OutboundService(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=lambda record, discovery, attempt: {
                "status": "delivered", "error": None, "retry_after": None
            },
            check_interval=60,
        )
        service.start()
        self.wait_for(lambda: service.status()["last_run_at"] is not None)
        self.queue.enqueue([self.event])
        service.wake()
        self.wait_for(lambda: self.queue.entries()[0]["status"] == "delivered")
        self.assertTrue(service.stop())

    def test_pause_survives_restart_and_resume_delivers_preserved_work(self):
        self.queue.enqueue([self.event])
        calls = []

        def deliver(record, discovery, *, attempt):
            calls.append(record["key"])
            return {"status": "delivered", "error": None, "retry_after": None}

        first = OutboundService(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=deliver,
            check_interval=60,
        )
        self.assertEqual(first.pause(True), {"paused": True})
        first.start()
        self.wait_for(lambda: first.status()["last_run_at"] is not None)
        self.assertEqual(calls, [])
        self.assertEqual(self.queue.entries()[0]["status"], "pending")
        self.assertTrue(first.stop())

        reloaded = OutboundQueue(self.root, lambda: "2026-10-18T15:01:00Z")
        second = OutboundService(
            reloaded,
            discoverer=lambda record: self.discovery,
            deliverer=deliver,
            check_interval=60,
        )
        self.assertTrue(second.status()["paused"])
        second.start()
        self.wait_for(lambda: second.status()["last_run_at"] is not None)
        self.assertEqual(calls, [])
        self.assertEqual(second.pause(False), {"paused": False})
        self.wait_for(lambda: reloaded.entries()[0]["status"] == "delivered")
        self.assertEqual(calls, [self.event["key"]])
        self.assertTrue(second.stop())

    def test_status_exposes_sanitized_read_only_delivery_records(self):
        current = document()
        current["stub_of"] = {"url": "https://ordinary.example/article?token=target#fragment"}
        event = plan_mentions(None, current, OWN)["events"][0]
        self.queue.enqueue([event])
        self.queue.update(
            event["key"],
            "retrying",
            endpoint=REMOTE + "webmention?token=secret",
            error="HTTP 503 from " + REMOTE + "webmention?token=secret",
            next_attempt_at="2026-10-18T15:15:00Z",
        )
        service = OutboundService(self.queue)

        status = service.status()

        self.assertFalse(status["running"])
        self.assertEqual(status["counts"]["retrying"], 1)
        self.assertEqual(len(status["entries"]), 1)
        row = status["entries"][0]
        self.assertEqual(row["source_id"], SOURCE_ID)
        self.assertEqual(row["source"], OWN + "t/" + SOURCE_ID + "/")
        self.assertEqual(row["target"], "https://ordinary.example/article")
        self.assertEqual(row["endpoint"], REMOTE + "webmention")
        self.assertNotIn("secret", json.dumps(status))
        self.assertNotIn("target#", json.dumps(status))
        self.assertEqual(self.queue.entries()[0]["endpoint"], REMOTE + "webmention?token=secret")

    def test_token_protected_status_api_returns_service_snapshot(self):
        self.queue.enqueue([self.event])
        service = OutboundService(self.queue)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.token = "status-token"
        server.webmentions = service
        class StatusStudio:
            state = {"published": {SOURCE_ID: {"title": "Local response"}}}

            @staticmethod
            def item_title(document):
                return document["title"]

        server.studio = StatusStudio()
        server.lock = threading.RLock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/api/webmentions-status", headers={"X-Blynger-Token": "status-token"})
            response = connection.getresponse()
            payload = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["counts"]["pending"], 1)
            self.assertFalse(payload["paused"])
            self.assertEqual(payload["entries"][0]["relations"], ["stub"])
            self.assertEqual(payload["entries"][0]["title"], "Local response")

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            body = json.dumps({"paused": True})
            connection.request(
                "POST",
                "/api/webmentions-pause",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "X-Blynger-Token": "status-token",
                },
            )
            paused = connection.getresponse()
            pause_payload = json.loads(paused.read())
            connection.close()
            self.assertEqual(paused.status, 200)
            self.assertTrue(pause_payload["paused"])
            self.assertTrue(OutboundQueue(self.root).paused())

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/api/webmentions-status")
            rejected = connection.getresponse()
            rejected.read()
            connection.close()
            self.assertEqual(rejected.status, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_service_failure_preserves_work_and_later_wake_recovers(self):
        self.queue.enqueue([self.event])
        broken = {"value": True}

        def discovery(record):
            if broken["value"]:
                raise RuntimeError("temporary worker failure")
            return self.discovery

        service = OutboundService(
            self.queue,
            discoverer=discovery,
            deliverer=lambda record, found, attempt: {
                "status": "delivered", "error": None, "retry_after": None
            },
            check_interval=60,
        )
        service.start()
        self.wait_for(lambda: service.status()["last_error"] == "temporary worker failure")
        self.assertEqual(self.queue.entries()[0]["status"], "pending")
        broken["value"] = False
        service.wake()
        self.wait_for(lambda: self.queue.entries()[0]["status"] == "delivered")
        self.assertIsNone(service.status()["last_error"])
        self.assertTrue(service.stop())

    def test_due_retry_runs_while_application_remains_open(self):
        self.queue.enqueue([self.event])
        moment = {"value": "2026-10-18T15:00:00Z"}
        attempts = []

        def delivery(record, discovery, *, attempt):
            attempts.append(attempt)
            if attempt == 1:
                return {"status": "retrying", "error": "unavailable", "retry_after": 900}
            return {"status": "delivered", "error": None, "retry_after": None}

        service = OutboundService(
            self.queue,
            discoverer=lambda record: self.discovery,
            deliverer=delivery,
            clock=lambda: moment["value"],
            check_interval=60,
        )
        service.start()
        self.wait_for(lambda: self.queue.entries()[0]["status"] == "retrying")
        self.assertEqual(attempts, [1])
        moment["value"] = "2026-10-18T15:15:00Z"
        service.wake()
        self.wait_for(lambda: self.queue.entries()[0]["status"] == "delivered")
        self.assertEqual(attempts, [1, 2])
        self.assertTrue(service.stop())

    def test_outbox_open_failure_does_not_prevent_application_start(self):
        with patch("webmentions.OutboundQueue", side_effect=OSError("private storage unavailable")):
            service = open_outbound_service(self.root)
        self.assertFalse(service.start())
        self.assertIn("private storage unavailable", service.status()["last_error"])
        with self.assertRaisesRegex(ValueError, "private storage unavailable"):
            service.wake()
        self.assertTrue(service.stop())


if __name__ == "__main__":
    unittest.main()
