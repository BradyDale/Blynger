# Webmentions for Blygger clients — an agent field guide

**Audience:** software agents and maintainers implementing Webmentions for a
Blygger-compatible personal site  
**Written by:** ChatGPT/Codex, an OpenAI GPT-5-based model  
**Date:** October 24, 2026  
**Basis:** Blynger 0.13.0 implementation, deployment, independent security
review, controlled activation, and operational review

This is not a substitute for the
[W3C Webmention Recommendation](https://www.w3.org/TR/webmention/) or the
[official Blygger specifications](https://blygger.org/spec/). It is a record of
what was easy to misunderstand while adding Webmentions to a local-first,
Git-published static Blygger site, and of the invariants that ultimately made
the system safe enough to activate.

## Executive lesson

A Webmention feature is not one HTTP form submission. On a static personal
site, it is a distributed reconciliation system spanning:

1. a mutable local editor and private drafts;
2. an exact Git commit that was actually published;
3. a public, hostile-network receiver;
4. a delayed verifier running under hosting constraints;
5. durable queues and protected exports on two machines; and
6. a local interface that must display remote claims without granting them
   authority.

Treat each boundary as independently fallible. Publication must remain valid
when Webmentions fail. A received request must remain untrusted until verified.
A verified relation must remain data, never an instruction. Every transition
must be repeatable after a crash.

## Assumptions that proved wrong

### “A static site cannot receive Webmentions”

The public site was static, but the host supported small CGI programs and
scheduled tasks. The workable design was a tiny intake endpoint, an append-only
unverified queue, a scheduled verifier, a protected verified export, and an SSH
pull into the Mac application. Static publishing and asynchronous receiving can
coexist without turning the site into a general web application.

### “A successful publication can enqueue notifications from current state”

By the time publication finalization clears its mutable state, the information
needed to construct exact Webmention events may be gone or may already reflect
later edits. Outgoing reconciliation and the inbound exact-target registry must
be derived from the exact Git documents in the successfully hosted commit—not
from drafts, working files, or an editor object that happens to be current.

The approved commit and previous published baseline must remain in a durable
reconciliation record until all corresponding work has been safely enqueued.
A crash after hosting succeeds but before enqueueing must resume without losing
events. A second publication must not overwrite unfinished work from the first.

### “Asynchronous SSH is enough”

Moving SSH off the UI thread prevents an immediate freeze, but does not create
durability. Registry refresh work must survive crashes, uncertain remote
results, SSH failures, application restarts, and overlapping publications. It
must retry idempotently until the intended registry is confirmed installed.
Revision ordering must prevent a delayed old refresh from replacing a newer
registry. Installation failure must preserve the last-good registry.

No registry or delivery operation should hold editor or publication locks, and
its failure must not retroactively turn a successful site publication into a
failed publication.

### “HTTP 202 means the mention was delivered”

It means only that a receiver accepted the request for later work. Discovery,
submission, verification, display, and withdrawal are separate states. Record
the receiver response, retain bounded diagnostics, and expose honest states to
the user. Do not claim that the other site displayed or accepted the relation
unless there is separate evidence.

### “A timeout bounds DNS”

A caller deadline does not necessarily cancel a blocking system resolver call.
The first design used a single resolver slot; one stuck lookup could occupy it
after its caller timed out and delay every later request. The corrected design
uses a small bounded resolver pool and shares one in-flight lookup among
requests for the same host. Tests must cover a lookup that outlives its caller,
not merely a resolver that returns a timeout promptly.

### “Safe leaf-file permissions imply a safe deployment”

They do not. A trusted helper can be owner-only while an ancestor directory is
group-writable. Another identity may then replace the whole directory and wait
for the owner to execute the substitute. Inspect the complete ancestor chain,
including ownership, modes, groups, symlinks, and rename rights.

On the deployed host, owner-executed code and trusted configuration needed an
owner-controlled path. The web-writable unverified inbox needed a separate
path. The rehearsal had to use the actual web and owner identities because the
host's real group inheritance and atomic-replacement behavior were more
important than the intended diagram.

### “The CGI process and SSH account can manage each other's files”

Shared groups do not imply that either identity can safely change mode, replace
locks, or atomically install files created by the other. Create files with
their final safe modes, validate existing lock objects, use set-group-ID or
sticky behavior only where the host actually supports the intended semantics,
and rehearse every cross-identity operation.

### “Manual execution proves a scheduled task works”

Schedulers have a different environment, working directory, PATH, identity,
output behavior, and overlap risk. Prove the scheduler itself. The production
worker should take a nonblocking lock, use absolute paths, finish within a
bounded interval, and distinguish routine silence from actionable failure.

### “Every 404 or 410 means the mention was withdrawn”

Only a 404/410 from the actual notified source establishes source deletion.
Failure of an optional Blyg JSON document, discovery link, or other supporting
fetch does not. Preserve structured HTTP status and the identity of the
request that produced it. Temporary DNS, timeout, TLS, and server failures
should preserve the last verified relation and schedule a durable, bounded
retry.

### “Any exception from remote content is just a failed mention”

A deeply nested but size-bounded `author` object produced a recursion failure
and repeatedly aborted an entire verifier batch. Validate types, depth, field
length, and collection sizes before copying remote structures. Malformed input
must fail only that item so later work continues. Conversely, do not swallow a
disk-write or permission failure as bad remote content; operational failures
need visible diagnostics.

### “Reverification is new activity”

Repeatedly proving the same semantic relationship should not create unread
notifications. Give each verified activity a semantic fingerprint. A new
relationship, changed source version, changed relation, or confirmed withdrawal
is activity; an identical reverification is not. Preserve read state across
equivalent records and application restarts.

### “One hosting-mode switch affects only the endpoint”

The original static Apache mode would serve CGI or PHP source instead of
executing it. Enabling CGI affected the whole site, so the rehearsal also had
to check ordinary pages, content types, caching, feeds, Git-file denial, and
sensitive rehearsal-file cleanup. PHP was not required, so PHP-like extensions
were explicitly denied even under a CGI-capable server mode.

## A safe architecture for a static Blygger site

### Outbound path

1. Publish the site and identify the exact hosted Git commit.
2. Compare immutable Blyg documents in that commit with the previous published
   baseline.
3. Durably record new, changed, and withdrawn relationships before clearing
   publication state.
4. Discover the target's endpoint with bounded, pinned network transport.
5. Submit standard `source` and `target` form fields asynchronously.
6. Classify the response and retry only according to a finite policy.
7. Keep publication success independent from delivery success.

The outbox needs cross-process locking, atomic replacement, directory fsync,
validated recovery from a backup, idempotent event identities, and tests at
every write boundary. A missing main file must not silently become an empty
writable queue if a valid committed backup exists.

### Inbound path

1. A public endpoint performs syntax, size, policy, rate, and exact-target
   admission only. It does no network fetch.
2. It durably queues an unverified claim and returns a generic response that
   does not reveal blocklist or registry details.
3. A scheduled worker locks the queue and fetches the claimed source through
   the hardened public-network transport.
4. The worker proves that the source contains the claimed relation to the exact
   target and applies Blyg-version-aware relation semantics.
5. It writes an owner-controlled verified record and an authoritative,
   revisioned export.
6. Blynger pulls that export over its existing SSH channel, rejects rollback or
   altered same-revision replay, archives it locally, and displays verified
   metadata as inert text.

The unverified inbox and verified export are different security domains. A web
process compromise may disrupt unverified intake availability, but it must not
be able to manufacture a verified relationship, replace trusted code, or
write the owner-controlled export.

### Exact-target admission

Same-origin admission is too broad. The receiver should accept only exact
canonical targets produced by the currently published site: relevant post,
thread, fragment, item-document, and withdrawal URLs as defined by the client.
Build this registry from the exact published commit. Install it atomically,
retain the last good copy, version it monotonically, and reject an older
delayed installation.

A newly published item may otherwise be rejected until an unrelated refresh
runs. Publication must therefore create durable registry-refresh work
immediately, while keeping the refresh itself outside the publication lock.

## Network security requirements

Every fetch and redirect is hostile. At minimum:

- allow only HTTP and HTTPS and reject credentials and unexpected ports;
- normalize and bound URLs before storing or displaying them;
- resolve the hostname and reject the destination if **any** selected address
  is loopback, private, link-local, multicast, reserved, or otherwise
  non-global;
- connect to the validated address while retaining the original hostname for
  TLS certificate validation and HTTP Host semantics;
- repeat the entire check for every redirect;
- impose one monotonic total deadline across DNS, connect, headers, redirects,
  and body reads;
- cap redirects, response headers, decompressed body size, JSON depth, string
  lengths, and collection counts;
- use a bounded resolver pool that cannot be monopolized by abandoned lookups;
  and
- never convert a fetched URL into a shell argument, local path, or command.

Tests should include mixed public/private DNS answers, rebinding attempts,
redirects into private space, slow DNS, slow headers, slow bodies, compressed
oversize responses, malformed encodings, certificate mismatch, and a DNS call
that continues after the request deadline.

HTTP remains an explicit interoperability compromise: verification proves the
relation observed at retrieval time, but plain HTTP does not authenticate its
origin against an on-path attacker. Prefer HTTPS without pretending that HTTP
and HTTPS offer the same assurance.

## Blygger-specific protocol discipline

- Parse the declared Blyg version before interpreting relations. Do not infer
  a newer draft's fields from an older document. During this implementation,
  for example, generation-source relations were accepted only for a document
  declaring Blyg 0.4, not 0.3.
- Preserve immutable item and version identity. A Stub, Transclusion, Fork, or
  withdrawal should refer to the exact public artifact the author approved,
  not the latest mutable editor state.
- Keep human HTML, Blyg JSON, fragment pages, and thread pages distinct even
  when they describe the same writing. The target registry and verifier need
  explicit rules for each.
- Generate outbound events from public commit documents. A draft may contain
  relations that were never published and must never send a Webmention.
- Treat the current official specification as the authority. Draft proposals
  are useful design input, but they do not silently change the protocol version
  emitted by a stable client.

## Intake policy and cost control

Rate limits and retention are core architecture, not later polish—especially
on metered hosting. Bound request bytes, URL lengths, total queue entries,
per-site activity, writer concurrency, terminal-record retention, verifier
batches, fetch bytes, execution time, and retry count.

Support three explicit receiving modes:

- **open:** accept otherwise valid exact-target claims;
- **denylist:** silently decline configured sources or sites; and
- **allowlist:** accept only configured sources or sites.

A blocked sender does not need confirmation. Apply policy before logging or
queue growth where possible, and return a generic response to avoid turning
the endpoint into a policy oracle.

Retention must cover derived records as well as the main queue. One early
implementation pruned ledger entries but kept verification files forever,
eventually freezing exports at a hard record limit. When an authoritative
export intentionally expires a relationship, the local archive must also
reconcile that removal so a later recurrence cannot collide with stale receipt
numbers.

## UI and authority boundaries

Incoming fields are labels, not markup. Render them with text-only DOM APIs.
Never insert remote HTML, execute scripts, treat a remote string as a local
path, or allow it to become a draft, subscription, publication, command, or
other privileged action.

Opening a source is itself an action boundary: revalidate that it is an allowed
HTTP(S) URL and open it in the main browser context. Copying a diagnostic report
may include bounded URLs and statuses, but never secrets, local paths, raw
headers, or shell-ready text.

The interface should show people and activity, not internal queue machinery.
Still, diagnostics must preserve enough information to distinguish accepted,
pending, retrying, failed, verified, updated, and withdrawn work without
overstating what happened.

## Recommended implementation order

1. Write the threat model, state machine, receiver contract, and activation
   gates before adding a public endpoint.
2. Implement durable outbound reconciliation from exact publication commits.
3. Add outbound status and diagnostics without changing delivery behavior.
4. Define exact targets, policy modes, limits, and the inactive intake queue.
5. Implement the verifier with hardened transport and item-level isolation.
6. Implement protected revisioned export and local synchronization.
7. Add verified-only UI and semantic unread behavior.
8. Rehearse the real host permissions, identities, server mode, registry
   installation, rollback, cleanup, and disable path using disposable data.
9. Run an independent security review. Fix each confirmed defect with a focused
   regression, then have the reviewer recheck the fix.
10. Deploy the exact reviewed runtime and verify hashes before scheduling it.
11. Activate in a controlled order: registry, receiver, scheduler, local sync,
    endpoint advertisement, then one bounded live interoperability test.
12. Perform a post-activation operational review before declaring a release.

Keep commits small at crash and trust boundaries. A package split or structural
cleanup should be separately reviewable from behavior changes.

## Failure-injection tests worth requiring

- crash before and after every publication-reconciliation write;
- two overlapping publications whose registry refreshes finish out of order;
- SSH success, explicit failure, timeout, disconnect, and uncertain result;
- missing main queue with a valid backup, corrupt main, corrupt backup, and
  unsafe lock objects;
- two processes trying to update the same queue or export;
- web identity attempts to replace every ancestor of trusted owner code;
- hostile input followed by a legitimate item in the same verifier batch;
- verified source followed by 404/410 withdrawal;
- verified source followed by transient DNS/timeout/5xx failure and restart;
- identical reverification, semantic update, withdrawal, prune, and later
  recurrence;
- lower-revision and altered same-revision export replay;
- scheduler overlap and scheduler-specific environment failure; and
- endpoint disable, advertisement removal, and last-good recovery.

Run these against disposable repositories and host paths. Do not use real
drafts as test fixtures.

## Activation checklist

Do not advertise the endpoint until all of these are true:

- the deployed receiver, verifier, registry installer, and runner hashes match
  the reviewed artifacts;
- the exact-target registry is current and crash-recoverable;
- every trusted path has a non-replaceable ancestor chain under the actual host
  identities;
- the web identity can append unverified intake but cannot replace trusted code,
  configuration, registries, or verified exports;
- the scheduled worker is proven under the scheduler, cannot overlap, and
  reports operational failure;
- rate, queue, retention, fetch, retry, and execution bounds are active;
- local synchronization rejects rollback and cannot freeze the UI or delay
  publication;
- untrusted fields remain inert through display and URL opening;
- PHP or other unused executable surfaces are denied;
- the disable and recovery procedures have been rehearsed; and
- an independent reviewer has approved the specific deployed design.

## What good looks like

A robust implementation maintains these invariants:

- Publishing is complete when the approved site commit is hosted. Webmention
  trouble cannot revoke that success.
- No draft or working-tree-only relation causes network activity.
- No accepted request is treated as verified merely because it reached the
  receiver.
- No remote field becomes code, markup, a filesystem path, or authority.
- No network destination is contacted unless the exact connected address was
  validated as public for that hop.
- No crash loses committed work, and every retry is idempotent and bounded.
- No older delayed operation can replace newer trusted state.
- No duplicate reverification creates false unread activity.
- No web-writable identity can replace code later executed by a more privileged
  identity.
- The user can pause or disable sending and receiving without damaging the
  published site.

The practical standard is not “it sent one Webmention.” It is: the system can
be interrupted at any boundary, fed hostile data, restarted, and allowed to
retry—and still converge on the exact relationships expressed by the exact
published commits, without exposing private writing or granting the network
authority over the site.
