"""Bounded public-network transport used by Blynger's private Reader.

This module owns address validation, DNS pinning, redirects, response limits,
and transport errors. Feed parsing and Reader state deliberately live elsewhere.
"""

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit


_DNS_SLOTS = threading.BoundedSemaphore(4)
_DNS_TASKS = {}
_DNS_TASKS_LOCK = threading.Lock()
_DEADLINE_MESSAGE = "Remote request exceeded the total time limit."


class HTTPStatusError(ValueError):
    """A bounded request completed with a non-success HTTP status."""

    def __init__(self, status, url):
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError("Invalid HTTP response status.")
        self.status = status
        self.url = normalized(url)
        super().__init__(f"HTTP {status} from {self.url}")


class _Deadline:
    """One monotonic budget shared by DNS, redirects, and response reads."""

    def __init__(self, seconds):
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError("Remote request timeout must be positive.")
        self.ends = time.monotonic() + float(seconds)

    def remaining(self):
        remaining = self.ends - time.monotonic()
        if remaining <= 0:
            raise ValueError(_DEADLINE_MESSAGE)
        return remaining

    def expired(self):
        return time.monotonic() >= self.ends


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


def _resolve(hostname, port, deadline=None):
    if deadline is None:
        return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)

    key = (hostname, port)
    with _DNS_TASKS_LOCK:
        task = _DNS_TASKS.get(key)
    owns_slot = False
    if task is None:
        if not _DNS_SLOTS.acquire(timeout=deadline.remaining()):
            raise ValueError(_DEADLINE_MESSAGE)
        owns_slot = True
        with _DNS_TASKS_LOCK:
            task = _DNS_TASKS.get(key)
            if task is None:
                task = {"finished": threading.Event(), "result": {}}
                _DNS_TASKS[key] = task
            else:
                _DNS_SLOTS.release()
                owns_slot = False

    def work():
        try:
            task["result"]["addresses"] = socket.getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            )
        except Exception as error:
            task["result"]["error"] = error
        finally:
            task["finished"].set()
            with _DNS_TASKS_LOCK:
                if _DNS_TASKS.get(key) is task:
                    del _DNS_TASKS[key]
            _DNS_SLOTS.release()

    if owns_slot:
        worker = threading.Thread(target=work, name="Blynger DNS", daemon=True)
        try:
            worker.start()
        except Exception as error:
            task["result"]["error"] = error
            task["finished"].set()
            with _DNS_TASKS_LOCK:
                if _DNS_TASKS.get(key) is task:
                    del _DNS_TASKS[key]
            _DNS_SLOTS.release()
            raise
    if not task["finished"].wait(deadline.remaining()):
        raise ValueError(_DEADLINE_MESSAGE)
    if "error" in task["result"]:
        raise task["result"]["error"]
    return task["result"]["addresses"]


def public_url(url, *, deadline=None):
    """Resolve once and reject every non-public destination address."""
    parsed = urlsplit(normalized(url))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = []

    for address in _resolve(parsed.hostname, port, deadline):
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


def _abort(connection):
    sock = connection.sock
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    connection.close()


def request_once(
    url, address, headers, limit, method="GET", timeout=15, body=None, deadline=None
):
    """Fetch one already-resolved URL without following redirects."""
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection_type = (
        PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
    )
    operation_timeout = min(float(timeout), deadline.remaining()) if deadline else timeout
    connection = connection_type(parsed.hostname, address, port=port, timeout=operation_timeout)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    cutoff = None

    try:
        connection.connect()
        if deadline:
            cutoff = threading.Timer(deadline.remaining(), _abort, (connection,))
            cutoff.daemon = True
            cutoff.start()
        connection.request(
            method,
            path,
            body=body,
            headers={
                "User-Agent": "Blynger Reader",
                "Host": parsed.netloc,
                **(headers or {}),
            },
        )
        response = connection.getresponse()
        chunks = []
        size = 0
        if method != "HEAD":
            while size <= limit:
                chunk = response.read1(min(64 * 1024, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > limit:
                raise ValueError("Remote response exceeds the reader size limit.")
        if deadline and deadline.expired():
            raise ValueError(_DEADLINE_MESSAGE)
        return response.status, b"".join(chunks), dict(response.getheaders())
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        if deadline and deadline.expired():
            raise ValueError(_DEADLINE_MESSAGE) from error
        raise
    finally:
        if cutoff is not None:
            cutoff.cancel()
        connection.close()


def post_bounded(url, body, *, headers=None, limit=64 * 1024, timeout=5):
    """POST one bounded body to one validated, address-pinned public URL."""
    if not isinstance(body, bytes):
        raise ValueError("Bounded public POST body must be bytes.")
    if type(limit) is not int or limit < 0:
        raise ValueError("Bounded public POST limit must be a non-negative integer.")
    try:
        deadline = _Deadline(timeout)
        current = normalized(url)
        _, addresses = public_url(current, deadline=deadline)
        status, response, response_headers = request_once(
            current,
            addresses[0],
            headers,
            limit,
            method="POST",
            timeout=timeout,
            body=body,
            deadline=deadline,
        )
        return current, response, response_headers, status
    except ValueError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        raise ValueError(f"Could not post to {url}: {error}") from error


def fetch_bounded(url, *, method="GET", headers=None, limit=1024 * 1024, redirects=3, timeout=5):
    """Fetch with caller-selected strict bounds and validation at every hop."""
    if method not in ("HEAD", "GET"):
        raise ValueError("Bounded public fetch supports only HEAD and GET.")
    if type(limit) is not int or limit < 0 or type(redirects) is not int or redirects < 0:
        raise ValueError("Bounded public fetch limits must be non-negative integers.")
    try:
        deadline = _Deadline(timeout)
        current = normalized(url)
        for _ in range(redirects + 1):
            _, addresses = public_url(current, deadline=deadline)
            status, body, response_headers = request_once(
                current,
                addresses[0],
                headers,
                limit,
                method=method,
                timeout=timeout,
                deadline=deadline,
            )
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
                raise HTTPStatusError(status, current)
            return current, body, response_headers, status
        raise ValueError("Too many redirects.")
    except ValueError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        raise ValueError(f"Could not fetch {url}: {error}") from error


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
