import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import webmentions.inbound_registry as registry_module
from webmentions.inbound_endpoint import load_registry
from webmentions.inbound_registry import (
    RegistryArtifactStore,
    build_registry_artifact,
    installation_action,
    validate_registry_artifact,
)
from webmentions.inbound_registry_refresh import (
    DisabledRegistryRefreshWorker,
    RegistryRefreshWorker,
    SSHRegistryInstaller,
    open_registry_refresh_worker,
)
from core import Studio, new_page


OWN = "https://example.com/blyg/"
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
OTHER = "f" * 40


def document(iid="00000000000000000000000001"):
    return {
        "blyg": "0.4",
        "id": iid,
        "kind": "thread",
        "origin": OWN,
        "page": "t/" + iid + "/",
        "version": 1,
        "changelog": [],
    }


def artifact(commit=SECOND, previous=FIRST, documents=None):
    return build_registry_artifact(
        commit,
        previous,
        OWN,
        {"blyg": "0.4", "site": OWN, "item": "items/{id}.json"},
        documents or [document()],
    )


class RegistryArtifactTests(unittest.TestCase):
    def ancestry(self, older, newer):
        order = {FIRST: 1, SECOND: 2, THIRD: 3}
        return older in order and newer in order and order[older] <= order[newer]

    def test_artifact_binds_exact_commit_and_registry_digest(self):
        value = artifact()
        self.assertEqual(validate_registry_artifact(value), value)
        damaged = json.loads(json.dumps(value))
        damaged["registry"]["item_count"] = 0
        with self.assertRaises(ValueError):
            validate_registry_artifact(damaged)

    def test_ordering_is_idempotent_newer_wins_and_divergence_fails(self):
        first = artifact(FIRST, "0" * 40)
        second = artifact(SECOND, FIRST)
        third = artifact(THIRD, SECOND)
        self.assertEqual(installation_action(None, first, self.ancestry), "install")
        self.assertEqual(installation_action(second, second, self.ancestry), "already")
        self.assertEqual(installation_action(first, second, self.ancestry), "install")
        self.assertEqual(installation_action(third, second, self.ancestry), "superseded")
        with self.assertRaises(ValueError):
            installation_action(second, artifact(OTHER, FIRST), self.ancestry)

    def test_store_is_atomic_confirmed_and_preserves_newer_against_delayed_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RegistryArtifactStore(Path(temporary) / "registry")
            second = artifact(SECOND, FIRST)
            third = artifact(THIRD, SECOND)
            self.assertEqual(store.install(second, self.ancestry)["status"], "install")
            self.assertEqual(store.install(second, self.ancestry)["status"], "already")
            self.assertEqual(store.install(third, self.ancestry)["status"], "install")
            self.assertEqual(store.install(second, self.ancestry)["status"], "superseded")
            self.assertEqual(store.installed()["commit"], THIRD)
            self.assertEqual(store.current.stat().st_mode & 0o777, 0o640)
            self.assertEqual(store.backup.stat().st_mode & 0o777, 0o640)
            self.assertEqual(store.root.stat().st_mode & 0o777, 0o750)
            self.assertEqual(store.lock.stat().st_mode & 0o777, 0o600)

    def test_store_preserves_deployment_setgid_mode_when_present(self):
        self.assertEqual(registry_module._directory_mode(stat.S_IFDIR | 0o2750), 0o2750)
        self.assertEqual(registry_module._directory_mode(stat.S_IFDIR | 0o0750), 0o0750)

    def test_crash_before_replace_keeps_last_good_and_receiver_can_read_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RegistryArtifactStore(Path(temporary) / "registry")
            second = artifact(SECOND, FIRST)
            third = artifact(THIRD, SECOND)
            store.install(second, self.ancestry)

            def crash(label, _action):
                if label == "before_registry_install":
                    raise SystemExit("crash")

            with self.assertRaises(SystemExit):
                store.install(third, self.ancestry, crash)
            self.assertEqual(store.installed()["commit"], SECOND)
            self.assertEqual(load_registry(store.current, OWN), second["registry"])

    def test_current_write_failure_preserves_last_good_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RegistryArtifactStore(Path(temporary) / "registry")
            second = artifact(SECOND, FIRST)
            third = artifact(THIRD, SECOND)
            store.install(second, self.ancestry)
            real_atomic = registry_module._atomic

            def fail_current(path, data, mode=0o640):
                if Path(path) == store.current:
                    raise OSError("simulated full storage")
                return real_atomic(path, data, mode)

            with patch.object(registry_module, "_atomic", side_effect=fail_current):
                with self.assertRaises(OSError):
                    store.install(third, self.ancestry)
            self.assertEqual(store.installed()["commit"], SECOND)
            self.assertEqual(load_registry(store.current, OWN), second["registry"])

    def test_concurrent_registry_installs_cannot_roll_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RegistryArtifactStore(Path(temporary) / "registry")
            store.install(artifact(SECOND, FIRST), self.ancestry)
            incoming = (artifact(SECOND, FIRST), artifact(THIRD, SECOND))
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda value: store.install(value, self.ancestry), incoming))
            self.assertEqual(store.installed()["commit"], THIRD)

    def test_registry_lock_rejects_hardlink_and_unsafe_mode(self):
        for kind in ("hardlink", "mode"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                store = RegistryArtifactStore(Path(temporary) / "registry")
                if kind == "hardlink":
                    outside = Path(temporary) / "outside"
                    outside.write_text("")
                    outside.chmod(0o600)
                    os.link(outside, store.lock)
                else:
                    store.lock.write_text("")
                    store.lock.chmod(0o660)
                with self.assertRaises(ValueError):
                    store.install(artifact(), self.ancestry)

    def test_corrupt_current_registry_fails_closed_without_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RegistryArtifactStore(Path(temporary) / "registry")
            store.install(artifact(SECOND, FIRST), self.ancestry)
            store.install(artifact(THIRD, SECOND), self.ancestry)
            self.assertEqual(store._read(store.backup)["commit"], SECOND)
            store.current.write_text("{broken", encoding="utf-8")
            store.current.chmod(0o640)
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                store.install(artifact(SECOND, FIRST), self.ancestry)
            self.assertEqual(store._read(store.backup)["commit"], SECOND)


class RegistryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.base=Path(self.temporary.name)
        self.root=self.base/"site";self.root.mkdir();(self.root/"images").mkdir()
        (self.root/"index.html").write_text(new_page("Home","<h3>Posts</h3>"))
        (self.root/"openers.html").write_text(new_page("Openers","<h3>March 2</h3><p>Thought.</p>"))
        subprocess.run(["git","init","-b","master"],cwd=self.root,capture_output=True,check=True)
        subprocess.run(["git","config","user.name","Test"],cwd=self.root,check=True)
        subprocess.run(["git","config","user.email","test@example.invalid"],cwd=self.root,check=True)
        subprocess.run(["git","add","."],cwd=self.root,check=True)
        subprocess.run(["git","commit","-qm","Initial"],cwd=self.root,check=True)
        self.remote=self.base/"remote.git";subprocess.run(["git","init","--bare",str(self.remote)],check=True,capture_output=True)
        self.data=self.base/"private";self.studio=Studio(self.root,self.data)
        self.studio.git("remote","add","website",str(self.remote))

    def tearDown(self):self.temporary.cleanup()

    def publication(self,title):
        self.studio.create(title);review=self.studio.prepare();pending=self.studio.begin_publication(review["signature"])
        self.studio.push_publication_network(pending);return pending

    class Installer:
        def __init__(self):self.artifacts=[];self.fail=False
        def install(self,value):
            self.artifacts.append(value)
            if self.fail:raise ValueError("ssh unavailable")
            return {"status":"install","commit":value["commit"],"registry_sha256":value["registry_sha256"]}

    def test_success_records_exact_hosted_commit_before_finalization(self):
        pending=self.publication("Exact registry")
        def crash(label,_details):
            if label=="after_registry_reconciliation_record":raise SystemExit("crash")
        with self.assertRaises(SystemExit):self.studio.finish_publication(pending,webmention_checkpoint=crash)
        self.assertIn("pending_publication",self.studio.state)
        row=self.studio.state["inbound_registry_reconciliations"][0]
        self.assertEqual(row["commit"],pending["commit"])
        restarted=Studio(self.root,self.data);installer=self.Installer()
        restarted.reconcile_inbound_registry(installer)
        self.assertEqual(installer.artifacts[0]["commit"],pending["commit"])

    def test_exact_commit_registry_includes_pinned_document_and_page(self):
        draft=self.studio.create("Pinned registry");draft["pin_on_publish"]=True
        self.studio.save_draft(draft);review=self.studio.prepare()
        pending=self.studio.begin_publication(review["signature"])
        artifact=self.studio._commit_registry_artifact(pending["commit"],pending["base"])
        row=next(item for item in artifact["registry"]["items"] if item["pins"])
        pin=row["pin_targets"][0]
        self.assertEqual(pin["version"],1)
        self.assertEqual(pin["document"],self.studio.origin+"items/"+row["id"]+"/v1.json")
        self.assertEqual(pin["page"],self.studio.origin+"t/"+row["id"]+"/v1/")

    def test_existing_untracked_pin_is_restored_to_the_next_review(self):
        draft=self.studio.create("Legacy pin");draft["pin_on_publish"]=True
        self.studio.save_draft(draft);review=self.studio.prepare()
        pending=self.studio.begin_publication(review["signature"])
        self.studio.push_publication_network(pending);self.studio.finish_publication(pending)
        iid=self.studio.state["ids"][draft["name"]]
        pin=f"blyg/items/{iid}/v1.json"
        self.studio.git("rm","--cached","--",pin)
        self.studio.git("commit","-m","Simulate legacy missing pin")
        self.studio.git("push","website","master")
        self.studio.state["review_base"]=self.studio.git("rev-parse","HEAD")
        self.studio.save_state()
        self.assertTrue((self.root/pin).is_file())
        repaired=self.studio.prepare()
        self.assertIn(pin,[change["path"] for change in repaired["changes"]])

    def test_invalid_registry_projection_does_not_strand_hosted_publication(self):
        pending=self.publication("Registry projection warning")
        iid="0"*25+"7";pin_path=f"blyg/items/{iid}/v3.json"
        (self.root/pin_path).parent.mkdir(parents=True,exist_ok=True)
        (self.root/pin_path).write_text(json.dumps({"id":iid,"version":3,"pinned":True}))
        with patch.object(self.studio,"_commit_registry_artifact",side_effect=ValueError("missing declared pin")):
            result=self.studio.finish_publication(pending)
        self.assertNotIn("pending_publication",self.studio.state)
        self.assertIn("previous verified registry",result["message"])
        self.assertIn(pin_path,self.studio.state["pending"])
        self.assertTrue(self.studio.publication_status()["ready"])
        self.assertIn("missing declared pin",self.studio.state["inbound_registry_diagnostics"][-1])

    def test_unchanged_commit_needs_no_registry_refresh(self):
        pending=self.publication("Initial registry");self.studio.finish_publication(pending)
        first=list(self.studio.state["inbound_registry_reconciliations"])
        review=self.studio.prepare();unchanged=self.studio.begin_publication(review["signature"])
        self.assertEqual(unchanged["commit"],unchanged["base"])
        self.studio.push_publication_network(unchanged);self.studio.finish_publication(unchanged)
        self.assertEqual(self.studio.state["inbound_registry_reconciliations"],first)

    def test_uncertain_install_retries_idempotently_after_restart(self):
        pending=self.publication("Retry registry");self.studio.finish_publication(pending)
        installer=self.Installer();installer.fail=True
        worker=RegistryRefreshWorker(self.studio,installer)
        self.assertFalse(worker.run());self.assertEqual(len(self.studio.state["inbound_registry_reconciliations"]),1)
        restarted=Studio(self.root,self.data);installer.fail=False
        self.assertTrue(RegistryRefreshWorker(restarted,installer).run())
        self.assertEqual(restarted.state["inbound_registry_reconciliations"],[])
        self.assertIn(pending["commit"],restarted.state["inbound_registry_reconciled_commits"])

    def test_lost_confirmation_after_remote_install_replays_safely(self):
        pending=self.publication("Installed before crash");self.studio.finish_publication(pending)
        class StatefulInstaller:
            def __init__(inner):inner.installed=None
            def install(inner,value):
                status="already" if inner.installed==value else "install"
                inner.installed=value
                return {"status":status,"commit":value["commit"],"registry_sha256":value["registry_sha256"]}
        installer=StatefulInstaller()
        def crash(label,_details):
            if label=="after_registry_refresh":raise SystemExit("lost confirmation")
        with self.assertRaises(SystemExit):self.studio.reconcile_inbound_registry(installer,crash)
        self.assertEqual(len(self.studio.state["inbound_registry_reconciliations"]),1)
        restarted=Studio(self.root,self.data)
        restarted.reconcile_inbound_registry(installer)
        self.assertEqual(restarted.state["inbound_registry_reconciliations"],[])
        self.assertEqual(installer.installed["commit"],pending["commit"])

    def test_two_publications_remain_ordered_and_single_flight(self):
        first=self.publication("First registry");self.studio.finish_publication(first)
        second=self.publication("Second registry");self.studio.finish_publication(second)
        self.assertEqual([r["commit"] for r in self.studio.state["inbound_registry_reconciliations"]],[first["commit"],second["commit"]])
        installer=self.Installer();worker=RegistryRefreshWorker(self.studio,installer)
        entered=threading.Event();release=threading.Event();original=installer.install
        def delayed(value):entered.set();release.wait(3);return original(value)
        installer.install=delayed;self.assertTrue(worker.wake());self.assertTrue(entered.wait(1))
        self.assertFalse(worker.wake());release.set();self.assertTrue(worker.join(3))
        self.assertEqual([a["commit"] for a in installer.artifacts],[first["commit"],second["commit"]])

    def test_ssh_installer_is_fixed_noninteractive_and_requires_confirmation(self):
        seen={}
        def runner(args,**options):
            seen.update(args=args,options=options)
            value=json.loads(options["input"])
            receipt={"status":"install","commit":value["commit"],"registry_sha256":value["registry_sha256"]}
            return type("Result",(),{"returncode":0,"stdout":json.dumps(receipt).encode()})()
        exact=artifact();installer=SSHRegistryInstaller(hostname="ssh.example.net",username="owner_site",ssh_key="/private/key",runner=runner)
        self.assertEqual(installer.install(exact)["commit"],SECOND)
        self.assertIn("BatchMode=yes",seen["args"]);self.assertEqual(seen["args"][-1],"/home/private/blynger-webmentions/bin/install-target-registry")
        self.assertNotIn(SECOND," ".join(seen["args"]))

    def test_factory_disables_invalid_configuration_without_network_work(self):
        worker=open_registry_refresh_worker(self.studio,{"publishing":{"hostname":"","ssh_user":""}})
        self.assertIsInstance(worker,DisabledRegistryRefreshWorker)
        self.assertFalse(worker.wake())

    def test_factory_uses_publishing_connection_and_expands_key(self):
        worker=open_registry_refresh_worker(
            self.studio,
            {"publishing":{"hostname":"ssh.example.net","ssh_user":"owner_site","ssh_key":"~/key"}},
        )
        self.assertIsInstance(worker,RegistryRefreshWorker)
        self.assertEqual(worker.installer.ssh_key,str(Path("~/key").expanduser()))


if __name__ == "__main__":
    unittest.main()
