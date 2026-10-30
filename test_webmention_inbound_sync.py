import copy
import hashlib
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import Handler

import webmentions.inbound_sync as sync_module
import webmentions.inbound_verifier as verifier_module
from webmentions.inbound_sync import (
    InboundMentionArchive,
    InboundSyncError,
    InboundSyncService,
    InboundSynchronizer,
    REMOTE_COMMAND,
    REMOTE_EXPORT,
    SSHExportReader,
    DisabledInboundSyncService,
    open_inbound_sync_service,
    _run_ssh,
)
from webmentions.inbound_activity import classify_activity, semantic_fingerprint
from webmentions.inbound_verifier import (
    EXPORT_LIMIT,
    VerificationStore,
    validate_verification_export,
    write_verification_export,
)


SOURCE = "https://writer.example/blyg/t/00000000000000000000000001/"
TARGET = "https://example.com/blyg/t/00000000000000000000000002/"


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self):
        self.value += 1


def key(source=SOURCE, target=TARGET):
    return hashlib.sha256((source + "\0" + target).encode()).hexdigest()


def record(*, count=1, version=3, status="verified", phase="final", source=SOURCE, target=TARGET):
    verified = status == "verified"
    return {
        "schema": 1,
        "key": key(source, target),
        "source": source,
        "target": target,
        "status": status,
        "phase": phase,
        "receipt_count": count,
        "relation": "stub" if verified else None,
        "source_item_id": "00000000000000000000000001" if verified else None,
        "source_origin": "https://writer.example/blyg/" if verified else None,
        "source_version": version if verified else None,
        "source_kind": "thread" if verified else None,
        "source_author": {"name": "Writer"} if verified else None,
        "source_page": SOURCE if verified else None,
        "verified_at": 1_800_000_000 + count,
        "error": None if verified else "no_relation",
    }


def modern_record(**options):
    value = record(**options)
    value.update(schema=2, checked_at=value["verified_at"], attempt_error=value["error"])
    return value


def notice_record(**options):
    value = modern_record(**options)
    value.update(schema=3, relation="link", mention_class="notice")
    return value


def encoded_export(root, rows, clock=None):
    store = VerificationStore(Path(root) / "verified")
    for row in rows:
        store.write(row)
    path = Path(root) / "export.json"
    value = write_verification_export(path, store, clock or Clock())
    return path.read_bytes(), value


class ExportTests(unittest.TestCase):
    def test_export_is_private_checksummed_sorted_and_final_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            other_source = "https://another.example/blyg/t/00000000000000000000000003/"
            first = record(source=other_source)
            second = record()
            unfinished = record(source="https://pending.example/post", phase="provisional")
            payload, value = encoded_export(temporary, [second, unfinished, first])
            self.assertEqual([row["key"] for row in value["records"]], sorted((first["key"], second["key"])))
            self.assertNotIn(unfinished["key"], payload.decode())
            self.assertEqual(validate_verification_export(json.loads(payload)), value)
            self.assertEqual((Path(temporary) / "export.json").stat().st_mode & 0o777, 0o600)

    def test_tampered_checksum_and_unfinished_record_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, value = encoded_export(temporary, [record()])
            damaged = copy.deepcopy(value)
            damaged["records"][0]["source_version"] = 99
            with self.assertRaises(ValueError):
                validate_verification_export(damaged)
            unfinished = copy.deepcopy(value)
            unfinished["records"][0]["phase"] = "provisional"
            raw = json.dumps(unfinished["records"], sort_keys=True, separators=(",", ":")).encode()
            unfinished["records_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                validate_verification_export(unfinished)

    def test_legacy_record_and_export_are_upgraded_without_losing_checksum_compatibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy = record()
            raw = json.dumps([legacy], sort_keys=True, separators=(",", ":")).encode()
            value = {"schema": 1, "generated_at": 1, "records": [legacy], "records_sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}
            upgraded = validate_verification_export(value)
            self.assertEqual(upgraded["records"][0]["schema"], 3)
            self.assertEqual(upgraded["records"][0]["checked_at"], legacy["verified_at"])

    def test_failed_export_replace_preserves_last_good_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VerificationStore(root / "verified")
            store.write(record())
            path = root / "export.json"
            write_verification_export(path, store, Clock())
            original = path.read_bytes()
            store.write(record(count=2, version=4))

            def fail(_path, _data):
                raise OSError("simulated full storage")

            with patch.object(verifier_module, "_atomic", side_effect=fail):
                with self.assertRaises(OSError):
                    write_verification_export(path, store, Clock())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(
                validate_verification_export(json.loads(original))["records"][0]["receipt_count"],
                1,
            )

    def test_damaged_existing_export_is_not_overwritten_with_a_lower_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VerificationStore(root / "verified")
            store.write(record())
            path = root / "export.json"
            path.write_text("{broken", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                write_verification_export(path, store, Clock())
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


class SSHReaderTests(unittest.TestCase):
    def test_command_is_fixed_noninteractive_and_contains_no_mention_values(self):
        seen = {}

        def runner(args, limit, timeout):
            seen.update(args=args, limit=limit, timeout=timeout)
            return b"{}"

        reader = SSHExportReader(
            hostname="ssh.example",
            username="example_example",
            ssh_key="~/keys/example",
            runner=runner,
        )
        self.assertEqual(reader.read(), b"{}")
        command = reader.command()
        self.assertEqual(command[-1], REMOTE_COMMAND)
        self.assertIn(REMOTE_EXPORT, command[-1])
        self.assertIn("BatchMode=yes", command)
        self.assertIn("PasswordAuthentication=no", command)
        self.assertIn("KbdInteractiveAuthentication=no", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertNotIn(SOURCE, " ".join(command))
        self.assertEqual((seen["limit"], seen["timeout"]), (EXPORT_LIMIT, 20))

    def test_hostname_and_username_cannot_be_command_options(self):
        for options in (
            {"hostname": "-oProxyCommand=bad", "username": "owner"},
            {"hostname": "host.example", "username": "-bad"},
            {"hostname": "host;bad", "username": "owner"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                SSHExportReader(**options)

    def test_process_reader_enforces_output_and_time_bounds(self):
        with self.assertRaises(InboundSyncError) as oversized:
            _run_ssh([sys.executable, "-c", "import sys;sys.stdout.write('x'*20)"], limit=10, timeout=2)
        self.assertEqual(oversized.exception.code, "oversized")
        with self.assertRaises(InboundSyncError) as timed:
            _run_ssh([sys.executable, "-c", "import time;time.sleep(2)"], limit=10, timeout=0.05)
        self.assertEqual(timed.exception.code, "timeout")
        with self.assertRaises(InboundSyncError) as failed:
            _run_ssh([sys.executable, "-c", "raise SystemExit(1)"], limit=10, timeout=2)
        self.assertEqual(failed.exception.code, "unavailable")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.archive = InboundMentionArchive(self.root / "archive", self.clock)

    def tearDown(self):
        self.temporary.cleanup()

    def export(self, rows):
        payload, value = encoded_export(self.root / ("remote-" + str(self.clock.value)), rows, self.clock)
        return payload, value

    def test_merge_is_idempotent_updates_records_and_removes_remote_omissions(self):
        _, first = self.export([record()])
        state = self.archive.merge(first)
        self.assertEqual(len(state["records"]), 1)
        before = self.archive.file.read_bytes()
        self.clock.advance()
        self.archive.merge(first)
        self.assertEqual(self.archive.records()[0]["receipt_count"], 1)
        other_source = "https://another.example/blyg/t/00000000000000000000000003/"
        _, second = self.export([record(source=other_source)])
        self.clock.advance()
        self.archive.merge(second)
        self.assertEqual(len(self.archive.records()), 1)
        self.assertEqual(self.archive.records()[0]["source"], other_source)
        self.assertNotEqual(before, self.archive.file.read_bytes())
        _, updated = self.export([record(count=2, version=4)])
        self.clock.advance()
        self.archive.merge(updated)
        self.assertEqual(self.archive.records()[0]["source_version"], 4)

    def test_export_revisions_are_monotonic_and_replays_fail_closed(self):
        store = VerificationStore(self.root / "revision-store")
        store.write(record())
        path = self.root / "revision-export.json"
        first = write_verification_export(path, store, self.clock)
        second = write_verification_export(path, store, self.clock)
        self.assertEqual(second["generated_at"], first["generated_at"] + 1)
        self.archive.merge(second)
        with self.assertRaises(InboundSyncError) as caught:
            self.archive.merge(first)
        self.assertEqual(caught.exception.code, "conflict")

    def test_same_revision_must_be_exactly_idempotent(self):
        _, first = self.export([record()])
        self.archive.merge(first)
        self.archive.merge(first)
        changed = copy.deepcopy(first)
        changed["records"] = []
        changed["records_sha256"] = "sha256:" + hashlib.sha256(b"[]").hexdigest()
        with self.assertRaises(InboundSyncError) as caught:
            self.archive.merge(changed)
        self.assertEqual(caught.exception.code, "conflict")

    def test_rollback_or_same_receipt_conflict_preserves_last_good_records(self):
        _, current = self.export([record(count=2, version=4)])
        self.archive.merge(current)
        original = self.archive.records()
        for incoming in (record(count=1), record(count=2, version=9)):
            _, value = self.export([incoming])
            with self.subTest(incoming=incoming["source_version"]), self.assertRaises(InboundSyncError) as caught:
                self.archive.merge(value)
            self.assertEqual(caught.exception.code, "conflict")
            self.assertEqual(self.archive.records(), original)

    def test_failure_diagnostic_never_erases_local_records(self):
        _, value = self.export([record()])
        self.archive.merge(value)
        self.clock.advance()
        state = self.archive.failure("unavailable")
        self.assertEqual(len(state["records"]), 1)
        self.assertEqual(state["last_error"], "unavailable")
        reopened = InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(len(reopened.records()), 1)

    def test_missing_or_damaged_main_recovers_last_good_backup(self):
        _, first = self.export([record()])
        self.archive.merge(first)
        self.archive.file.unlink()
        recovered = InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(len(recovered.records()), 1)
        self.assertTrue(recovered.recovery_notice)
        recovered.file.write_text("{broken", encoding="utf-8")
        recovered.file.chmod(0o600)
        again = InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(len(again.records()), 1)
        self.assertIsNotNone(again.damaged_file)

    def test_corrupt_main_and_backup_fail_closed(self):
        _, first = self.export([record()])
        self.archive.merge(first)
        for path in (self.archive.file, self.archive.backup):
            path.write_text("{broken", encoding="utf-8")
            path.chmod(0o600)
        with self.assertRaises(InboundSyncError) as caught:
            InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(caught.exception.code, "local_store")

    def test_main_write_failure_preserves_last_good_archive(self):
        _, first = self.export([record()])
        self.archive.merge(first)
        original = self.archive.file.read_bytes()
        _, updated = self.export([record(count=2, version=4)])
        real_atomic = sync_module._atomic

        def fail_main(path, data):
            if Path(path) == self.archive.file:
                raise OSError("simulated full storage")
            return real_atomic(path, data)

        with patch.object(sync_module, "_atomic", side_effect=fail_main):
            with self.assertRaises(OSError):
                self.archive.merge(updated)
        self.assertEqual(self.archive.file.read_bytes(), original)
        reopened = InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(reopened.records()[0]["receipt_count"], 1)

    def test_lost_confirmation_after_main_write_is_idempotent(self):
        _, first = self.export([record()])
        self.archive.merge(first)
        _, updated = self.export([record(count=2, version=4)])
        real_atomic = sync_module._atomic

        def fail_after_main(path, data):
            real_atomic(path, data)
            if Path(path) == self.archive.file:
                raise OSError("simulated lost completion")

        with patch.object(sync_module, "_atomic", side_effect=fail_after_main):
            with self.assertRaises(OSError):
                self.archive.merge(updated)
        reopened = InboundMentionArchive(self.root / "archive", self.clock)
        self.assertEqual(reopened.records()[0]["receipt_count"], 2)
        reopened.merge(updated)
        self.assertEqual(reopened.records()[0]["source_version"], 4)

    def test_archive_refuses_symlink_directory_and_unsafe_record_file(self):
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            InboundMentionArchive(linked, self.clock)
        file_link_root = self.root / "file-link"
        file_link_root.mkdir()
        (file_link_root / "inbound-mentions.json").symlink_to(self.root / "missing.json")
        with self.assertRaises(InboundSyncError):
            InboundMentionArchive(file_link_root, self.clock)
        _, value = self.export([record()])
        self.archive.merge(value)
        self.archive.file.chmod(0o644)
        with self.assertRaises(InboundSyncError):
            InboundMentionArchive(self.root / "archive", self.clock)

    def test_archive_files_are_owner_only(self):
        _, value = self.export([record()])
        self.archive.merge(value)
        self.assertEqual(self.archive.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.archive.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.archive.backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.archive.lock_file.stat().st_mode & 0o777, 0o600)

    def test_concurrent_archives_merge_without_losing_records(self):
        other_source = "https://another.example/blyg/t/00000000000000000000000003/"
        _, snapshot = self.export([record(), record(source=other_source)])
        other = InboundMentionArchive(self.root / "archive", self.clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda archive: archive.merge(snapshot), (self.archive, other)))
        self.assertEqual(len(InboundMentionArchive(self.root / "archive", self.clock).records()), 2)

    def test_semantic_activity_ignores_duplicate_receipts_and_check_diagnostics(self):
        _, first = self.export([modern_record()]);self.archive.merge(first)
        activity=self.archive.activities();self.assertEqual((activity[0]["kind"],activity[0]["unread"]),("new",True))
        self.assertTrue(self.archive.mark_read(key()))
        duplicate=modern_record(count=2)
        duplicate["verified_at"]=modern_record()["verified_at"]
        duplicate["checked_at"]+=20
        duplicate["attempt_error"]="fetch_failed"
        _, repeated=self.export([duplicate]);self.archive.merge(repeated)
        self.assertEqual(self.archive.activities()[0]["unread"],False)
        self.assertEqual(self.archive.activities()[0]["kind"],"new")

    def test_update_and_withdrawal_each_create_one_unread_activity(self):
        _, first=self.export([modern_record()]);self.archive.merge(first);self.archive.mark_read(key())
        _, updated=self.export([modern_record(count=2,version=4)]);self.archive.merge(updated)
        activity=self.archive.activities()[0];self.assertEqual((activity["kind"],activity["unread"]),("update",True))
        self.archive.mark_read(key())
        _, gone=self.export([modern_record(count=3,status="gone")]);self.archive.merge(gone)
        activity=self.archive.activities()[0];self.assertEqual((activity["kind"],activity["unread"]),("withdrawal",True))

    def test_activity_read_state_survives_restart_and_first_failure_is_not_activity(self):
        _, failed=self.export([modern_record(status="failed")]);self.archive.merge(failed)
        self.assertEqual(self.archive.activities(),[])
        _, verified=self.export([modern_record(count=2)]);self.archive.merge(verified);self.archive.mark_read(key())
        reopened=InboundMentionArchive(self.root/"archive",self.clock)
        self.assertEqual(len(reopened.activities()),1);self.assertFalse(reopened.activities()[0]["unread"])

    def test_acknowledgement_is_bound_to_exact_semantic_fingerprint(self):
        _, first=self.export([modern_record()]);self.archive.merge(first)
        old=self.archive.activities()[0]["fingerprint"]
        self.assertTrue(self.archive.mark_read(key(),old))
        _, updated=self.export([modern_record(count=2,version=4)]);self.archive.merge(updated)
        current=self.archive.activities()[0]
        self.assertNotEqual(current["fingerprint"],old);self.assertTrue(current["unread"])
        self.assertFalse(self.archive.mark_read(key(),old))
        reopened=InboundMentionArchive(self.root/"archive",self.clock)
        self.assertTrue(reopened.activities()[0]["unread"])

    def test_acknowledgement_survives_archive_recovery(self):
        _, first=self.export([modern_record()]);self.archive.merge(first);self.archive.mark_read(key())
        self.archive.file.write_text("{broken")
        self.archive.file.chmod(0o600)
        reopened=InboundMentionArchive(self.root/"archive",self.clock)
        self.assertFalse(reopened.activities()[0]["unread"])

    def test_schema_two_read_state_migrates_to_fingerprint_ledger(self):
        _, first=self.export([modern_record()]);self.archive.merge(first);self.archive.mark_read(key())
        state=self.archive.snapshot();state["schema"]=2;state.pop("acknowledged")
        for activity in state["activities"].values():activity["unread"]=False
        self.archive.file.write_text(json.dumps(state,sort_keys=True,separators=(",",":"))+"\n")
        self.archive.file.chmod(0o600)
        reopened=InboundMentionArchive(self.root/"archive",self.clock)
        self.assertEqual(reopened.snapshot()["schema"],3)
        self.assertFalse(reopened.activities()[0]["unread"])

    def test_semantic_fingerprint_excludes_transport_fields(self):
        first=modern_record();duplicate=modern_record(count=9)
        duplicate["checked_at"]+=99;duplicate["attempt_error"]="fetch_failed"
        self.assertEqual(semantic_fingerprint(first),semantic_fingerprint(duplicate))
        self.assertIsNone(classify_activity(first,duplicate))
        self.assertEqual(classify_activity(first,modern_record(count=2,version=4)),"update")


class SynchronizerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.archive = InboundMentionArchive(self.root / "archive", self.clock)
        self.payload, _ = encoded_export(self.root / "remote", [record()], self.clock)

    def tearDown(self):
        self.temporary.cleanup()

    def test_success_and_repetition_are_idempotent(self):
        reader = type("Reader", (), {"read": lambda _self: self.payload})()
        sync = InboundSynchronizer(reader, self.archive)
        self.assertEqual(sync.sync(), {"ok": True, "records": 1, "error": None})
        self.assertEqual(sync.sync(), {"ok": True, "records": 1, "error": None})

    def test_offline_truncated_and_oversized_reads_preserve_last_good(self):
        good = type("Reader", (), {"read": lambda _self: self.payload})()
        InboundSynchronizer(good, self.archive).sync()

        class Offline:
            def read(self):
                raise InboundSyncError("unavailable")

        cases = (
            (Offline(), "unavailable"),
            (type("Reader", (), {"read": lambda _self: b'{"schema":1'})(), "invalid_export"),
            (type("Reader", (), {"read": lambda _self: b"x" * (EXPORT_LIMIT + 1)})(), "oversized"),
        )
        for reader, code in cases:
            with self.subTest(code=code):
                result = InboundSynchronizer(reader, self.archive).sync()
                self.assertEqual((result["ok"], result["error"], result["records"]), (False, code, 1))
                self.assertEqual(len(self.archive.records()), 1)


class BackgroundServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = InboundMentionArchive(self.root / "archive", Clock())

    def tearDown(self):
        self.temporary.cleanup()

    def wait_for(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail("Background synchronization did not reach the expected state.")

    def test_disabled_service_never_starts_network_work(self):
        service = open_inbound_sync_service(self.root, {"webmentions": {"inbound_sync_enabled": False}})
        self.assertIsInstance(service, DisabledInboundSyncService)
        self.assertFalse(service.start())
        self.assertFalse(service.wake())
        self.assertEqual(service.status()["record_count"], 0)

    def test_delayed_start_manual_wake_and_stop(self):
        calls = []
        synchronizer = type("Sync", (), {"sync": lambda _self: calls.append(time.monotonic()) or {"ok": True, "records": 0, "error": None}})()
        service = InboundSyncService(synchronizer, self.archive, startup_delay=60, interval=60)
        self.assertTrue(service.start())
        time.sleep(.03)
        self.assertEqual(calls, [])
        started = time.monotonic()
        self.assertTrue(service.wake())
        self.assertLess(time.monotonic() - started, .1)
        self.wait_for(lambda: len(calls) == 1)
        self.assertTrue(service.status()["running"])
        self.assertTrue(service.stop())
        self.assertFalse(service.status()["running"])

    def test_repeated_wakes_never_overlap(self):
        gate = threading.Event()
        entered = threading.Event()
        state = {"active": 0, "maximum": 0, "calls": 0}

        class BlockingSync:
            def sync(_self):
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                state["calls"] += 1
                entered.set()
                gate.wait(1)
                state["active"] -= 1
                return {"ok": True, "records": 0, "error": None}

        service = InboundSyncService(BlockingSync(), self.archive, startup_delay=60, interval=60)
        service.start();service.wake();self.assertTrue(entered.wait(1))
        for _ in range(8):
            service.wake()
        gate.set()
        self.wait_for(lambda: state["calls"] >= 2)
        service.stop()
        self.assertEqual(state["maximum"], 1)
        self.assertLessEqual(state["calls"], 2)

    def test_status_reports_archive_activity_without_triggering_sync(self):
        payload, value = encoded_export(self.root / "remote", [modern_record()], Clock())
        self.archive.merge(value)
        service = InboundSyncService(type("Sync", (), {"sync": lambda _self: None})(), self.archive)
        status = service.status()
        self.assertEqual((status["record_count"], status["activity_count"], status["unread_count"]), (1, 1, 1))
        self.assertTrue(status["last_success_at"].endswith("Z"))
        self.assertEqual(status["activities"][0]["kind"], "new")
        self.assertNotIn("record", status["activities"][0])
        self.assertEqual(status["activities"][0]["source_author"], "Writer")

    def test_status_holds_notices_out_of_response_and_badge_counts(self):
        payload, value = encoded_export(self.root / "remote", [notice_record()], Clock())
        self.archive.merge(value)
        service = InboundSyncService(type("Sync", (), {"sync": lambda _self: None})(), self.archive)
        status = service.status()
        self.assertEqual((status["activity_count"], status["unread_count"]), (0, 0))
        self.assertEqual((status["notice_count"], status["unread_notice_count"]), (1, 1))
        self.assertEqual(status["activities"][0]["mention_class"], "notice")

    def test_status_distinguishes_not_synchronized_unavailable_empty_and_stale(self):
        service = InboundSyncService(type("Sync", (), {"sync": lambda _self: None})(), self.archive)
        self.assertEqual(service.status()["availability"], "not_synchronized")
        self.archive.failure("unavailable")
        self.assertEqual(service.status()["availability"], "unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            old_archive=InboundMentionArchive(Path(temporary)/"archive",Clock(1))
            _,empty=encoded_export(Path(temporary)/"remote",[],Clock(1));old_archive.merge(empty)
            old_service=InboundSyncService(type("Sync", (), {"sync": lambda _self: None})(),old_archive,interval=1)
            self.assertEqual(old_service.status()["availability"],"stale")
            self.assertEqual(old_service.status()["activity_count"],0)

    def test_token_protected_status_and_nonblocking_refresh_api(self):
        class Service:
            def __init__(self):
                self.wakes = 0

            def wake(self):
                self.wakes += 1
                return True

            def status(self):
                return {"enabled": True, "running": True, "syncing": False, "record_count": 3, "activities": [{"target": TARGET}]}

            def mark_read(self, key_value, fingerprint):
                return key_value == "0" * 64 and fingerprint.startswith("sha256:")

        service = Service()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.token = "inbound-token"
        server.inbound_webmentions = service
        server.studio = type("Studio", (), {"state": {"published": {TARGET.rstrip('/').split('/')[-1]: {"title": "Local title"}}}, "item_title": staticmethod(lambda document: document["title"])})()
        server.lock = threading.RLock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/api/inbound-webmentions-status", headers={"X-Blynger-Token": "inbound-token"})
            response = connection.getresponse();payload = json.loads(response.read());connection.close()
            self.assertEqual((response.status, payload["record_count"]), (200, 3))
            self.assertEqual(payload["activities"][0]["title"], "Local title")

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            body = "{}"
            connection.request("POST", "/api/inbound-webmentions-refresh", body=body, headers={"Content-Length": str(len(body)), "X-Blynger-Token": "inbound-token"})
            response = connection.getresponse();payload = json.loads(response.read());connection.close()
            self.assertEqual((response.status, payload["refresh_requested"], service.wakes), (200, True, 1))

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            body = json.dumps({"key": "0" * 64, "fingerprint": "sha256:" + "0" * 64})
            connection.request("POST", "/api/inbound-webmentions-read", body=body, headers={"Content-Length": str(len(body)), "X-Blynger-Token": "inbound-token"})
            response = connection.getresponse();payload = json.loads(response.read());connection.close()
            self.assertEqual((response.status, payload["acknowledged"]), (200, True))

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/api/inbound-webmentions-status")
            response = connection.getresponse();response.read();connection.close()
            self.assertEqual(response.status, 403)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == "__main__":
    unittest.main()
