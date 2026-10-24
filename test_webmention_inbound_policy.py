import json
import tempfile
import unittest
from pathlib import Path

from webmentions.inbound_policy import (
    SSHInboundPolicyManager,
    update_receiver_policy,
)


class PolicyFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = self.root / "inbox"; self.queue.mkdir(); self.queue.chmod(0o770)
        self.registry = self.root / "targets.json"; self.registry.write_text("{}")
        self.suffixes = self.root / "suffixes.dat"; self.suffixes.write_text("// VERSION: test\ncom\n")
        self.config = self.root / "receiver.json"
        self.config.write_text(json.dumps({
            "schema": 1,
            "origin": "https://example.com/blyg/",
            "policy": {"mode": "off", "domains": []},
            "registry": str(self.registry),
            "queue": str(self.queue),
            "public_suffixes": str(self.suffixes),
            "limits": {},
        }))
        self.config.chmod(0o600)

    def tearDown(self): self.temporary.cleanup()

    def test_status_set_and_block_preserve_fixed_configuration(self):
        self.assertEqual(update_receiver_policy(self.config,{"schema":1,"action":"status"})["mode"],"off")
        result=update_receiver_policy(self.config,{"schema":1,"action":"set","mode":"denylist","domains":["Writer.Example."]})
        self.assertEqual(result,{"mode":"denylist","domains":["writer.example"]})
        result=update_receiver_policy(self.config,{"schema":1,"action":"block","domain":"Other.Example"})
        self.assertEqual(result,{"mode":"denylist","domains":["other.example","writer.example"]})
        saved=json.loads(self.config.read_text())
        self.assertEqual(saved["queue"],str(self.queue));self.assertEqual(saved["policy"],result)

    def test_block_requires_denylist_and_rejects_extra_fields(self):
        with self.assertRaisesRegex(ValueError,"denylist"):
            update_receiver_policy(self.config,{"schema":1,"action":"block","domain":"writer.example"})
        with self.assertRaises(ValueError):
            update_receiver_policy(self.config,{"schema":1,"action":"status","path":"/tmp/elsewhere"})


class SSHPolicyTests(unittest.TestCase):
    def test_fixed_command_and_verified_response(self):
        seen={}
        def runner(args,**options):
            seen.update(args=args,options=options)
            return type("Result",(),{"returncode":0,"stdout":b'{"mode":"denylist","domains":["writer.example"]}'})()
        manager=SSHInboundPolicyManager(hostname="ssh.example.net",username="owner_site",runner=runner)
        self.assertEqual(manager.block("https://writer.example/blyg/"),{"mode":"denylist","domains":["writer.example"]})
        self.assertEqual(seen["args"][-1],"/home/private/blynger-webmentions/bin/manage-receiver-policy")
        self.assertNotIn("writer.example"," ".join(seen["args"]))
        self.assertEqual(json.loads(seen["options"]["input"])["domain"],"writer.example")


if __name__ == "__main__": unittest.main()
