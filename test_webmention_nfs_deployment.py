import ast
import runpy
import stat
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from webmentions.inbound_registry_refresh import REMOTE_COMMAND


ROOT = Path(__file__).parent
DEPLOYMENT = ROOT / "deployment" / "nfs"


class NFSDeploymentTests(unittest.TestCase):
    def test_python_helpers_compile_and_use_only_fixed_host_paths(self):
        registry = (DEPLOYMENT / "install-target-registry").read_text()
        verifier = (DEPLOYMENT / "run-inbound-verifier").read_text()
        ast.parse(registry)
        ast.parse(verifier)
        self.assertIn('"--git-dir=/home/public/.git"', registry)
        self.assertIn('"/home/protected/webmentions/config"', registry)
        self.assertIn('"/home/protected/webmentions/inbox"', verifier)
        self.assertIn('"/home/protected/webmentions/verified"', verifier)
        self.assertNotIn("shell=True", registry + verifier)
        self.assertIn('require_directory("/home/protected", 0o1770)', registry)
        self.assertIn('require_directory("/home/protected", 0o1770)', verifier)
        self.assertIn('require_directory("/home/private/blynger-webmentions/current", 0o700)', registry)
        self.assertIn('require_directory("/home/private/blynger-webmentions/current", 0o700)', verifier)
        self.assertEqual(
            REMOTE_COMMAND,
            "/home/private/blynger-webmentions/bin/install-target-registry",
        )
        self.assertNotIn("/home/protected/webmentions/bin", registry + verifier)
        self.assertNotIn("sys.stdout", verifier)
        self.assertIn("worker.run()", verifier)

    def test_documented_boundary_separates_owner_code_from_web_writable_data(self):
        deployment = (DEPLOYMENT / "README.md").read_text()
        self.assertIn("/home/protected", deployment)
        self.assertIn("`1770`", deployment)
        self.assertIn("/home/private/blynger-webmentions", deployment)
        self.assertIn("reader_network.py", deployment)

    def test_owner_helpers_fail_closed_when_the_sticky_boundary_is_missing(self):
        modes = {
            "/home/private": (0o700, 42),
            "/home/private/blynger-webmentions": (0o700, 42),
            "/home/private/blynger-webmentions/current": (0o700, 42),
            "/home/private/blynger-webmentions/bin": (0o700, 42),
            "/home/protected": (0o1770, 99),
            "/home/protected/webmentions": (0o750, 99),
            "/home/protected/webmentions/config": (0o2750, 99),
            "/home/protected/webmentions/inbox": (0o2770, 99),
            "/home/protected/webmentions/verified": (0o700, 42),
            "/home/public": (0o775, 42),
            "/home/public/.git": (0o775, 42),
        }

        def details(path):
            mode, group = modes[path]
            return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=42, st_gid=group)

        for helper in ("install-target-registry", "run-inbound-verifier"):
            with self.subTest(helper=helper):
                namespace = runpy.run_path(str(DEPLOYMENT / helper), run_name="deployment_test")
                with patch.object(namespace["os"], "lstat", side_effect=details), patch.object(
                    namespace["os"], "getuid", return_value=42
                ), patch.object(namespace["os"], "getgroups", return_value=[42, 99]):
                    namespace["require_boundary"]()
                    modes["/home/protected"] = (0o770, 99)
                    with self.assertRaises(ValueError):
                        namespace["require_boundary"]()
                    modes["/home/protected"] = (0o1770, 99)

    def test_shared_inbox_requires_group_inheritance(self):
        verifier = (DEPLOYMENT / "run-inbound-verifier").read_text()
        self.assertIn(
            'require_directory("/home/protected/webmentions/inbox", 0o2770, group=protected.st_gid)',
            verifier,
        )

    def test_cgi_wrapper_is_fixed_and_policy_is_external(self):
        wrapper = (DEPLOYMENT / "webmention.cgi").read_text()
        self.assertIn("PYTHONPATH=/home/protected/webmentions/runtime/current", wrapper)
        self.assertIn(
            "BLYNGER_WEBMENTION_CONFIG=/home/protected/webmentions/config/receiver.json",
            wrapper,
        )
        self.assertNotIn("$QUERY_STRING", wrapper)
        self.assertNotIn("$HTTP_", wrapper)


if __name__ == "__main__":
    unittest.main()
