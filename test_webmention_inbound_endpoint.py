import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

import webmentions.inbound_endpoint as endpoint_module

from webmentions.inbound_endpoint import PublicSuffixList, WriterSlot
from webmentions.inbound_queue import InboundQueue
from webmentions.inbound_targets import build_target_registry, validate_target_registry, write_target_registry


OWN = "https://example.com/blyg/"
IID = "00000000000000000000000002"
PAGE = OWN + "t/" + IID + "/"
ITEM = OWN + "items/" + IID + ".json"
SOURCE = "https://writer.example/blyg/t/00000000000000000000000001/"


def document(kind="thread", page="t/" + IID + "/"):
    return {
        "blyg": "0.3",
        "id": IID,
        "kind": kind,
        "origin": OWN,
        "page": page,
        "version": 2,
        "changelog": [
            {"version": 1, "pinned": True},
            {"version": 2},
        ],
    }


class TargetRegistryTests(unittest.TestCase):
    def test_current_page_and_document_are_the_only_targets(self):
        registry = build_target_registry(OWN, {"blyg": "0.3", "site": OWN}, [document()])
        self.assertEqual(registry["targets"], [ITEM, PAGE])
        self.assertEqual(registry["schema"], 2)
        self.assertEqual(registry["items"], [{"id": IID, "kind": "thread", "page": PAGE, "document": ITEM, "pins": [1]}])
        self.assertEqual(validate_target_registry(registry, OWN), registry)
        self.assertNotIn("https://example.com/97.html", registry["targets"])
        self.assertNotIn(OWN + "items/" + IID + "/v1.json", registry["targets"])

    def test_withdrawn_items_remain_targets_and_04_template_is_expanded(self):
        withdrawn = build_target_registry(OWN, {"blyg": "0.3", "site": OWN}, [document("withdrawn")])
        self.assertEqual(withdrawn["targets"], [ITEM, PAGE])
        custom = build_target_registry(
            OWN,
            {"blyg": "0.4", "site": OWN, "item": "api/items/{id}?format=blyg"},
            [document()],
        )
        self.assertIn(OWN + "api/items/" + IID + "?format=blyg", custom["targets"])

    def test_legacy_same_site_url_remains_a_target_without_rewriting_item(self):
        legacy = {**document(), "blyg": "0.3", "url": "https://example.com/67.html"}
        legacy.pop("page")
        registry = build_target_registry(OWN, {"blyg": "0.3", "site": OWN}, [legacy])
        self.assertEqual(registry["targets"], ["https://example.com/67.html", ITEM])
        self.assertEqual(validate_target_registry(registry, OWN), registry)

    def test_rejects_foreign_duplicate_or_malformed_items_and_templates(self):
        manifest = {"blyg": "0.3", "site": OWN}
        cases = (
            [document(), document()],
            [{**document(), "origin": "https://elsewhere.example/blyg/"}],
            [{**document(), "kind": "mystery"}],
            [{**document(), "page": "https://elsewhere.example/post"}],
            [{**document(), "page": "", "url": "https://elsewhere.example/post"}],
        )
        for documents in cases:
            with self.subTest(documents=documents), self.assertRaises(ValueError):
                build_target_registry(OWN, manifest, documents)
        with self.assertRaises(ValueError):
            build_target_registry(OWN, {**manifest, "item": "api/{id}.json"}, [document()])
        with self.assertRaises(ValueError):
            build_target_registry(OWN, {"blyg": "0.4", "site": OWN, "item": "api/{other}"}, [document()])

    def test_atomic_registry_is_read_only_to_the_web_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "targets.json"
            registry = build_target_registry(OWN, {"blyg": "0.3", "site": OWN}, [document()])
            write_target_registry(path, registry)
            self.assertEqual(json.loads(path.read_text()), registry)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)


class EndpointFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = self.root / "inbox"
        self.queue.mkdir(mode=0o770)
        self.registry = self.root / "targets.json"
        self.suffixes = self.root / "public_suffix_list.dat"
        self.config = self.root / "receiver.json"
        write_target_registry(
            self.registry,
            build_target_registry(OWN, {"blyg": "0.3", "site": OWN}, [document()]),
        )
        self.suffixes.write_text("// VERSION: fixture-2026-10-19\ncom\nexample\nco.uk\n*.ck\n!www.ck\n", encoding="utf-8")
        self.suffixes.chmod(0o644)
        self.write_config("open")

    def tearDown(self):
        self.temporary.cleanup()

    def test_existing_writer_lock_is_validated_without_chmod(self):
        lock = self.queue / "inbound-writer-0.lock"
        lock.touch(mode=0o660)
        lock.chmod(0o660)
        with patch.object(endpoint_module.os, "chmod", side_effect=PermissionError):
            with WriterSlot(self.queue, 1):
                pass

    def write_config(self, mode, domains=(), limits=None):
        value = {
            "schema": 1,
            "origin": OWN,
            "policy": {"mode": mode, "domains": list(domains)},
            "registry": str(self.registry),
            "queue": str(self.queue),
            "public_suffixes": str(self.suffixes),
        }
        if limits is not None:
            value["limits"] = limits
        self.config.write_text(json.dumps(value), encoding="utf-8")
        self.config.chmod(0o640)

    def call(self, *, source=SOURCE, target=PAGE, method="POST", content_type="application/x-www-form-urlencoded", raw=None, peer="198.51.100.1", length=None):
        body = raw if raw is not None else urlencode({"source": source, "target": target}).encode()
        environment = os.environ.copy()
        environment.update(
            {
                "BLYNGER_WEBMENTION_CONFIG": str(self.config),
                "REQUEST_METHOD": method,
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(len(body) if length is None else length),
                "REMOTE_ADDR": peer,
            }
        )
        completed = subprocess.run(
            [sys.executable, "-m", "webmentions.inbound_endpoint"],
            input=body,
            cwd=Path(__file__).parent,
            env=environment,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        text = completed.stdout.decode("utf-8")
        head, _, response = text.partition("\r\n\r\n")
        headers = {}
        lines = head.split("\r\n")
        status = int(lines[0].split()[1])
        for line in lines[1:]:
            name, value = line.split(":", 1)
            headers[name] = value.strip()
        return status, headers, response

    def rows(self):
        return InboundQueue(self.queue).entries() if (self.queue / "inbound-state.json").exists() else []

    def test_real_cgi_process_accepts_durably_without_fetching_source(self):
        status, headers, body = self.call(source="https://unreachable.invalid/post")
        self.assertEqual(status, 202)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("verified", body.lower())
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["source"], "https://unreachable.invalid/post")

    def test_page_and_item_targets_accept_but_unknown_alias_does_not(self):
        self.assertEqual(self.call(target=ITEM)[0], 202)
        self.assertEqual(self.call(target="https://example.com/97.html", peer="198.51.100.2")[0], 400)
        self.assertEqual(len(self.rows()), 1)

    def test_duplicate_refreshes_one_pair(self):
        self.assertEqual(self.call()[0], 202)
        self.assertEqual(self.call()[0], 202)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["received_count"], 2)

    def test_policy_suppression_is_indistinguishable_and_leaves_no_state(self):
        self.write_config("denylist", ("writer.example",))
        first = self.call(target="not a URL")
        self.assertEqual(first[0], 202)
        self.assertEqual(first[2], "Webmention accepted for processing.\n")
        self.assertFalse((self.queue / "inbound-state.json").exists())
        self.write_config("allowlist", ("friend.example",))
        self.assertEqual(self.call(target="not a URL")[0], 202)
        self.assertFalse((self.queue / "inbound-state.json").exists())

    def test_off_method_media_size_and_malformed_fail_generically(self):
        self.write_config("off")
        status, headers, _ = self.call(method="GET", raw=b"", length=999999)
        self.assertEqual((status, headers["Retry-After"]), (503, "3600"))
        self.write_config("open")
        status, headers, _ = self.call(method="GET", raw=b"", length=999999)
        self.assertEqual((status, headers["Allow"]), (405, "POST"))
        self.assertEqual(self.call(content_type="application/json")[0], 415)
        self.assertEqual(self.call(raw=b"x", length=8193)[0], 413)
        self.assertEqual(self.call(raw=b"source=%zz&target=x")[0], 400)
        self.assertFalse((self.queue / "inbound-state.json").exists())

    def test_invalid_target_is_charged_before_lookup(self):
        self.write_config("open", limits={"global_per_minute": 1})
        self.assertEqual(self.call(target=OWN + "t/00000000000000000000000003/")[0], 400)
        self.assertEqual(self.call(peer="198.51.100.2")[0], 429)
        self.assertEqual(self.rows(), [])

    def test_bad_configuration_and_registry_fail_closed_without_details(self):
        self.config.chmod(0o666)
        status, _, body = self.call()
        self.assertEqual(status, 503)
        self.assertNotIn(str(self.config), body)
        self.config.chmod(0o640)
        self.registry.write_text("{broken", encoding="utf-8")
        self.registry.chmod(0o640)
        status, _, body = self.call()
        self.assertEqual(status, 503)
        self.assertNotIn("broken", body)

    def test_queue_directory_cannot_be_redirected(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.queue.rmdir()
        self.queue.symlink_to(outside, target_is_directory=True)
        status, _, _ = self.call()
        self.assertEqual(status, 503)
        self.assertEqual(list(outside.iterdir()), [])

    def test_public_suffix_grouping_and_writer_slots(self):
        suffixes = PublicSuffixList(self.suffixes)
        self.assertEqual(suffixes.registrable("a.writer.co.uk"), "writer.co.uk")
        self.assertEqual(suffixes.registrable("a.b.ck"), "a.b.ck")
        self.assertEqual(suffixes.registrable("a.www.ck"), "www.ck")
        held = [WriterSlot(self.queue, 4) for _ in range(4)]
        for slot in held:
            slot.__enter__()
        try:
            with self.assertRaises(Exception):
                WriterSlot(self.queue, 4).__enter__()
        finally:
            for slot in reversed(held):
                slot.__exit__(None, None, None)

    def test_query_strings_are_stored_for_verification_but_never_reflected(self):
        source = SOURCE + "?private=token"
        status, _, response = self.call(source=source)
        self.assertEqual(status, 202)
        self.assertNotIn("token", response)
        self.assertEqual(self.rows()[0]["source"], source)


if __name__ == "__main__":
    unittest.main()
