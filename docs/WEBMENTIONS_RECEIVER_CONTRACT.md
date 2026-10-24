# Blynger inbound Webmention receiver contract

Status: Stages 4A-4C implemented locally. The CGI receiver and target registry
generator exist but are not deployed, connected to the app, or advertised.
`webmentions/inbound_contract.py` remains side-effect-free.

## Trust boundary

The public endpoint is only an intake valve. It may parse, apply cheap policy and
resource checks, confirm an exact local target, and durably enqueue one
`(source, target)` pair. It must never fetch a source, resolve DNS, verify a
relation, modify the site, run Git, invoke Blynger, or hold publishing secrets.

Every source URL, hostname, form value, header, and remote address is hostile.
An accepted claim is **pending**, not verified. Nothing accepted at this stage
may become a draft, subscription, response, feed item, public comment, or other
published material.

## Request contract

- Method: `POST` only.
- Media type: `application/x-www-form-urlencoded`, with no charset parameter or
  `charset=utf-8`.
- Body: at most 8 KiB, strict UTF-8, exactly one non-empty `source` and one
  non-empty `target`, and no other fields.
- URLs: absolute HTTP(S), at most 2,048 characters, no credentials or fragment,
  normalized scheme/IDNA host/default port, and not equal after normalization.
  Literal non-global IP addresses fail the cheap check. Full DNS and address
  safety checks belong to the asynchronous verifier.
- The endpoint must not include submitted values in an error body or log. Query
  strings must be redacted from operator-facing status.

### Accepted targets

Publication will eventually produce a bounded, owner-written target registry
from the exact hosted Blyg surface. A target is accepted only when it exactly
matches one of these registry entries:

1. a current fragment or thread's `page`, resolved against Blynger's identity
   origin; or
2. that item's current live document URL, expanded from Blynger's item template
   (the default is `items/{id}.json`).

Withdrawn current items remain valid targets. Numbered HTML aliases, pins,
frozen version pages/documents, the feed, manifest, index, arbitrary same-host
pages, and merely plausible IDs are not accepted. The URL must also lie under
the full identity origin (`https://example.com/blyg/` today), not merely on the
same host. An unknown item is `400`, as Blygger 0.4 requires.

The target registry is immutable to the web process. The receiver never scans
the public tree or trusts a caller-provided ID to construct a path.

## Source policy

Owner-only configuration has four explicit modes:

- `off`: accept nothing; return `503` with `Retry-After: 3600`.
- `open`: accept any syntactically eligible source, subject to all limits.
- `denylist`: silently suppress a listed hostname and its subdomains.
- `allowlist`: silently suppress any hostname not listed.

Entries are IDNA-normalized hostnames, never URLs. The source hostname is still
only an unverified claim at intake. Allowlist mode reduces noise and cost but is
not authentication; denylisting never establishes guilt, and Blynger must not
automatically block a domain from an unverified source claim.

A suppressed request receives the same generic `202` acknowledgement as queued
work but creates no queue record, verification job, notification, diagnostic,
or Thicket history. It is discarded before target lookup, so the response does
not reveal whether a submitted target exists or whether the source is blocked.
The sender is given no reason to retry and no policy membership oracle.

## Fixed resource budgets

The first deployed receiver must enforce all of these. Lower emergency limits
are allowed; raising any limit requires a reviewed contract change.

| Dimension | Limit |
| --- | ---: |
| Body | 8 KiB |
| Each URL | 2,048 characters |
| Complete intake state document | 16 MiB |
| Concurrent queue writers | 4 |
| Queue-lock wait | 2 seconds |
| Pending distinct pairs | 200 |
| Total stored current pairs | 2,000 |
| Terminal record pruning threshold | 90 days |
| One network address | 10/minute, 50/hour |
| One claimed source host | 10/minute, 50/hour |
| One claimed registrable source domain | 25/hour, 100/day |
| All sources | 30/minute, 100/hour, 500/day |

The source-domain group is computed using a versioned, bundled Public Suffix
List snapshot; an IP address groups as itself. If grouping fails, the endpoint
must use a conservative broader bucket, not silently omit that limiter. The IP
limit uses the actual peer address supplied by the web server, not a caller's
forwarding header unless the configured Git host documents and Stage 4D verifies a
trusted proxy boundary.

Syntactically valid, policy-eligible attempts consume rate budget before target
lookup so random target probing is not free. A suppressed source is discarded
without persistent rate or mention history. A re-sent pending pair also consumes
rate budget but updates/acknowledges the existing pair rather than adding a
duplicate. Pending work is never pruned to make room. At 2,000 records, only
terminal records older than 90 days may be pruned, oldest first; if that cannot
create capacity, intake returns `503`. Later verified-state export must occur
before deployed pruning is enabled.

## Decision order and responses

1. Refuse disabled receiver, wrong method/media type, oversized or malformed
   body, and malformed URLs without taking the queue lock.
2. Apply source policy. Silently discarded sources receive the generic `202`
   response and create no persistent record of any kind.
3. For an eligible source, under the rate-state lock, charge the peer-address, claimed-host,
   registrable-domain, and global buckets. Any exceeded bucket returns `429`.
4. Check exact membership in the owner-written target registry.
5. Acquire the queue lock for at most two seconds and apply concurrency,
   pending-pair, total-storage, and writable-storage checks.
6. Atomically and durably create or refresh the pair. Return `202` only after
   the data and containing directory are durable. A duplicate pending pair is
   still `202` but never becomes a second queue record.

| Condition | Status | Required detail |
| --- | ---: | --- |
| Accepted durably | `202` | Plain acknowledgement only; never claims verification |
| Suppressed by denylist/allowlist | `202` | Same acknowledgement; do not queue or log |
| Syntax, source=target, foreign/unknown target | `400` | Generic, no reflected input |
| Wrong method | `405` | `Allow: POST` |
| Body over 8 KiB | `413` | No parsing attempt |
| Wrong media type | `415` | Form encoding required |
| Any rate bucket exceeded | `429` | `Retry-After: 3600`; do not queue |
| Off, full, unwritable, lock/concurrency exhausted | `503` | `Retry-After` 3600 for off, otherwise 600 |

Every response is `Cache-Control: no-store`, contains a short UTF-8 plain-text
or fixed-shape JSON message, and excludes stack traces, paths, policy entries,
counts, and submitted data. `202` deliberately does not reveal whether a pair
was durably queued or silently suppressed by owner policy.

## the configured Git host layout to prove in Stage 4D

| Location | Owner | Web process | Publicly downloadable |
| --- | --- | --- | --- |
| `/home/public/blyg/webmention` (or final CGI route) | executable/read-only | execute/read, never write | endpoint only |
| `/home/protected/webmentions/config/` | read/write | read only | no |
| `/home/protected/webmentions/inbox/` | read/write | narrowly create/update queue data | no |
| `/home/protected/webmentions/verified/` | read/write | no write | no |
| `/home/private/blynger-webmentions/` | read/write/execute | no access | no |

No web-writable path may be executable. No executable or owner-only
configuration may live below the inbox. Stage 4D must demonstrate on the real
host that Python CGI can create an inbox record but cannot alter configuration,
verifier code, or verified records; the owner task can process inbox files;
protected/private files cannot be downloaded; and ownership/umask remain usable
over SSH. Failure of any boundary blocks advertisement and deployment.

## Next checkpoint

Stage 4B is complete. `webmentions/inbound_queue.py` implements the bounded,
durable pending queue and rate-state machine against disposable directories.
It does not add a public route, fetch a source, advertise an endpoint, or
contact the configured Git host.

The portable host format is one strictly validated JSON state document, its
last verified backup, a separate cross-process lock file, and uniquely named
preserved damage. All mutations hold both an in-process lock and an advisory
filesystem lock. A save writes a same-directory temporary file, flushes the
file, atomically replaces the destination, and flushes the containing
directory. State and lock files are group-readable/writable for the eventual
NFS owner/web group boundary and have no world or executable bits.

The state stores one current record per normalized `(source, target)` pair.
Duplicate pending delivery refreshes that record; a re-send of a terminal pair
reopens it for verification. Raw peer addresses are never stored: rolling rate
buckets use one-way keys and expire after their longest window. Invalid target
probes consume rate budget but create no mention record. Policy-suppressed
sources never reach this storage at all.

The queue fails closed when its lock, size, pending, total-record, or storage
budget is exhausted. It recovers a missing or damaged main file only from a
fully validated backup, preserves bounded damaged data once per fingerprint,
rejects symlinks/hardlinks, and will not silently start empty after damage.
Emergency limit overrides may lower the reviewed budgets but cannot raise them.

Stage 4C added `webmentions/inbound_endpoint.py` and
`webmentions/inbound_targets.py`. The endpoint is Python CGI rather than PHP so
it can reuse the reviewed Stage 4A parser and Stage 4B storage implementation
without a second security-critical translation. Its disposable fixture performs
no source fetch and its module is not imported by the application package.

The endpoint requires a pre-created protected inbox, an owner-only configuration,
an immutable exact-target registry, and a versioned Public Suffix List snapshot.
The generator accepts exact current fragment, thread, and withdrawn documents
and emits only their canonical pages and current item-document URLs. Custom item
templates are accepted only for 0.4 input; this does not change Blynger's own
declared 0.3 output.

Stage 4D completed on 2026-10-19 after the owner changed the site from **Apache
2.4 Static Content** to **Apache 2.4, PHP, CGI**. The live Python CGI receiver
created only inbox data; could read but not change config/runtime; could neither
read nor change verified/private data; and owner-side processing produced a
private owner-owned record. Protected/private fixture URLs returned `404`.
The official PSL snapshot `2026-10-17_18-52-06_UTC` was installed with pinned
version, upstream commit, byte length, and SHA-256 metadata. All public rehearsal
routes and fixture state were removed, and the receiver remains unadvertised.
The next checkpoint is Stage 5's bounded structural verifier.
