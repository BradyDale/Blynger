import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core import Studio, new_page
from webmentions import OutboundQueue


class WebmentionPublicationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "site"
        self.root.mkdir()
        (self.root / "images").mkdir()
        (self.root / "index.html").write_text(new_page("Home", "<h3>Posts</h3>"))
        (self.root / "openers.html").write_text(new_page("Openers", "<h3>March 2</h3><p>Thought.</p>"))
        subprocess.run(["git", "init", "-b", "master"], cwd=self.root, capture_output=True, check=True)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "config", key, value], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "Initial"], cwd=self.root, check=True)
        self.remote = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], capture_output=True, check=True)
        self.data = self.base / "private"
        self.studio = Studio(self.root, self.data)
        self.studio.git("remote", "add", "website", str(self.remote))

    def tearDown(self):
        self.temporary.cleanup()

    def approve_and_push(self, title, target):
        draft = self.studio.create(title, stub_of={"url": target})
        review = self.studio.prepare()
        pending = self.studio.begin_publication(review["signature"])
        self.studio.push_publication_network(pending)
        return draft, pending

    def establish_baseline(self):
        baseline = self.studio.git("rev-parse", "HEAD")
        self.assertEqual(self.studio.state["webmention_baseline_commit"], baseline)
        self.assertEqual(self.studio.state["webmention_reconciliations"], [])
        self.assertFalse((self.data / "webmentions-outbox.json").exists())
        return baseline

    def outbox(self):
        return OutboundQueue(self.data, lambda: "2026-10-18T18:00:00Z")

    def test_first_publication_after_activation_queues_new_reference_from_exact_commit(self):
        self.establish_baseline()
        draft, pending = self.approve_and_push("New response", "https://approved.example/article")

        item_path = self.root / "blyg" / "items" / (self.studio.state["ids"][draft["name"]] + ".json")
        working = json.loads(item_path.read_text())
        working["stub_of"] = {"url": "https://unpublished.example/later-edit"}
        item_path.write_text(json.dumps(working))

        self.studio.finish_publication(pending)
        rows = self.outbox().entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_url"], "https://approved.example/article")
        self.assertNotIn("unpublished.example", json.dumps(rows))

    def test_restart_baselines_existing_history_without_backfilling_it(self):
        draft, pending = self.approve_and_push("Older response", "https://historical.example/article")
        self.studio.finish_publication(pending)
        (self.data / "webmentions-outbox.json").unlink()
        backup = self.data / "webmentions-outbox.backup.json"
        if backup.exists():
            backup.unlink()
        self.studio.state.pop("webmention_baseline_commit", None)
        self.studio.state["webmention_reconciled_commits"] = []
        self.studio.save_state()

        restarted = Studio(self.root, self.data)
        self.assertEqual(restarted.state["webmention_baseline_commit"], pending["commit"])
        unrelated = restarted.create("Unrelated new post")
        review = restarted.prepare()
        later = restarted.begin_publication(review["signature"])
        restarted.push_publication_network(later)
        restarted.finish_publication(later)
        rows = OutboundQueue(self.data).entries()
        self.assertFalse(any(row["target_url"] == "https://historical.example/article" for row in rows))
        self.assertIn(unrelated["name"], later["drafts"])

    def test_preserved_uncertain_publication_uses_its_verified_parent_as_baseline(self):
        self.studio.state.pop("webmention_baseline_commit", None)
        self.studio.save_state()
        _, pending = self.approve_and_push("Uncertain first response", "https://uncertain-first.example/article")
        # Simulate activation/restart after the hosted push response was lost.
        self.studio.state.pop("webmention_baseline_commit", None)
        self.studio.save_state()
        restarted = Studio(self.root, self.data)
        self.assertEqual(restarted.state["webmention_baseline_commit"], pending["base"])
        restarted.push_publication_network(pending)
        restarted.finish_publication(pending)
        self.assertEqual(
            [row["target_url"] for row in OutboundQueue(self.data).entries()],
            ["https://uncertain-first.example/article"],
        )

    def test_interrupted_old_silent_baseline_record_is_recovered_as_new_work(self):
        _, pending = self.approve_and_push("Interrupted first response", "https://interrupted.example/article")
        self.studio.state.pop("webmention_baseline_commit", None)
        self.studio.ensure_webmention_reconciliation(pending)
        self.assertTrue(self.studio.state["webmention_reconciliations"][0]["baseline"])

        restarted = Studio(self.root, self.data)
        self.assertEqual(restarted.state["webmention_baseline_commit"], pending["commit"])
        self.assertEqual(restarted.state["webmention_reconciliations"], [])
        self.assertEqual(
            [row["target_url"] for row in OutboundQueue(self.data).entries()],
            ["https://interrupted.example/article"],
        )

    def test_crash_after_record_preserves_pending_and_recovers_after_restart(self):
        self.establish_baseline()
        _, pending = self.approve_and_push("Recorded response", "https://recorded.example/article")

        def crash(label, details):
            if label == "after_reconciliation_record":
                raise SystemExit("crash after record")

        with self.assertRaisesRegex(SystemExit, "after record"):
            self.studio.finish_publication(pending, webmention_checkpoint=crash)
        self.assertIn("pending_publication", self.studio.state)
        self.assertEqual([row["commit"] for row in self.studio.state["webmention_reconciliations"]], [pending["commit"]])

        restarted = Studio(self.root, self.data)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)
        self.assertIn(pending["commit"], restarted.state["webmention_reconciled_commits"])
        restarted.finish_publication(pending)
        self.assertNotIn("pending_publication", restarted.state)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)

    def test_crash_after_finalization_recovers_without_pending_publication(self):
        self.establish_baseline()
        _, pending = self.approve_and_push("Finalized response", "https://finalized.example/article")

        def crash(label, details):
            if label == "after_publication_finalization":
                raise SystemExit("crash after finalization")

        with self.assertRaisesRegex(SystemExit, "after finalization"):
            self.studio.finish_publication(pending, webmention_checkpoint=crash)
        self.assertNotIn("pending_publication", self.studio.state)
        self.assertEqual(len(self.studio.state["webmention_reconciliations"]), 1)

        restarted = Studio(self.root, self.data)
        self.assertEqual(restarted.state["webmention_reconciliations"], [])
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)

    def test_crash_after_enqueue_replays_idempotently_and_cleans_record(self):
        self.establish_baseline()
        _, pending = self.approve_and_push("Accepted response", "https://accepted.example/article")

        def crash(label, details):
            if label == "after_webmention_enqueue":
                raise SystemExit("crash after enqueue")

        with self.assertRaisesRegex(SystemExit, "after enqueue"):
            self.studio.finish_publication(pending, webmention_checkpoint=crash)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)
        self.assertEqual(len(self.studio.state["webmention_reconciliations"]), 1)

        restarted = Studio(self.root, self.data)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)
        self.assertEqual(restarted.state["webmention_reconciliations"], [])

    def test_crash_before_enqueue_leaves_durable_work_for_restart(self):
        self.establish_baseline()
        _, pending = self.approve_and_push("Planned response", "https://planned.example/article")

        def crash(label, details):
            if label == "before_webmention_enqueue":
                raise SystemExit("crash before enqueue")

        with self.assertRaisesRegex(SystemExit, "before enqueue"):
            self.studio.finish_publication(pending, webmention_checkpoint=crash)
        self.assertNotIn("pending_publication", self.studio.state)
        self.assertEqual(len(self.studio.state["webmention_reconciliations"]), 1)
        self.assertFalse((self.data / "webmentions-outbox.json").exists())

        restarted = Studio(self.root, self.data)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)
        self.assertEqual(restarted.state["webmention_reconciliations"], [])

    def test_partial_enqueue_and_second_publication_both_reconcile(self):
        self.establish_baseline()
        self.studio.create("First queued response", stub_of={"url": "https://one.example/article"})
        _, first = self.approve_and_push("Second queued response", "https://two.example/article")

        class PartialQueue:
            def __init__(inner, root):
                inner.real = OutboundQueue(root)

            def enqueue(inner, events):
                inner.real.enqueue(events[:1])
                raise SystemExit("crash during enqueue")

        with self.assertRaisesRegex(SystemExit, "during enqueue"):
            self.studio.finish_publication(first, webmention_queue_factory=PartialQueue)
        self.assertEqual(len(self.studio.state["webmention_reconciliations"]), 1)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)

        restarted = Studio(self.root, self.data)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 2)
        self.assertEqual(restarted.state["webmention_reconciliations"], [])

        class UnavailableQueue:
            def __init__(inner, root):
                pass

            def enqueue(inner, events):
                raise ValueError("outbox temporarily unavailable")

        restarted.create("Later publication", stub_of={"url": "https://three.example/article"})
        review = restarted.prepare()
        later = restarted.begin_publication(review["signature"])
        restarted.push_publication_network(later)
        result = restarted.finish_publication(later, webmention_queue_factory=UnavailableQueue)
        self.assertIn("remain safely queued", result["message"])
        self.assertNotIn("pending_publication", restarted.state)
        self.assertEqual(len(restarted.state["webmention_reconciliations"]), 1)
        restarted.reconcile_webmentions()
        self.assertEqual(len(OutboundQueue(self.data).entries()), 3)
        self.assertEqual(restarted.state["webmention_reconciliations"], [])

    def test_lost_push_response_creates_no_record_until_host_is_confirmed(self):
        self.establish_baseline()
        _, pending = self.approve_and_push("Uncertain response", "https://uncertain.example/article")
        # The helper above already proved the commit reached the bare host. A
        # lost response leaves only pending_publication and no reconciliation.
        self.assertEqual(self.studio.state["webmention_reconciliations"], [])
        self.assertIn("pending_publication", self.studio.state)

        self.studio.push_publication_network(pending)
        self.studio.finish_publication(pending)
        self.assertEqual(len(OutboundQueue(self.data).entries()), 1)
        self.assertNotIn("pending_publication", self.studio.state)

    def test_unfinished_record_survives_a_second_publication(self):
        self.establish_baseline()

        class UnavailableQueue:
            def __init__(inner, root):
                pass

            def enqueue(inner, events):
                raise ValueError("outbox temporarily unavailable")

        _, first = self.approve_and_push("First delayed response", "https://first.example/article")
        first_result = self.studio.finish_publication(first, webmention_queue_factory=UnavailableQueue)
        self.assertIn("remain safely queued", first_result["message"])
        self.assertEqual(len(self.studio.state["webmention_reconciliations"]), 1)

        _, second = self.approve_and_push("Second delayed response", "https://second.example/article")
        second_result = self.studio.finish_publication(second, webmention_queue_factory=UnavailableQueue)
        self.assertIn("remain safely queued", second_result["message"])
        self.assertEqual(
            [record["commit"] for record in self.studio.state["webmention_reconciliations"]],
            [first["commit"], second["commit"]],
        )
        self.assertNotIn("pending_publication", self.studio.state)

        self.studio.reconcile_webmentions()
        rows = self.outbox().entries()
        self.assertEqual(
            {row["target_url"] for row in rows},
            {"https://first.example/article", "https://second.example/article"},
        )
        self.assertEqual(self.studio.state["webmention_reconciliations"], [])

    def test_withdrawn_stub_is_queued_once_from_exact_successive_commits(self):
        self.establish_baseline()
        draft, published = self.approve_and_push("Temporary response", "https://target.example/article")
        self.studio.finish_publication(published)
        self.assertEqual(len(self.outbox().entries()), 1)

        self.studio.delete_post(draft["name"])
        review = self.studio.prepare()
        withdrawn = self.studio.begin_publication(review["signature"])
        self.studio.push_publication_network(withdrawn)
        self.studio.finish_publication(withdrawn)

        rows = self.outbox().entries()
        self.assertEqual(len(rows), 2)
        withdrawals = [row for row in rows if row["withdrawal"]]
        self.assertEqual(len(withdrawals), 1)
        self.assertEqual(withdrawals[0]["target_url"], "https://target.example/article")


if __name__ == "__main__":
    unittest.main()
