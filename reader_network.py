"""Bounded public-network transport used by Blynger's private Reader.

This module owns address validation, DNS pinning, redirects, response limits,
and transport errors. Feed parsing and Reader state deliberately live elsewhere.
"""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit


def normalized(url):
    """Return a canonical public HTTP(S) URL or reject it."""
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Enter a public https:// Blyg or item URL.")
    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def public_url(url):
    """Resolve once and reject every non-public destination address."""
    parsed = urlsplit(normalized(url))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = []

    for address in socket.getaddrinfo(
        parsed.hostname, port, type=socket.SOCK_STREAM
    ):
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Reader downloads must use public internet addresses.")
        if str(ip) not in addresses:
            addresses.append(str(ip))

    if not addresses:
        raise ValueError("Reader could not resolve that public address.")
    return parsed, addresses


class PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to the address already checked by public_url."""

    def __init__(self, host, address, port=None, timeout=15):
        super().__init__(host, port=port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection(
            (self.address, self.port), self.timeout, self.source_address
        )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Pin the address while retaining TLS verification for the hostname."""

    def __init__(self, host, address, port=None, timeout=15):
        context = ssl.create_default_context()
        super().__init__(host, port=port, timeout=timeout, context=context)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection(
            (self.address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def request_once(url, address, headers, limit):
    """Fetch one already-resolved URL without following redirects."""
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection_type = (
        PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
    )
    connection = connection_type(
        parsed.hostname, address, port=port, timeout=15
    )
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "Blynger Reader",
                "Host": parsed.netloc,
                **(headers or {}),
            },
        )
        response = connection.getresponse()
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Remote response exceeds the reader size limit.")
        return response.status, body, dict(response.getheaders())
    finally:
        connection.close()


def fetch(url, headers=None, limit=4 * 1024 * 1024):
    """Fetch a bounded public resource with validated, pinned redirects."""
    try:
        current = normalized(url)
        for _ in range(6):
            _, addresses = public_url(current)
            status, body, response_headers = request_once(
                current, addresses[0], headers, limit
            )
            if status == 304:
                return current, b"", response_headers, status
            if status in (301, 302, 303, 307, 308):
                location = next(
                    (
                        value
                        for key, value in response_headers.items()
                        if key.lower() == "location"
                    ),
                    None,
                )
                if not location:
                    raise ValueError("Remote redirect has no destination.")
                current = normalized(urljoin(current, location))
                continue
            if not 200 <= status < 300:
                raise ValueError(f"HTTP {status} from {current}")
            return current, body, response_headers, status
        raise ValueError("Too many redirects.")
    except ValueError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        raise ValueError(f"Could not fetch {url}: {error}") from error
