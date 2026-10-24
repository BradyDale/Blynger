import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import reader_network


PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


class _Socket:
    def __init__(self):
        self.closed = threading.Event()

    def shutdown(self, _how):
        self.closed.set()


class _Response:
    status = 200

    def __init__(self, sock, phase):
        self.sock = sock
        self.phase = phase
        self.reads = 0

    def getheaders(self):
        return []

    def read1(self, _amount):
        self.reads += 1
        if self.reads > 1:
            return b""
        self.sock.closed.wait(1)
        raise OSError("connection interrupted")


class _Connection:
    phase = "body"

    def __init__(self, *_args, **_kwargs):
        self.sock = _Socket()
        self.response = _Response(self.sock, self.phase)

    def connect(self):
        return None

    def request(self, *_args, **_kwargs):
        return None

    def getresponse(self):
        if self.phase == "headers":
            self.sock.closed.wait(1)
            raise OSError("connection interrupted")
        return self.response

    def close(self):
        self.sock.closed.set()


class BoundedTransportSecurityTests(unittest.TestCase):
    def test_bounded_fetch_preserves_non_success_status_and_url(self):
        with patch("reader_network.public_url", return_value=(None, ["8.8.8.8"])), patch(
            "reader_network.request_once", return_value=(410, b"", {})
        ):
            with self.assertRaises(reader_network.HTTPStatusError) as caught:
                reader_network.fetch_bounded("https://remote.example/deleted")
        self.assertEqual((caught.exception.status, caught.exception.url), (410, "https://remote.example/deleted"))

    def test_invalid_resource_budgets_fail_before_network_access(self):
        cases = (
            {"timeout": 0},
            {"timeout": True},
            {"limit": -1},
            {"redirects": -1},
            {"redirects": 1.5},
        )
        with patch("reader_network.socket.getaddrinfo") as resolve:
            for options in cases:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    reader_network.fetch_bounded(
                        "https://remote.example/post", **options
                    )
        resolve.assert_not_called()

    def test_dns_resolution_is_inside_total_deadline(self):
        release = threading.Event()

        def blocked(*_args, **_kwargs):
            release.wait(1)
            return PUBLIC

        started = time.monotonic()
        try:
            with patch("reader_network.socket.getaddrinfo", side_effect=blocked):
                with self.assertRaisesRegex(ValueError, "total time limit"):
                    reader_network.fetch_bounded(
                        "https://slow.example/post", timeout=0.03
                    )
        finally:
            release.set()
        self.assertLess(time.monotonic() - started, 0.25)

    def test_timed_out_dns_does_not_block_an_unrelated_hostname(self):
        release = threading.Event()
        slow_started = threading.Event()

        def resolve(hostname, *_args, **_kwargs):
            if hostname == "slow.example":
                slow_started.set()
                release.wait(1)
            return PUBLIC

        try:
            with patch("reader_network.socket.getaddrinfo", side_effect=resolve):
                with self.assertRaisesRegex(ValueError, "total time limit"):
                    reader_network.public_url(
                        "https://slow.example/post",
                        deadline=reader_network._Deadline(0.03),
                    )
                self.assertTrue(slow_started.is_set())
                started = time.monotonic()
                parsed, addresses = reader_network.public_url(
                    "https://fast.example/post",
                    deadline=reader_network._Deadline(0.2),
                )
        finally:
            release.set()
        self.assertEqual(parsed.hostname, "fast.example")
        self.assertEqual(addresses, ["8.8.8.8"])
        self.assertLess(time.monotonic() - started, 0.15)

    def test_concurrent_dns_for_one_hostname_shares_one_lookup(self):
        release = threading.Event()
        resolver_started = threading.Event()
        calls = []
        results = []

        def resolve(*_args, **_kwargs):
            calls.append(True)
            resolver_started.set()
            release.wait(1)
            return PUBLIC

        def request():
            results.append(
                reader_network.public_url(
                    "https://shared.example/post",
                    deadline=reader_network._Deadline(0.5),
                )[1]
            )

        with patch("reader_network.socket.getaddrinfo", side_effect=resolve):
            first = threading.Thread(target=request)
            second = threading.Thread(target=request)
            first.start()
            self.assertTrue(resolver_started.wait(0.2))
            second.start()
            time.sleep(0.02)
            release.set()
            first.join(0.5)
            second.join(0.5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [["8.8.8.8"], ["8.8.8.8"]])

    def test_one_deadline_is_shared_across_redirects(self):
        deadlines = []

        def resolve(_url, *, deadline):
            deadlines.append(deadline)
            deadline.remaining()
            return None, ["8.8.8.8"]

        def redirect(*_args, **_kwargs):
            time.sleep(0.04)
            return 302, b"", {"Location": "https://next.example/end"}

        with patch("reader_network.public_url", side_effect=resolve), patch(
            "reader_network.request_once", side_effect=redirect
        ):
            with self.assertRaisesRegex(ValueError, "total time limit"):
                reader_network.fetch_bounded(
                    "https://first.example/start", redirects=3, timeout=0.03
                )
        self.assertGreaterEqual(len(deadlines), 2)
        self.assertTrue(all(value is deadlines[0] for value in deadlines))

    def test_slow_headers_and_body_are_actively_interrupted(self):
        for phase in ("headers", "body"):
            with self.subTest(phase=phase):
                connection = type(
                    "Connection", (_Connection,), {"phase": phase}
                )
                with patch("reader_network.public_url", return_value=(None, ["8.8.8.8"])), patch(
                    "reader_network.PinnedHTTPSConnection", connection
                ):
                    started = time.monotonic()
                    with self.assertRaisesRegex(ValueError, "total time limit"):
                        reader_network.fetch_bounded(
                            "https://slow.example/post", timeout=0.03
                        )
                    self.assertLess(time.monotonic() - started, 0.25)

    def test_mixed_public_and_private_dns_is_rejected(self):
        mixed = PUBLIC + [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
        with patch("reader_network.socket.getaddrinfo", return_value=mixed):
            with self.assertRaisesRegex(ValueError, "public internet"):
                reader_network.public_url("https://mixed.example/post")

    def test_custom_port_is_resolved_and_tls_stays_bound_to_hostname(self):
        with patch("reader_network.socket.getaddrinfo", return_value=PUBLIC) as resolve:
            parsed, _ = reader_network.public_url(
                "https://secure.example:8443/post"
            )
        self.assertEqual((parsed.hostname, parsed.port), ("secure.example", 8443))
        resolve.assert_called_once_with(
            "secure.example", 8443, type=socket.SOCK_STREAM
        )

        raw = MagicMock()
        wrapped = MagicMock()
        context = MagicMock()
        context.wrap_socket.return_value = wrapped
        with patch(
            "reader_network.ssl.create_default_context", return_value=context
        ), patch("reader_network.socket.create_connection", return_value=raw) as connect:
            connection = reader_network.PinnedHTTPSConnection(
                "secure.example", "8.8.8.8", port=8443, timeout=0.25
            )
            connection.connect()
        connect.assert_called_once_with(("8.8.8.8", 8443), 0.25, None)
        context.wrap_socket.assert_called_once_with(
            raw, server_hostname="secure.example"
        )
        self.assertIs(connection.sock, wrapped)

    def test_oversized_response_is_rejected(self):
        class Response:
            status = 200

            def getheaders(self):
                return []

            def read1(self, _amount):
                return b"abc"

        class Connection(_Connection):
            def getresponse(self):
                return Response()

        with patch(
            "reader_network.public_url", return_value=(None, ["8.8.8.8"])
        ), patch("reader_network.PinnedHTTPSConnection", Connection):
            with self.assertRaisesRegex(ValueError, "size limit"):
                reader_network.fetch_bounded(
                    "https://large.example/post", limit=2
                )

    def test_bounded_post_uses_the_same_total_deadline(self):
        seen = {}

        def resolve(_url, *, deadline):
            seen["resolve"] = deadline
            return None, ["8.8.8.8"]

        def request(*_args, **kwargs):
            seen["request"] = kwargs["deadline"]
            return 202, b"ok", {}

        with patch("reader_network.public_url", side_effect=resolve), patch(
            "reader_network.request_once", side_effect=request
        ):
            reader_network.post_bounded(
                "https://receiver.example/webmention", b"source=x&target=y"
            )
        self.assertIs(seen["resolve"], seen["request"])


if __name__ == "__main__":
    unittest.main()
