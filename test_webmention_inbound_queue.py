import fcntl
import multiprocessing
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import webmentions.inbound_queue as inbound_module
from webmentions.inbound_contract import InboundClaim, InboundContractError
from webmentions.inbound_queue import InboundQueue, InboundStoreError


OWN = "https://example.com/blyg/"
TARGET = OWN + "t/00000000000000000000000002/"


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def claim(number=1, host=None, target=TARGET):
    host = host or f"writer{number}.example"
    source = f"https://{host}/blyg/t/{number:026d}/"
    return InboundClaim(source, target, host)


def process_accept(arguments):
    root, number = arguments
    value = claim(number)
    queue = InboundQueue(root, lambda: 1_800_000_000)
    queue.accept(
        value,
        peer=f"198.51.100.{number}",
        source_group=value.source_host,
        published_targets={TARGET},
    )


class InboundQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.queue = InboundQueue(self.root, self.clock)

    def tearDown(self):
        self.temporary.cleanup()

    def accept(self, value=None, *, peer="198.51.100.1", group=None, targets=None):
        value = value or claim()
        return self.queue.accept(
            value,
            peer=peer,
            source_group=group or value.source_host,
            published_targets=targets or {TARGET},
        )

    def test_accept_is_durable_private_and_survives_reload(self):
        row = self.accept()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["received_count"], 1)
        reloaded = InboundQueue(self.root, self.clock)
        self.assertEqual(reloaded.entries(), [row])
        for path in (self.queue.file, self.queue.lock_file):
            self.assertEqual(path.stat().st_mode & 0o007, 0)
            self.assertEqual(path.stat().st_mode & 0o110, 0)
        self.assertNotIn("198.51.100.1", self.queue.file.read_text(encoding="utf-8"))

    def test_queue_state_and_locks_have_exact_group_boundary_modes(self):
        self.accept()
        self.clock.advance(1)
        self.accept()
        self.assertEqual(self.queue.file.stat().st_mode & 0o777, 0o660)
        self.assertEqual(self.queue.backup.stat().st_mode & 0o777, 0o660)
        self.assertEqual(self.queue.lock_file.stat().st_mode & 0o777, 0o660)

    def test_existing_shared_lock_is_validated_without_chmod(self):
        root = self.root / "other-identity"
        root.mkdir()
        lock = root / "inbound-state.lock"
        lock.touch(mode=0o660)
        lock.chmod(0o660)
        with patch.object(inbound_module.os, "chmod", side_effect=PermissionError):
            InboundQueue(root, self.clock)

    def test_duplicate_refreshes_one_pair_and_terminal_resend_reopens_it(self):
        first = self.accept()
        self.clock.advance(1)
        second = self.accept()
        self.assertEqual(len(self.queue.entries()), 1)
        self.assertEqual(second["received_count"], 2)
        self.assertEqual(second["first_received_at"], first["first_received_at"])
        self.queue.set_status(first["key"], "verified")
        self.clock.advance(1)
        reopened = self.accept()
        self.assertEqual(reopened["status"], "pending")
        self.assertEqual(reopened["received_count"], 3)

    def test_ipv6_source_and_peer_survive_reload(self):
        value = InboundClaim(
            "https://[2606:4700:4700::1111]/post",
            TARGET,
            "2606:4700:4700::1111",
        )
        row = self.queue.accept(
            value,
            peer="2001:4860:4860::8888",
            source_group="2606:4700:4700::1111",
            published_targets={TARGET},
        )
        self.assertEqual(InboundQueue(self.root, self.clock).entries(), [row])

    def test_unknown_target_is_rate_charged_but_never_queued(self):
        queue = InboundQueue(self.root / "probe", self.clock, {"global_per_minute": 1})
        unknown = claim(target=OWN + "t/00000000000000000000000003/")
        with self.assertRaises(InboundContractError) as caught:
            queue.accept(
                unknown,
                peer="198.51.100.1",
                source_group=unknown.source_host,
                published_targets={TARGET},
            )
        self.assertEqual(caught.exception.code, "unknown_target")
        self.assertEqual(queue.entries(), [])
        with self.assertRaises(InboundContractError) as limited:
            queue.accept(
                claim(),
                peer="198.51.100.2",
                source_group="writer1.example",
                published_targets={TARGET},
            )
        self.assertEqual(limited.exception.status, 429)

    def test_peer_host_group_and_global_limits_are_independent(self):
        cases = (
            (
                "ip_per_minute",
                (claim(1), "198.51.100.1", "writer1.example"),
                (claim(2), "198.51.100.1", "writer2.example"),
            ),
            (
                "ip_per_hour",
                (claim(1), "198.51.100.1", "writer1.example"),
                (claim(2), "198.51.100.1", "writer2.example"),
            ),
            (
                "source_host_per_minute",
                (claim(1, "same.example"), "198.51.100.1", "same.example"),
                (claim(2, "same.example"), "198.51.100.2", "same.example"),
            ),
            (
                "source_host_per_hour",
                (claim(1, "same.example"), "198.51.100.1", "same.example"),
                (claim(2, "same.example"), "198.51.100.2", "same.example"),
            ),
            (
                "source_group_per_hour",
                (claim(1, "a.group.example"), "198.51.100.1", "group.example"),
                (claim(2, "b.group.example"), "198.51.100.2", "group.example"),
            ),
            (
                "source_group_per_day",
                (claim(1, "a.group.example"), "198.51.100.1", "group.example"),
                (claim(2, "b.group.example"), "198.51.100.2", "group.example"),
            ),
            (
                "global_per_minute",
                (claim(1), "198.51.100.1", "writer1.example"),
                (claim(2), "198.51.100.2", "writer2.example"),
            ),
            (
                "global_per_hour",
                (claim(1), "198.51.100.1", "writer1.example"),
                (claim(2), "198.51.100.2", "writer2.example"),
            ),
            (
                "global_per_day",
                (claim(1), "198.51.100.1", "writer1.example"),
                (claim(2), "198.51.100.2", "writer2.example"),
            ),
        )
        for name, first, second in cases:
            with self.subTest(name=name):
                queue = InboundQueue(self.root / name, self.clock, {name: 1})
                queue.accept(first[0], peer=first[1], source_group=first[2], published_targets={TARGET})
                with self.assertRaises(InboundContractError) as caught:
                    queue.accept(second[0], peer=second[1], source_group=second[2], published_targets={TARGET})
                self.assertEqual((caught.exception.status, caught.exception.code), (429, "rate_limited"))

    def test_rolling_rate_window_expires(self):
        queue = InboundQueue(self.root / "rolling", self.clock, {"global_per_minute": 1})
        queue.accept(claim(1), peer="198.51.100.1", source_group="writer1.example", published_targets={TARGET})
        self.clock.advance(60)
        queue.accept(claim(2), peer="198.51.100.2", source_group="writer2.example", published_targets={TARGET})
        self.assertEqual(len(queue.entries()), 2)

    def test_pending_cap_rejects_without_removing_work(self):
        queue = InboundQueue(self.root / "pending", self.clock, {"pending_pairs": 2})
        for number in (1, 2):
            queue.accept(
                claim(number),
                peer=f"198.51.100.{number}",
                source_group=f"writer{number}.example",
                published_targets={TARGET},
            )
        with self.assertRaises(InboundContractError) as caught:
            queue.accept(
                claim(3),
                peer="198.51.100.3",
                source_group="writer3.example",
                published_targets={TARGET},
            )
        self.assertEqual((caught.exception.status, caught.exception.code), (503, "receiver_busy"))
        self.assertEqual(len(queue.entries("pending")), 2)

    def test_total_cap_prunes_only_old_terminal_records(self):
        queue = InboundQueue(
            self.root / "retention",
            self.clock,
            {"stored_pairs": 2, "pending_pairs": 2, "terminal_retention_days": 1},
        )
        first = queue.accept(
            claim(1), peer="198.51.100.1", source_group="writer1.example", published_targets={TARGET}
        )
        queue.set_status(first["key"], "verified")
        second = queue.accept(
            claim(2), peer="198.51.100.2", source_group="writer2.example", published_targets={TARGET}
        )
        queue.set_status(second["key"], "gone")
        with self.assertRaises(InboundContractError):
            queue.accept(
                claim(3), peer="198.51.100.3", source_group="writer3.example", published_targets={TARGET}
            )
        self.clock.advance(86401)
        third = queue.accept(
            claim(3), peer="198.51.100.3", source_group="writer3.example", published_targets={TARGET}
        )
        keys = {row["key"] for row in queue.entries()}
        self.assertEqual(len(keys), 2)
        self.assertNotIn(first["key"], keys)
        self.assertIn(third["key"], keys)

    def test_damaged_main_recovers_backup_and_preserves_damage(self):
        first = self.accept(claim(1))
        self.clock.advance(1)
        self.accept(claim(2), peer="198.51.100.2")
        self.queue.file.write_text("{broken", encoding="utf-8")
        recovered = InboundQueue(self.root, self.clock)
        self.assertEqual([row["key"] for row in recovered.entries()], [first["key"]])
        self.assertTrue(recovered.recovery_notice)
        self.assertIsNotNone(recovered.damaged_file)
        self.assertTrue(recovered.damaged_file.exists())

    def test_damage_without_backup_fails_closed_and_symlink_is_not_read(self):
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "inbound-state.json").write_text("{broken", encoding="utf-8")
        (broken / "inbound-state.json").chmod(0o660)
        with self.assertRaises(InboundStoreError):
            InboundQueue(broken, self.clock)
        self.assertTrue(any(broken.glob("inbound-state.damaged-*.json")))
        with self.assertRaises(InboundStoreError):
            InboundQueue(broken, self.clock)

        linked = self.root / "linked"
        linked.mkdir()
        outside = self.root / "outside.json"
        outside.write_text('{"private":"untouched"}', encoding="utf-8")
        (linked / "inbound-state.json").symlink_to(outside)
        with self.assertRaises(InboundStoreError):
            InboundQueue(linked, self.clock)
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"private":"untouched"}')

        hardlinked = self.root / "hardlinked"
        hardlinked.mkdir()
        lock_target = self.root / "lock-target"
        lock_target.write_text("untouched", encoding="utf-8")
        before = lock_target.stat().st_mode
        (hardlinked / "inbound-state.lock").hardlink_to(lock_target)
        with self.assertRaises(InboundStoreError):
            InboundQueue(hardlinked, self.clock)
        self.assertEqual(lock_target.read_text(encoding="utf-8"), "untouched")
        self.assertEqual(lock_target.stat().st_mode, before)

    def test_missing_main_recovers_verified_backup(self):
        first = self.accept(claim(1))
        self.clock.advance(1)
        self.accept(claim(2), peer="198.51.100.2")
        self.queue.file.unlink()
        recovered = InboundQueue(self.root, self.clock)
        self.assertEqual([row["key"] for row in recovered.entries()], [first["key"]])
        self.assertTrue(recovered.recovery_notice)

    def test_concurrent_accepts_do_not_lose_pairs(self):
        def add(number):
            value = claim(number)
            return self.queue.accept(
                value,
                peer=f"198.51.100.{number}",
                source_group=value.source_host,
                published_targets={TARGET},
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, range(1, 21)))
        self.assertEqual(len(self.queue.entries()), 20)

    def test_separate_processes_do_not_lose_pairs(self):
        root = self.root / "processes"
        context = multiprocessing.get_context("fork")
        processes = [context.Process(target=process_accept, args=((root, number),)) for number in range(1, 9)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len(InboundQueue(root, self.clock).entries()), 8)

    def test_failure_between_backup_and_main_keeps_last_committed_state(self):
        first = self.accept(claim(1))
        real_atomic = inbound_module._atomic

        def fail_main(path, text, mode=0o660):
            if Path(path).name == "inbound-state.json":
                raise OSError("simulated interruption")
            return real_atomic(path, text, mode)

        with patch.object(inbound_module, "_atomic", fail_main):
            with self.assertRaises(InboundContractError):
                self.accept(claim(2), peer="198.51.100.2")
        reloaded = InboundQueue(self.root, self.clock)
        self.assertEqual([row["key"] for row in reloaded.entries()], [first["key"]])

    def test_uncertain_response_after_main_write_retries_without_duplicate_pair(self):
        real_atomic = inbound_module._atomic

        def fail_after_main(path, text, mode=0o660):
            real_atomic(path, text, mode)
            if Path(path).name == "inbound-state.json":
                raise OSError("simulated lost completion")

        with patch.object(inbound_module, "_atomic", fail_after_main):
            with self.assertRaises(InboundContractError):
                self.accept()
        reloaded = InboundQueue(self.root, self.clock)
        self.assertEqual(len(reloaded.entries()), 1)
        retried = reloaded.accept(
            claim(),
            peer="198.51.100.1",
            source_group="writer1.example",
            published_targets={TARGET},
        )
        self.assertEqual(len(reloaded.entries()), 1)
        self.assertEqual(retried["received_count"], 2)

    def test_lock_timeout_is_a_bounded_503(self):
        queue = InboundQueue(self.root / "locked", self.clock, {"lock_seconds": 0.05})
        with queue.lock_file.open("a+") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(InboundContractError) as caught:
                queue.entries()
            self.assertEqual((caught.exception.status, caught.exception.code), (503, "receiver_busy"))

    def test_state_size_limit_fails_closed_before_acceptance(self):
        queue = InboundQueue(self.root / "small", self.clock, {"state_bytes": 200})
        with self.assertRaises(InboundContractError) as caught:
            queue.accept(
                claim(), peer="198.51.100.1", source_group="writer1.example", published_targets={TARGET}
            )
        self.assertEqual((caught.exception.status, caught.exception.code), (503, "receiver_busy"))
        self.assertEqual(queue.entries(), [])

    def test_invalid_peer_group_status_and_limit_override_fail_before_mutation(self):
        with self.assertRaises(ValueError):
            self.accept(peer="not an address")
        with self.assertRaises(ValueError):
            self.accept(group="elsewhere.example")
        with self.assertRaises(KeyError):
            self.queue.set_status("missing", "verified")
        with self.assertRaises(ValueError):
            InboundQueue(self.root / "raised", self.clock, {"pending_pairs": 201})
        self.assertEqual(self.queue.entries(), [])


if __name__ == "__main__":
    unittest.main()
