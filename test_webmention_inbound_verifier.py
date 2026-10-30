import json
import fcntl
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import webmentions.inbound_verifier as verifier_module
from reader_network import HTTPStatusError
from webmentions.inbound_contract import InboundClaim
from webmentions.inbound_queue import InboundQueue
from webmentions.inbound_targets import build_target_registry
from webmentions.inbound_sync import InboundMentionArchive
from webmentions.inbound_verifier import (
    AUTHOR_LIMIT,
    BODY_LIMIT,
    InboundVerifierWorker,
    RETRY_DELAYS,
    StructuralVerifier,
    VerificationFailure,
    VerificationStore,
    validate_verification_export,
)


OWN = "https://example.com/blyg/"
TARGET_ID = "00000000000000000000000002"
TARGET_PAGE = OWN + "t/" + TARGET_ID + "/"
SOURCE_ORIGIN = "https://writer.example/blyg/"
SOURCE_ID = "00000000000000000000000001"
SOURCE_PAGE = SOURCE_ORIGIN + "t/" + SOURCE_ID + "/"
SOURCE_ITEM = SOURCE_ORIGIN + "items/" + SOURCE_ID + ".json"


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds=1):
        self.value += seconds


class Fetcher:
    def __init__(self):
        self.responses = {}
        self.calls = []

    def add(self, url, body, *, final=None, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.responses[url] = (final or url, body, {"Content-Type": content_type}, 200)

    def __call__(self, url, **options):
        self.calls.append((url, options))
        if url not in self.responses:
            raise ValueError("fixture unavailable")
        return self.responses[url]


def target_document(pins=(1,)):
    return {
        "blyg": "0.4",
        "id": TARGET_ID,
        "kind": "thread",
        "origin": OWN,
        "page": "t/" + TARGET_ID + "/",
        "version": 2,
        "changelog": [
            {"version": 1, "pinned": 1 in pins},
            {"version": 2, "pinned": 2 in pins},
        ],
    }


def registry(pins=(1,)):
    return build_target_registry(
        OWN,
        {"blyg": "0.4", "site": OWN},
        [target_document(pins)],
    )


def source_document(**changes):
    value = {
        "blyg": "0.4",
        "id": SOURCE_ID,
        "kind": "thread",
        "origin": SOURCE_ORIGIN,
        "page": "t/" + SOURCE_ID + "/",
        "version": 3,
        "author": {"name": "Writer"},
        "transclusions": [],
    }
    value.update(changes)
    return value


def relation_document(name):
    reference = {"origin": OWN, "id": TARGET_ID, "version": 1, "cited": {"ignored": True}}
    if name == "stub":
        return source_document(stub_of=reference)
    if name == "transclusion":
        return source_document(transclusions=[reference])
    if name == "fork":
        return source_document(forked_from=reference)
    if name == "source":
        return source_document(generated=[{"sources": [reference]}])
    if name == "link":
        return source_document(links=[{"origin": OWN, "id": TARGET_ID}])
    raise AssertionError(name)


def html_alternate(url=SOURCE_ITEM):
    return '<html><head><link rel="alternate" type="application/json" href="' + url + '"></head></html>'


class StructuralVerifierTests(unittest.TestCase):
    def verifier(self, document, *, source=SOURCE_PAGE, fetcher=None, target=TARGET_PAGE):
        fetcher = fetcher or Fetcher()
        if source == SOURCE_PAGE:
            fetcher.add(SOURCE_PAGE, html_alternate(), content_type="text/html; charset=utf-8")
            fetcher.add(SOURCE_ITEM, document)
        row = {"source": source, "target": target}
        return StructuralVerifier(registry(), fetcher, Clock()), row, fetcher

    def test_recognizes_all_five_relations_and_priority(self):
        for name in ("stub", "transclusion", "fork", "source", "link"):
            with self.subTest(name=name):
                verifier, row, fetcher = self.verifier(relation_document(name))
                result = verifier.verify(row)
                self.assertEqual(result["relation"], name)
                self.assertEqual(result["source_item_id"], SOURCE_ID)
                self.assertEqual(result["source_page"], SOURCE_PAGE)
                self.assertEqual(
                    result["mention_class"],
                    "notice" if name == "link" else "response",
                )
                self.assertEqual(len(fetcher.calls), 2)
                for _, options in fetcher.calls:
                    self.assertEqual(
                        (options["limit"], options["redirects"], options["timeout"]),
                        (BODY_LIMIT, 3, 5),
                    )
        document = relation_document("transclusion")
        document["stub_of"] = {"origin": OWN, "id": TARGET_ID, "version": 1}
        verifier, row, _ = self.verifier(document)
        self.assertEqual(verifier.verify(row)["relation"], "stub")

    def test_content_free_stub_and_transclusion_are_repost_notices(self):
        reference = {"origin": OWN, "id": TARGET_ID, "version": 1}
        cases = (
            source_document(stub_of=reference, content_md="![[" + TARGET_ID + "]]"),
            source_document(transclusions=[reference], content_md="![[" + TARGET_ID + "]]\n\n> selected words"),
        )
        for document in cases:
            verifier, row, _ = self.verifier(document)
            self.assertEqual(verifier.verify(row)["mention_class"], "notice")

    def test_own_words_make_stub_or_transclusion_a_response(self):
        reference = {"origin": OWN, "id": TARGET_ID, "version": 1}
        document = source_document(
            stub_of=reference,
            content_md="My own response.\n\n![[" + TARGET_ID + "]]",
        )
        verifier, row, _ = self.verifier(document)
        self.assertEqual(verifier.verify(row)["mention_class"], "response")

    def test_generation_source_relation_requires_blyg_04(self):
        document = relation_document("source")
        document["blyg"] = "0.3"
        verifier, row, _ = self.verifier(document)
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify(row)
        self.assertEqual(caught.exception.code, "no_relation")

    def test_custom_04_item_template_uses_exact_third_fetch(self):
        item = "https://writer.example/api/blyg/" + SOURCE_ID + "?format=json"
        fetcher = Fetcher()
        fetcher.add(SOURCE_PAGE, html_alternate(item), content_type="text/html")
        fetcher.add(item, relation_document("stub"))
        fetcher.add(
            SOURCE_ORIGIN + "blyg.json",
            {"blyg": "0.4", "item": "https://writer.example/api/blyg/{id}?format=json"},
        )
        verifier = StructuralVerifier(registry(), fetcher, Clock())
        self.assertEqual(verifier.verify({"source": SOURCE_PAGE, "target": TARGET_PAGE})["relation"], "stub")
        self.assertEqual(len(fetcher.calls), 3)

    def test_direct_json_source_must_be_the_live_document(self):
        fetcher = Fetcher()
        fetcher.add(SOURCE_ITEM, relation_document("stub"))
        result = StructuralVerifier(registry(), fetcher, Clock()).verify(
            {"source": SOURCE_ITEM, "target": TARGET_PAGE}
        )
        self.assertEqual(result["source_page"], SOURCE_PAGE)

    def test_plain_link_wrong_page_and_wrong_document_location_fail(self):
        cases = []
        cases.append(self.verifier(source_document(content_html='<a href="' + TARGET_PAGE + '">link</a>')))
        cases.append(self.verifier(relation_document("stub") | {"page": "elsewhere/"}))
        bad_fetcher = Fetcher()
        bad = SOURCE_ORIGIN + "shadow/" + SOURCE_ID + ".json"
        bad_fetcher.add(SOURCE_PAGE, html_alternate(bad), content_type="text/html")
        bad_fetcher.add(bad, relation_document("stub"))
        bad_fetcher.add(SOURCE_ORIGIN + "blyg.json", {"blyg": "0.4", "item": "other/{id}.json"})
        cases.append((StructuralVerifier(registry(), bad_fetcher, Clock()), {"source": SOURCE_PAGE, "target": TARGET_PAGE}, bad_fetcher))
        expected = ("no_relation", "invalid_source", "wrong_location")
        for case, code in zip(cases, expected):
            with self.subTest(code=code), self.assertRaises(VerificationFailure) as caught:
                case[0].verify(case[1])
            self.assertEqual(caught.exception.code, code)

    def test_fork_requires_receiver_known_pin(self):
        verifier, row, _ = self.verifier(relation_document("fork"))
        verifier.registry = registry(())
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify(row)
        self.assertEqual(caught.exception.code, "unpublished_fork")

    def test_pinned_document_and_page_are_valid_targets(self):
        targets = (
            OWN + "items/" + TARGET_ID + "/v1.json",
            TARGET_PAGE + "v1/",
        )
        for target in targets:
            with self.subTest(target=target):
                verifier, row, _ = self.verifier(relation_document("stub"), target=target)
                result = verifier.verify(row)
                self.assertEqual(result["relation"], "stub")

    def test_malformed_duplicate_json_html_without_alternate_and_oversize_author_fail(self):
        fixtures = []
        duplicate = Fetcher()
        duplicate.add(SOURCE_ITEM, '{"blyg":"0.4","blyg":"0.3"}')
        fixtures.append((StructuralVerifier(registry(), duplicate, Clock()), {"source": SOURCE_ITEM, "target": TARGET_PAGE}, "invalid_document"))
        no_link = Fetcher()
        no_link.add(SOURCE_PAGE, "<html><a href='target'>ordinary</a></html>", content_type="text/html")
        fixtures.append((StructuralVerifier(registry(), no_link, Clock()), {"source": SOURCE_PAGE, "target": TARGET_PAGE}, "invalid_source"))
        huge = source_document(author={"bio": "x" * (AUTHOR_LIMIT + 1)}, stub_of={"origin": OWN, "id": TARGET_ID, "version": 1})
        verifier, row, _ = self.verifier(huge)
        fixtures.append((verifier, row, "invalid_document"))
        for verifier, row, code in fixtures:
            with self.subTest(code=code), self.assertRaises(VerificationFailure) as caught:
                verifier.verify(row)
            self.assertEqual(caught.exception.code, code)

    def test_pathological_json_and_unsafe_alternate_location_are_inert(self):
        nested = Fetcher()
        nested.add(
            SOURCE_ITEM,
            b'{"value":' + b"[" * 1200 + b"0" + b"]" * 1200 + b"}",
        )
        unsafe = Fetcher()
        unsafe.add(
            SOURCE_PAGE,
            html_alternate("file:///etc/passwd"),
            content_type="text/html",
        )
        cases = (
            (StructuralVerifier(registry(), nested, Clock()), SOURCE_ITEM),
            (StructuralVerifier(registry(), unsafe, Clock()), SOURCE_PAGE),
        )
        for verifier, source in cases:
            with self.subTest(source=source), self.assertRaises(VerificationFailure):
                verifier.verify({"source": source, "target": TARGET_PAGE})

    def test_hostile_author_strings_remain_bounded_metadata(self):
        author = {
            "name": '<img src=x onerror="fetch(\'/api/settings\')">',
            "url": "file:///etc/passwd",
            "extra": {"path": "../../drafts", "script": "javascript:alert(1)"},
        }
        verifier, row, _ = self.verifier(
            source_document(
                author=author,
                stub_of={"origin": OWN, "id": TARGET_ID, "version": 1},
            )
        )
        result = verifier.verify(row)
        self.assertEqual(result["source_author"], author)
        self.assertIsNot(result["source_author"], author)

    def test_deep_small_author_is_an_invalid_document(self):
        document = relation_document("stub")
        document.pop("author")
        encoded = json.dumps(document, separators=(",", ":"))[:-1]
        nested = '{"child":' * 400 + '"Writer"' + "}" * 400
        payload = (encoded + ',"author":' + nested + "}").encode()
        self.assertLess(len(nested.encode()), AUTHOR_LIMIT)
        fetcher = Fetcher()
        fetcher.add(SOURCE_ITEM, payload)
        verifier = StructuralVerifier(registry(), fetcher, Clock())
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify({"source": SOURCE_ITEM, "target": TARGET_PAGE})
        self.assertEqual(caught.exception.code, "invalid_document")

    def test_invalid_author_field_types_and_lengths_are_rejected(self):
        cases = (
            {"name": ["Writer"]},
            {"name": "x" * 201},
            {"url": 7},
        )
        for author in cases:
            with self.subTest(author=author):
                document = relation_document("stub") | {"author": author}
                fetcher = Fetcher()
                fetcher.add(SOURCE_ITEM, document)
                verifier = StructuralVerifier(registry(), fetcher, Clock())
                with self.assertRaises(VerificationFailure) as caught:
                    verifier.verify({"source": SOURCE_ITEM, "target": TARGET_PAGE})
                self.assertEqual(caught.exception.code, "invalid_document")

    def test_deleted_source_is_distinct_from_deleted_supporting_document(self):
        def deleted_source(url, **_options):
            raise HTTPStatusError(410, url)

        verifier = StructuralVerifier(registry(), deleted_source, Clock())
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify({"source": SOURCE_PAGE, "target": TARGET_PAGE})
        self.assertEqual(caught.exception.code, "source_gone")

        def deleted_alternate(url, **_options):
            if url == SOURCE_PAGE:
                return url, html_alternate().encode(), {"Content-Type": "text/html"}, 200
            raise HTTPStatusError(404, url)

        verifier = StructuralVerifier(registry(), deleted_alternate, Clock())
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify({"source": SOURCE_PAGE, "target": TARGET_PAGE})
        self.assertEqual(caught.exception.code, "fetch_failed")

    def test_fetch_failures_are_fixed_diagnostics_without_untrusted_text(self):
        verifier = StructuralVerifier(registry(), Fetcher(), Clock())
        with self.assertRaises(VerificationFailure) as caught:
            verifier.verify({"source": SOURCE_PAGE + "?secret=token", "target": TARGET_PAGE})
        self.assertEqual(str(caught.exception), "fetch_failed")
        self.assertNotIn("secret", str(caught.exception))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.queue = InboundQueue(self.root / "inbox", self.clock)
        self.fetcher = Fetcher()
        self.fetcher.add(SOURCE_PAGE, html_alternate(), content_type="text/html")
        self.fetcher.add(SOURCE_ITEM, relation_document("stub"))

    def tearDown(self):
        self.temporary.cleanup()

    def accept(self):
        claim = InboundClaim(SOURCE_PAGE, TARGET_PAGE, "writer.example")
        return self.queue.accept(
            claim,
            peer="198.51.100.1",
            source_group="writer.example",
            published_targets=set(registry()["targets"]),
        )

    def worker(self, fetcher=None):
        return InboundVerifierWorker(
            self.queue,
            registry(),
            self.root / "verified",
            fetcher=fetcher or self.fetcher,
            clock=self.clock,
        )

    def test_verified_record_is_private_bounded_and_contains_no_body(self):
        row = self.accept()
        self.assertEqual(self.worker().run(), 1)
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["phase"], record["relation"]), ("verified", "final", "stub"))
        self.assertNotIn("content_html", record)
        path = self.root / "verified" / (row["key"] + ".json")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual((path.parent / "worker.lock").stat().st_mode & 0o777, 0o600)

    def test_deep_author_fails_one_item_and_later_item_still_verifies(self):
        hostile_id = "00000000000000000000000003"
        hostile_item = "https://hostile.example/blyg/items/" + hostile_id + ".json"
        hostile = relation_document("stub") | {
            "id": hostile_id,
            "origin": "https://hostile.example/blyg/",
            "page": "t/" + hostile_id + "/",
        }
        hostile.pop("author")
        encoded = json.dumps(hostile, separators=(",", ":"))[:-1]
        nested = '{"child":' * 400 + '"Writer"' + "}" * 400
        self.fetcher.add(hostile_item, (encoded + ',"author":' + nested + "}").encode())
        hostile_row = self.queue.accept(
            InboundClaim(hostile_item, TARGET_PAGE, "hostile.example"),
            peer="198.51.100.2",
            source_group="hostile.example",
            published_targets=set(registry()["targets"]),
        )
        self.clock.advance()
        valid_id = "00000000000000000000000004"
        valid_item = "https://valid.example/blyg/items/" + valid_id + ".json"
        self.fetcher.add(
            valid_item,
            relation_document("stub")
            | {
                "id": valid_id,
                "origin": "https://valid.example/blyg/",
                "page": "t/" + valid_id + "/",
            },
        )
        valid_row = self.queue.accept(
            InboundClaim(valid_item, TARGET_PAGE, "valid.example"),
            peer="198.51.100.3",
            source_group="valid.example",
            published_targets=set(registry()["targets"]),
        )

        self.assertEqual(self.worker().run(), 2)
        store = VerificationStore(self.root / "verified")
        self.assertEqual(
            (store.read(hostile_row["key"])["status"], store.read(hostile_row["key"])["error"]),
            ("failed", "invalid_document"),
        )
        self.assertEqual(store.read(valid_row["key"])["status"], "verified")

    def test_worker_atomically_refreshes_final_only_export(self):
        row = self.accept()
        export = self.root / "protected" / "export.json"
        worker = InboundVerifierWorker(
            self.queue,
            registry(),
            self.root / "verified",
            fetcher=self.fetcher,
            clock=self.clock,
            export_path=export,
        )
        self.assertEqual(worker.run(), 1)
        value = validate_verification_export(json.loads(export.read_text()))
        self.assertEqual([record["key"] for record in value["records"]], [row["key"]])
        self.assertEqual(export.stat().st_mode & 0o777, 0o600)

    def test_export_can_live_beside_records_across_repeated_runs(self):
        row = self.accept()
        verified = self.root / "verified"
        export = verified / "export.json"
        worker = InboundVerifierWorker(
            self.queue,
            registry(),
            verified,
            fetcher=self.fetcher,
            clock=self.clock,
            export_path=export,
        )
        self.assertEqual(worker.run(), 1)
        self.assertEqual(worker.run(), 0)
        value = validate_verification_export(json.loads(export.read_text()))
        self.assertEqual([record["key"] for record in value["records"]], [row["key"]])

    def test_unexpected_json_beside_records_fails_closed(self):
        verified = self.root / "verified"
        store = VerificationStore(verified)
        (verified / "surprise.json").write_text("{}")
        (verified / "surprise.json").chmod(0o600)
        with self.assertRaisesRegex(ValueError, "Unexpected inbound verification file"):
            store.entries()

    def test_verified_retention_tracks_bounded_intake_and_keeps_export_working(self):
        queue = InboundQueue(
            self.root / "retained-inbox",
            self.clock,
            {"stored_pairs": 2, "pending_pairs": 2, "terminal_retention_days": 1},
        )
        verified = self.root / "retained-verified"
        export = self.root / "retained-export.json"
        fetcher = Fetcher()
        keys = []
        for number, host in enumerate(("one.example", "two.example", "three.example"), 1):
            source_id = "0" * 25 + str(number)
            source_origin = f"https://{host}/blyg/"
            source_page = source_origin + "t/" + source_id + "/"
            source_item = source_origin + "items/" + source_id + ".json"
            fetcher.add(
                source_page,
                html_alternate(source_item),
                content_type="text/html",
            )
            fetcher.add(
                source_item,
                source_document(
                    id=source_id,
                    origin=source_origin,
                    page="t/" + source_id + "/",
                    stub_of={"origin": OWN, "id": TARGET_ID, "version": 1},
                ),
            )
            row = queue.accept(
                InboundClaim(source_page, TARGET_PAGE, host),
                peer=f"198.51.100.{number}",
                source_group=host,
                published_targets=set(registry()["targets"]),
            )
            keys.append(row["key"])
            worker = InboundVerifierWorker(
                queue,
                registry(),
                verified,
                fetcher=fetcher,
                clock=self.clock,
                export_path=export,
            )
            self.assertEqual(worker.run(), 1)
            self.clock.advance(86401)

        self.assertEqual(len(queue.entries()), 2)
        self.assertEqual(
            {row["key"] for row in VerificationStore(verified).entries()},
            set(keys[-2:]),
        )
        exported = validate_verification_export(json.loads(export.read_text()))
        self.assertEqual({row["key"] for row in exported["records"]}, set(keys[-2:]))

    def test_pruned_pair_can_reappear_without_blocking_mac_synchronization(self):
        queue = InboundQueue(
            self.root / "rollover-inbox",
            self.clock,
            {"stored_pairs": 1, "pending_pairs": 1, "terminal_retention_days": 1},
        )
        verified = self.root / "rollover-verified"
        export = self.root / "rollover-export.json"
        archive = InboundMentionArchive(self.root / "rollover-archive", self.clock)
        fetcher = Fetcher()

        def source(number, host, relation=True):
            source_id = "0" * 25 + str(number)
            origin = f"https://{host}/blyg/"
            page = origin + "t/" + source_id + "/"
            item = origin + "items/" + source_id + ".json"
            fetcher.add(page, html_alternate(item), content_type="text/html")
            changes = {
                "id": source_id,
                "origin": origin,
                "page": "t/" + source_id + "/",
            }
            if relation:
                changes["stub_of"] = {"origin": OWN, "id": TARGET_ID, "version": 1}
            fetcher.add(item, source_document(**changes))
            return page, host

        def receive_and_sync(pair):
            page, host = pair
            row = queue.accept(
                InboundClaim(page, TARGET_PAGE, host),
                peer="198.51.100.1",
                source_group=host,
                published_targets=set(registry()["targets"]),
            )
            worker = InboundVerifierWorker(
                queue,
                registry(),
                verified,
                fetcher=fetcher,
                clock=self.clock,
                export_path=export,
            )
            self.assertEqual(worker.run(), 1)
            archive.merge(json.loads(export.read_text(encoding="utf-8")))
            return row

        first = source(1, "one.example")
        first_row = receive_and_sync(first)
        self.assertEqual(archive.records()[0]["status"], "verified")

        self.clock.advance(86401)
        second = source(2, "two.example")
        receive_and_sync(second)
        self.assertNotIn(first_row["key"], {row["key"] for row in archive.records()})

        self.clock.advance(86401)
        receive_and_sync(first)
        restored = archive.records()[0]
        self.assertEqual((restored["key"], restored["receipt_count"], restored["status"]), (first_row["key"], 1, "verified"))

        self.clock.advance(86401)
        receive_and_sync(second)
        source(1, "one.example", relation=False)
        self.clock.advance(86401)
        receive_and_sync(first)
        removed = archive.records()[0]
        self.assertEqual((removed["key"], removed["receipt_count"], removed["status"]), (first_row["key"], 1, "failed"))

    def test_duplicate_updates_one_record_and_removed_relation_becomes_gone(self):
        row = self.accept()
        self.worker().run()
        self.clock.advance()
        self.accept()
        changed = source_document(version=4)
        self.fetcher.add(SOURCE_ITEM, changed)
        self.worker().run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["error"], record["receipt_count"]), ("gone", "no_relation", 2))
        self.assertEqual(len(VerificationStore(self.root / "verified").entries()), 1)

    def test_reverification_updates_source_version(self):
        row = self.accept()
        self.worker().run()
        self.clock.advance()
        self.accept()
        self.fetcher.add(SOURCE_ITEM, relation_document("stub") | {"version": 4})
        self.worker().run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["source_version"], record["receipt_count"]), ("verified", 4, 2))

    def test_duplicate_arriving_mid_fetch_stays_pending_and_is_reverified(self):
        row = self.accept()
        base = self.fetcher
        fired = {"value": False}

        def racing(url, **options):
            if not fired["value"]:
                fired["value"] = True
                self.accept()
            return base(url, **options)

        self.assertEqual(self.worker(racing).run(), 0)
        self.assertEqual(self.queue.entries()[0]["status"], "pending")
        self.assertEqual(self.worker().run(), 1)
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual(record["receipt_count"], 2)

    def test_restart_finalizes_crash_after_queue_transition(self):
        row = self.accept()
        worker = self.worker()
        worker.run()
        store = VerificationStore(self.root / "verified")
        record = store.read(row["key"])
        record["phase"] = "provisional"
        store.write(record)
        self.assertEqual(self.worker().run(), 0)
        self.assertEqual(store.read(row["key"])["phase"], "final")

    def test_restart_retries_crash_before_queue_transition(self):
        row = self.accept()
        with patch.object(self.queue, "complete", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.worker().run()
        store = VerificationStore(self.root / "verified")
        self.assertEqual(store.read(row["key"])["phase"], "provisional")
        self.assertEqual(self.queue.entries()[0]["status"], "pending")
        self.assertEqual(self.worker().run(), 1)
        self.assertEqual(store.read(row["key"])["phase"], "final")

    def test_record_write_failure_leaves_claim_pending_for_retry(self):
        row = self.accept()
        real_atomic = verifier_module._atomic

        def fail_record(path, data):
            if Path(path).parent == self.root / "verified":
                raise OSError("simulated full storage")
            return real_atomic(path, data)

        with patch.object(verifier_module, "_atomic", side_effect=fail_record):
            with self.assertRaises(OSError):
                self.worker().run()
        self.assertEqual(self.queue.entries()[0]["status"], "pending")
        self.assertIsNone(VerificationStore(self.root / "verified").read(row["key"]))
        self.assertEqual(self.worker().run(), 1)

    def test_failed_export_preserves_final_record_and_rebuilds_on_restart(self):
        row = self.accept()
        export = self.root / "protected" / "export.json"
        real_atomic = verifier_module._atomic

        def fail_export(path, data):
            if Path(path) == export:
                raise OSError("simulated full storage")
            return real_atomic(path, data)

        worker = InboundVerifierWorker(
            self.queue,
            registry(),
            self.root / "verified",
            fetcher=self.fetcher,
            clock=self.clock,
            export_path=export,
        )
        with patch.object(verifier_module, "_atomic", side_effect=fail_export):
            with self.assertRaises(OSError):
                worker.run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["phase"], self.queue.entries()[0]["status"]), ("final", "verified"))
        self.assertFalse(export.exists())
        restarted = InboundVerifierWorker(
            self.queue,
            registry(),
            self.root / "verified",
            fetcher=self.fetcher,
            clock=self.clock,
            export_path=export,
        )
        self.assertEqual(restarted.run(), 0)
        self.assertEqual(validate_verification_export(json.loads(export.read_text()))["records"][0]["key"], row["key"])

    def test_worker_overlap_is_single_flight(self):
        worker = self.worker()
        worker.lock_path.touch(mode=0o600)
        worker.lock_path.chmod(0o600)
        with worker.lock_path.open("r+") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(worker.run(), 0)

    def test_worker_lock_rejects_symlink_hardlink_and_unsafe_mode(self):
        for kind in ("symlink", "hardlink", "mode"):
            with self.subTest(kind=kind):
                root = self.root / kind
                worker = InboundVerifierWorker(
                    self.queue, registry(), root, fetcher=self.fetcher, clock=self.clock
                )
                outside = self.root / (kind + "-outside")
                outside.write_text("")
                outside.chmod(0o600)
                if kind == "symlink":
                    worker.lock_path.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, worker.lock_path)
                else:
                    worker.lock_path.write_text("")
                    worker.lock_path.chmod(0o644)
                with self.assertRaises((OSError, ValueError)):
                    worker.run()

    def test_unavailable_source_preserves_last_verified_relationship(self):
        row = self.accept()
        self.worker().run()
        self.clock.advance()
        self.accept()
        empty = Fetcher()
        self.worker(empty).run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["error"]), ("verified", None))
        self.assertEqual(record["attempt_error"], "fetch_failed")
        self.assertEqual(record["source_version"], 3)
        with self.assertRaises(ValueError):
            InboundVerifierWorker(self.queue, registry(), self.root / "other", batch=21)

    def test_verified_source_410_becomes_a_withdrawal(self):
        row = self.accept()
        self.worker().run()
        self.clock.advance()
        self.accept()

        def deleted(url, **_options):
            raise HTTPStatusError(410, url)

        self.assertEqual(self.worker(deleted).run(), 1)
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual(
            (record["status"], record["error"], record["mention_class"], self.queue.entries()[0]["status"]),
            ("gone", "source_gone", "response", "gone"),
        )

    def test_transient_retry_survives_restart_and_does_not_block_later_work(self):
        first = self.accept()
        empty = Fetcher()
        worker = InboundVerifierWorker(
            self.queue,
            registry(),
            self.root / "verified",
            fetcher=empty,
            clock=self.clock,
            batch=1,
        )
        self.assertEqual(worker.run(), 0)
        deferred = self.queue.entries()[0]
        self.assertEqual((deferred["status"], deferred["retry_count"]), ("pending", 1))
        self.assertEqual(deferred["retry_at"], int(self.clock()) + RETRY_DELAYS[0])

        valid_id = "00000000000000000000000004"
        valid_origin = "https://valid.example/blyg/"
        valid_page = valid_origin + "t/" + valid_id + "/"
        valid_item = valid_origin + "items/" + valid_id + ".json"
        self.fetcher.add(valid_page, html_alternate(valid_item), content_type="text/html")
        self.fetcher.add(
            valid_item,
            relation_document("stub")
            | {"id": valid_id, "origin": valid_origin, "page": "t/" + valid_id + "/"},
        )
        valid = self.queue.accept(
            InboundClaim(valid_page, TARGET_PAGE, "valid.example"),
            peer="198.51.100.2",
            source_group="valid.example",
            published_targets=set(registry()["targets"]),
        )

        restarted_queue = InboundQueue(self.queue.root, self.clock)
        restarted = InboundVerifierWorker(
            restarted_queue,
            registry(),
            self.root / "verified",
            fetcher=self.fetcher,
            clock=self.clock,
            batch=1,
        )
        self.assertEqual(restarted.run(), 1)
        self.assertEqual(VerificationStore(self.root / "verified").read(valid["key"])["status"], "verified")
        self.assertEqual(restarted_queue.entries("pending")[0]["key"], first["key"])

    def test_transient_retries_are_bounded_and_preserve_last_verified_result(self):
        row = self.accept()
        self.worker().run()
        self.clock.advance()
        self.accept()
        empty = Fetcher()

        for delay in RETRY_DELAYS:
            self.assertEqual(self.worker(empty).run(), 0)
            pending = self.queue.entries()[0]
            self.assertEqual(pending["status"], "pending")
            self.clock.advance(delay)
        self.assertEqual(self.worker(empty).run(), 1)
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["attempt_error"]), ("verified", "fetch_failed"))
        self.assertEqual(self.queue.entries()[0]["status"], "failed")

    def test_first_fetch_failure_remains_a_failure(self):
        row = self.accept()
        self.worker(Fetcher()).run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["error"], record["attempt_error"]), ("failed", "fetch_failed", "fetch_failed"))

    def test_success_after_transient_failure_clears_attempt_diagnostic(self):
        row = self.accept();self.worker().run();self.clock.advance();self.accept()
        self.worker(Fetcher()).run();self.clock.advance();self.accept();self.worker().run()
        record = VerificationStore(self.root / "verified").read(row["key"])
        self.assertEqual((record["status"], record["attempt_error"], record["receipt_count"]), ("verified", None, 3))

    def test_store_rejects_symlink_and_tampered_or_oversized_records(self):
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            VerificationStore(linked)
        row = self.accept()
        self.worker().run()
        path = self.root / "verified" / (row["key"] + ".json")
        value = json.loads(path.read_text())
        value["target"] = OWN + "t/00000000000000000000000003/"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        with self.assertRaises(ValueError):
            VerificationStore(self.root / "verified").read(row["key"])
        path.write_bytes(b"x" * (16 * 1024 + 1))
        path.chmod(0o600)
        with self.assertRaises(ValueError):
            VerificationStore(self.root / "verified").read(row["key"])


if __name__ == "__main__":
    unittest.main()
