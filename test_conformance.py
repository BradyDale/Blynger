"""Mutation controls for the independent final-artifact checker."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from conformance import ConformanceError, validate_surface
from conformance_fixture import generate


class ConformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "site"
        generate(self.root / "blyg")
        self.origin = "https://blynger.example/blyg/"

    def tearDown(self):
        self.tmp.cleanup()

    def validate(self, overlay=None):
        return validate_surface(self.root, self.origin, overlay)

    def item(self, predicate=lambda doc: True):
        for path in (self.root / "blyg/items").glob("*.json"):
            if path.name == "index.json":
                continue
            doc = json.loads(path.read_text())
            if predicate(doc):
                return path, doc
        raise AssertionError("fixture has no matching item")

    def test_real_lifecycle_fixture_has_pin_withdrawal_thread_and_generation(self):
        report = self.validate()
        self.assertEqual(report.items, 3)
        self.assertEqual(report.pins, 1)
        docs = [json.loads(path.read_text()) for path in (self.root / "blyg/items").glob("*.json") if path.name != "index.json"]
        self.assertTrue(any(doc["kind"] == "withdrawn" for doc in docs))
        self.assertTrue(any(doc.get("transclusions") for doc in docs))
        self.assertTrue(any(doc.get("generated") for doc in docs))

    def test_hash_mutation_is_rejected(self):
        path, doc = self.item(lambda value: value["kind"] != "withdrawn")
        doc["content_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ConformanceError, "content_hash"):
            self.validate({str(path.relative_to(self.root)): json.dumps(doc)})

    def test_relative_html_address_is_rejected(self):
        path, doc = self.item(lambda value: value["kind"] != "withdrawn")
        doc["content_html"] += '<p><a href="relative">bad</a></p>'
        with self.assertRaisesRegex(ConformanceError, "relative href"):
            self.validate({str(path.relative_to(self.root)): json.dumps(doc)})

    def test_transclusion_version_disagreement_is_rejected(self):
        path, doc = self.item(lambda value: bool(value.get("transclusions")))
        doc["transclusions"][0]["version"] += 1
        with self.assertRaisesRegex(ConformanceError, "wrappers do not match"):
            self.validate({str(path.relative_to(self.root)): json.dumps(doc)})

    def test_missing_promised_pin_is_rejected(self):
        path, doc = self.item(lambda value: any(row.get("pinned") for row in value["changelog"]))
        version = next(row["version"] for row in doc["changelog"] if row.get("pinned"))
        pin = self.root / f"blyg/items/{doc['id']}/v{version}.json"
        pin.unlink()
        with self.assertRaisesRegex(ConformanceError, "is missing"):
            self.validate()

    def test_private_editor_metadata_is_rejected(self):
        path, doc = self.item(lambda value: value["kind"] != "withdrawn")
        doc["content_html"] += '<blockquote data-blynger-quote="private">x</blockquote>'
        with self.assertRaisesRegex(ConformanceError, "private editor metadata"):
            self.validate({str(path.relative_to(self.root)): json.dumps(doc)})


if __name__ == "__main__":
    unittest.main()
