import unittest
from urllib.parse import urlencode

from webmentions.inbound_contract import (
    InboundContractError,
    LIMITS,
    ReceiverPolicy,
    capacity_error,
    parse_inbound_claim,
    parse_inbound_request,
    require_published_target,
    response_headers,
)


OWN = "https://example.com/blyg/"
TARGET = OWN + "t/00000000000000000000000002/"
ITEM = OWN + "items/00000000000000000000000002.json"
SOURCE = "https://writer.example/blyg/t/00000000000000000000000001/"


def body(source=SOURCE, target=TARGET, **extra):
    return urlencode({"source": source, "target": target, **extra}).encode()


def parse(payload=None, **options):
    return parse_inbound_claim(
        method=options.pop("method", "POST"),
        content_type=options.pop("content_type", "application/x-www-form-urlencoded"),
        body=payload if payload is not None else body(),
        own_origin=OWN,
        published_targets={TARGET, ITEM},
        **options,
    )


class InboundContractTests(unittest.TestCase):
    def error(self, status, code, payload=None, **options):
        with self.assertRaises(InboundContractError) as caught:
            parse(payload, **options)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))
        return caught.exception

    def test_accepts_exact_published_page_or_item_document(self):
        claim = parse()
        self.assertEqual(claim.key, (SOURCE, TARGET))
        self.assertEqual(claim.source_host, "writer.example")
        self.assertEqual(parse(body(target=ITEM)).target, ITEM)

    def test_normalizes_scheme_host_idna_and_default_port(self):
        source = "HTTPS://B\N{LATIN SMALL LETTER U WITH DIAERESIS}CHER.example:443/post"
        claim = parse(body(source=source))
        self.assertEqual(claim.source, "https://xn--bcher-kva.example/post")
        self.assertEqual(claim.source_host, "xn--bcher-kva.example")

    def test_rejects_method_media_type_oversize_and_malformed_forms(self):
        self.error(405, "method_not_allowed", method="GET")
        self.error(415, "unsupported_media_type", content_type="application/json")
        self.error(413, "request_too_large", b"x" * (LIMITS["body_bytes"] + 1))
        self.error(400, "invalid_form", b"source=%zz")
        self.error(400, "invalid_form", b"source=https%3A%2F%2Fwriter.example%2Fbad%zz&target=" + TARGET.encode())
        self.error(400, "invalid_form", body(extra="ignored"))
        self.error(400, "invalid_form", b"source=a&source=b&target=c")

    def test_rejects_unsafe_or_oversize_urls_before_queueing(self):
        self.error(400, "invalid_source", body(source="file:///etc/passwd"))
        self.error(400, "invalid_source", body(source="http://127.0.0.1/post"))
        self.error(400, "invalid_source", body(source="https://bad_host.example/post"))
        self.error(400, "invalid_source", body(source="https://user:secret@writer.example/post"))
        self.error(400, "invalid_source", body(source=SOURCE + "#part"))
        self.error(400, "invalid_source", body(source="https://writer.example/" + "x" * 2048))

    def test_rejects_same_foreign_and_unknown_targets(self):
        self.error(400, "same_source_target", body(source=TARGET))
        self.error(400, "foreign_target", body(target="https://elsewhere.example/post"))
        self.error(400, "unknown_target", body(target=OWN + "t/00000000000000000000000003/"))
        self.error(400, "invalid_target", body(target=TARGET + "#part"))

    def test_rate_boundary_precedes_exact_target_lookup(self):
        unknown = body(target=OWN + "t/00000000000000000000000003/")
        claim = parse_inbound_request(
            method="POST",
            content_type="application/x-www-form-urlencoded",
            body=unknown,
            own_origin=OWN,
        )
        self.assertEqual(claim.target, OWN + "t/00000000000000000000000003/")
        with self.assertRaises(InboundContractError) as caught:
            require_published_target(claim, {TARGET, ITEM})
        self.assertEqual(caught.exception.code, "unknown_target")

    def test_policy_modes_are_explicit_and_domain_scoped(self):
        self.assertEqual(parse(policy=ReceiverPolicy("open")).source, SOURCE)
        self.assertIsNone(parse(policy=ReceiverPolicy("denylist", ("example",))))
        self.assertIsNone(parse(policy=ReceiverPolicy("allowlist", ("friend.example",))))
        self.assertEqual(
            parse(policy=ReceiverPolicy("allowlist", ("example",))).source_host,
            "writer.example",
        )
        stopped = self.error(503, "receiver_disabled", policy=ReceiverPolicy("off"))
        self.assertEqual(stopped.retry_after, 3600)
        stopped = self.error(
            503,
            "receiver_disabled",
            b"not even a form",
            method="GET",
            content_type="application/json",
            policy=ReceiverPolicy("off"),
        )
        self.assertEqual(stopped.retry_after, 3600)

    def test_suppressed_source_cannot_probe_targets_and_creates_no_claim(self):
        policy = ReceiverPolicy("denylist", ("writer.example",))
        self.assertIsNone(
            parse_inbound_request(
                method="POST",
                content_type="application/x-www-form-urlencoded",
                body=body(target="not even a URL"),
                own_origin=OWN,
                policy=policy,
            )
        )

    def test_policy_entries_are_hosts_not_urls(self):
        self.assertEqual(ReceiverPolicy("denylist", ("EXAMPLE.", "example")).domains, ("example",))
        self.assertEqual(
            ReceiverPolicy("denylist", ("[2606:4700:4700::1111]",)).domains,
            ("2606:4700:4700::1111",),
        )
        for value in ("", "https://example", "example/path", "example:443"):
            with self.assertRaises(ValueError):
                ReceiverPolicy("denylist", (value,))

    def test_capacity_responses_do_not_echo_untrusted_values(self):
        limited = capacity_error("rate")
        self.assertEqual((limited.status, limited.code, limited.retry_after), (429, "rate_limited", 3600))
        for kind in ("queue", "storage", "lock", "writers"):
            busy = capacity_error(kind)
            self.assertEqual((busy.status, busy.code, busy.retry_after), (503, "receiver_busy", 600))

    def test_response_headers_are_fixed_and_add_only_required_control_headers(self):
        self.assertEqual(
            response_headers(),
            {"Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8"},
        )
        method = InboundContractError(405, "method_not_allowed", "POST required.")
        self.assertEqual(method.headers["Allow"], "POST")
        limited = capacity_error("rate")
        self.assertEqual(limited.headers["Retry-After"], "3600")
        self.assertNotIn("Allow", limited.headers)

    def test_contract_budgets_are_fixed_and_conservative(self):
        self.assertEqual(
            dict(LIMITS),
            {
                "body_bytes": 8192,
                "url_characters": 2048,
                "state_bytes": 16777216,
                "active_writers": 4,
                "lock_seconds": 2,
                "pending_pairs": 200,
                "stored_pairs": 2000,
                "terminal_retention_days": 90,
                "ip_per_minute": 10,
                "ip_per_hour": 50,
                "source_host_per_minute": 10,
                "source_host_per_hour": 50,
                "source_group_per_hour": 25,
                "source_group_per_day": 100,
                "global_per_minute": 30,
                "global_per_hour": 100,
                "global_per_day": 500,
            },
        )


if __name__ == "__main__":
    unittest.main()
