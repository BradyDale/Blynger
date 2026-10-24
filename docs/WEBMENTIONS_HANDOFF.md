# Blynger Webmentions implementation journal

## CURRENT HANDOFF — READ THIS FIRST

**Stage 10 activation is functionally complete. Blynger sends eligible outbound
Webmentions and now receives, verifies, synchronizes, and presents incoming
semantic activity in Thicket. The public receiver is advertised sitewide,
deny-list mode is active, exact-commit target refresh is current, the emergency
Off path passed, and a live self-transclusion completed end to end. Activation
exposed two cross-identity shared-lock defects; both failed closed, received
focused regressions, were deployed with matching hashes, and the complete
539-test suite passes. Stage 11 operational review and the Stage 12 release
checkpoint are complete. Webmentions is released in Blynger `0.13.0`.**

- Baseline: Blynger `0.12.0`, Blyg output `0.3`, Git commit
  `6c62c818d86be8ce7e1c41a4b880e1645ca11912`.
- Protocol examined: current Blygger Protocol `0.4` draft at
  <https://blygger.org/spec/0.4/>, source revision
  [`da5fa2f`](https://github.com/blygger/blygger-spec/commit/da5fa2f), checked
  2026-10-18. The W3C Webmention Recommendation was also checked at
  <https://www.w3.org/TR/webmention/>.
- The current application sends compatible outgoing `0.3` stub,
  transclusion, and fork Webmentions. Receiving, synchronization, endpoint
  advertisement, and the verified-only Thicket display are active. Existing
  `0.3` output must not be relabeled `0.4` until the
  separate 0.4 compatibility work described below is complete.
- Outgoing work belongs after the exact approved publication commit reaches the
  host. Queue creation must use documents read from that commit, never drafts or
  the current working tree. Network delivery must be asynchronous and must never
  change a successful publication into a failed one.
- Incoming work can use a small the configured Git host endpoint plus a scheduled
  verifier. Verified results should be pulled one-way to the Mac over Blynger's
  existing SSH connection; the local app must not become publicly reachable.
- The endpoint was advertised only after receiving, verification,
  synchronization, and security tests were complete.
- The complete working send-and-receive release is **Blynger 0.13.0**.
- Safe to run and publish from this checkpoint: **yes**. Outbound delivery is
  active background work; it does not hold publication/editor locks or change a
  successful publication result. Existing due outbox entries may send when
  Blynger starts.

## Objective

Add interoperable Blygger Webmention sending and receiving without changing
Blynger's local-first model: a private Mac application publishes static files by
Git, the public host performs only the minimal dynamic receiving work, and
untrusted remote data never edits or publishes local writing automatically.

The implementation should eventually cover remote `stub_of`,
`transclusions[]`, `forked_from`, and 0.4 `generated[].sources[]` references,
plus ordinary URL stubs where W3C discovery succeeds. Incoming verified
mentions should be available in a calm, simple Reader/Mentions interface, with
no automatic subscription and no automatic public display.

## What was verified in Stage 0

### Protocol

Blygger 0.4 is the current complete protocol document and supersedes 0.3, but it
remains a pre-1.0 draft. Webmention remains optional at every conformance level.
The examined published page identifies source revision `da5fa2f`; later living
text should be rechecked before coding each wire-facing stage.

Section 15 requires or recommends the following relevant behavior:

- A receiving Blyg advertises a manifest `webmention` URL. Permalinks and the
  feed should also advertise it using Webmention link discovery.
- A sender notifies remote structural references only: cross-origin stubs,
  transclusions, forks, and 0.4 generation sources. Same-origin references and
  ordinary links do not generate Blygger mentions. A `{url}` stub uses ordinary
  W3C Webmention discovery.
- `source` is the referencing item's absolute public page. `target` is the
  referenced public page (or ordinary URL for a URL stub).
- Discovery first checks the target Blyg manifest, then W3C HTTP `Link`, then
  HTML `<link>`/`<a>` discovery. An absent endpoint is a final, normal result.
- Any 2xx response is success. Network errors, 5xx, and 429 are retryable; other
  4xx responses are terminal. The recommended retry intervals are 15 minutes,
  1 hour, 4 hours, 12 hours, and 24 hours.
- Republishing sends only new references or references whose target version
  changed. Withdrawal of a stub re-sends once. Delivery is fire-and-forget:
  publication must not wait for it or fail because of it.
- A receiver accepts the W3C form-encoded `source`/`target` POST, performs cheap
  validation and rate limiting before queueing, responds 202, and verifies
  asynchronously.
- Structural verification is deliberately bounded (recommended maximum three
  redirects, five seconds and 1 MB per fetch, and two fetches or three when a
  manifest template must be checked). It verifies the live item document's
  origin/path and one relation in priority order: stub, transclusion, fork,
  source. The 0.4 manifest-located item template must be honored.
- A verified result is a pointer and metadata, not copied remote content. It is
  never automatically published, added to the feed, or treated as authoring
  material. Re-sent pairs reverify; no-longer-valid mentions become `gone`.
- Plain non-Blyg Webmentions may be accepted only as a separate, lower-trust
  class. The reference client does not accept them. Blynger should omit them in
  the first implementation.

The W3C Recommendation additionally confirms discovery precedence, preserving
endpoint query strings, form-encoded POSTs, idempotent updates, source-link
verification, and strict protection against arbitrary/localhost fetching.

### Existing publication architecture

- `app.py` owns background review and publication jobs. Publication already
  returns control to the writer while the exact approved commit is pushed.
- `core.py:begin_publication` creates and durably records an immutable approved
  commit plus the drafts, pins, paths, and prepared inputs represented by it.
- `core.py:push_publication_network` pushes exactly that commit and verifies the
  remote branch state without holding the private-state locks.
- `core.py:finish_publication` reads public documents from that commit, records
  successful-publication interactions, preserves later writing, and clears only
  state represented by the approved snapshot.
- `reader.py` owns private Reader state, serializes mutations, writes atomically,
  keeps a backup, and isolates malformed imported items.
- `reader_network.py` already supplies public-URL validation, DNS resolution and
  address pinning, TLS hostname verification, bounded bodies, and revalidation
  of every redirect. Webmention code should reuse or extract these tested
  principles rather than create an unsafe second fetcher.
- The local HTTP server binds only to `127.0.0.1` and uses an ephemeral token and
  origin/host checks. It must remain private.
- Site publication is Git-based. A host-side post-receive hook checks the pushed
  commit into `/home/public`.

### Exact outgoing integration point

After `push_publication_network(pending)` returns successfully, but before the
pending publication is discarded, derive notifications from the exact item
documents in `pending["commit"]` and add them to a durable private outbox using
idempotency keys. This can be a small, non-network step beside publication
finalization; the actual discovery and delivery worker starts independently
afterward.

The outbox operation must be safe to repeat. A crash after the host accepts the
commit leaves `pending_publication` available for retry; a repeat must neither
lose nor duplicate notifications. Failure to contact a Webmention endpoint—or
the absence of one—must never roll back, obscure, or relabel the successful Git
publication. Queue-maintenance errors should be surfaced as Webmention status,
not as a claim that the public post failed.

Extraction must compare the newly published exact document with the last
successfully published exact document. It must not scan arbitrary HTML links or
infer relationships from prose.

### the configured Git host capabilities

Verified against the configured Git host's current official documentation and the
actual example site environment on 2026-10-18:

- the configured Git host supports PHP, CGI, FastCGI, and scheduled tasks. Scheduled
  tasks may run as often as every ten minutes and are configured in the site
  control panel. See the official [programming](https://faq/section/programming/-)
  and [scheduled task](https://faq/section/programming/cron)
  documentation.
- The actual site currently provides PHP `8.3.31-nfsn1` and Python `3.11.15`.
  No existing public PHP or CGI handlers were found in the first two public
  directory levels.
- `/home/public` is web-served. `/home/protected` is not directly downloadable,
  is accessible to scripts, and on this site is writable by the web group.
  `/home/private` is owner-only. See the official [directory layout](https://faq/section/ourservice/directories).
- The provider explicitly recommends that web-writable data never also be
  web-executable. Any queue belongs under `/home/protected`, not beside the
  public endpoint.

No receiver, writable queue directory, secret, or scheduled task was created in
Stage 0. CGI execution through the live site has not been tested. A deployment
stage must verify the chosen handler locally and on-host before advertising it.

## Proposed design

### Outgoing

Create a focused outbound module rather than enlarging `core.py` or `reader.py`.
It should own:

1. exact-document reference extraction and comparison;
2. a private, atomically written and backed-up outbox;
3. deterministic idempotency keys, at minimum incorporating source identity and
   version, target identity/version or URL, and relation/withdrawal event;
4. endpoint discovery using the existing safe-network transport principles;
5. status (`pending`, `delivered`, `rejected`, `no_endpoint`, `retrying`,
   `abandoned`) and retry metadata; and
6. asynchronous delivery that never participates in the Git publication result.

Do not backfill historical items automatically. The first enabled publication
establishes the baseline; only later new/changed eligible references should send.

### Incoming host components

The preferred small deployment is:

1. A minimal public PHP endpoint accepts only bounded form-encoded POSTs, checks
   syntax and that the target maps to a published example Blyg item, applies
   per-host, registrable-domain, global, request-size, and queue-size limits,
   appends a pending `(source,target)` record under `/home/protected`, and returns
   202. It performs no remote fetch in the request.
2. A scheduled Python or PHP worker processes the protected queue under a lock,
   performs bounded SSRF-resistant structural verification, and atomically
   updates durable verified/gone/failed records. The worker contains no Git,
   local-app, or publishing credentials.
3. The endpoint and worker are immutable program files owned by the site owner;
   only tightly scoped data files/directories are web-writable. Queue entries
   store URLs and processing metadata, not fetched hostile page bodies.
4. Endpoint advertisement is added only after the complete receiving path passes
   security and interoperability tests.

### Secure synchronization to the Mac

Use the SSH access Blynger already requires for Git publication. The scheduled
worker writes a bounded, non-secret JSON export under `/home/protected`; Blynger
reads it one-way over SSH and merges records idempotently into a separate private
local mention store. This avoids a public management API, a new bearer secret,
and all inbound access to the Mac.

The host should retain the authoritative relation/status history needed for
duplicate handling, reverification, and withdrawal. Blynger should retain a
durable local copy for offline presentation. A remote outage must not erase the
local copy or block authoring, Reader use, or publication.

### Presentation

After the data path is stable, prepare a mockup for approval before implementing
the Mentions view. The first UI should show source/author, target item, relation,
verification status, received time, and an action to open the source. It may
offer existing Reader actions explicitly, but must not subscribe automatically.
Use a subtle green-blue status indicator—not red—and avoid an elaborate social
interface.

## 0.3 / 0.4 compatibility

- Webmention itself exists in 0.3, so Blynger can first send compatible stub,
  transclusion, and fork notifications without changing its declared protocol.
- The `source` relation requires 0.4 generation-source records. Do not invent
  these records or emit `source` while Blynger still declares 0.3.
- Receiving 0.4 mentions requires manifest-located item templates and the path-
  scoped identity checks in §15.4. A receiver that checks only
  `{origin}items/{id}.json` would reject legitimate 0.4 senders.
- Blynger must not change `BLYG_VERSION` to `0.4` until its publisher and Reader
  support the relevant manifest templates and labels and its conformance docs
  have been re-audited. Keep that compatibility work in independently testable
  commits; it is related to but not a pretext for one large Webmention change.
- Numbered HTML pages are permitted. The protocol identity is the Blyg item and
  its stable `page` URL, not a required `/t/{id}/` presentation convention.

## Implementation stages

Each entry is a separate reviewed commit (split further if it exceeds one small
work unit). Every stage updates this journal and leaves the app safe to run.

0. **Investigation and architecture — completed.** Documentation only.
1. **Outbound foundation, inactive.**
   - 1A: exact-snapshot reference extraction, relation classification,
     comparison, and idempotency-key tests — **completed 2026-10-18**.
   - 1B: durable private outbox with atomic recovery and status transitions —
     **completed 2026-10-18**.
   - 1C: safe manifest/W3C endpoint discovery with hostile-URL tests —
     **completed 2026-10-18**.
2. **Outbound delivery and exact-publication integration.** No historical
   backfill and no live third-party notification without approval.
   - 2A: inactive W3C form-encoded POST contract, response classification,
     finite retry schedule, withdrawal semantics, and disposable-server tests —
     **completed 2026-10-18**. It does not consume the outbox or connect to
     publication.
   - 2B: inactive asynchronous outbox worker with durable retry transitions,
     restart behavior, and idempotent recovery when a remote endpoint may have
     accepted a request before local success was recorded. It uses mock or
     disposable endpoints only and never holds publication/editor locks —
     **completed 2026-10-18**.
   - 2C: crash-safe publication-to-outbox handoff using only the exact approved,
     successfully hosted commit. Add failure injection around push, enqueueing,
     finalization, uncertain push results, and repeated recovery. Establish an
     explicit first-enable baseline so historical references are not replayed —
     **completed 2026-10-18**.
   - 2D: enable the complete local outbound workflow only after 2A-2C pass,
     preserving publication independence and recoverable diagnostics. Network
     delivery remains background work and no third-party live test occurs here
     — **completed 2026-10-18**.
3. **Outbound status and approved interoperability test.**
   - 3A: safe read-only status backend — **completed 2026-10-18**.
   - 3B: approved read-only Thicket status UI — **completed 2026-10-18**.
   - 3C: durable pause/resume plus outbound verification and cleanup —
     **completed 2026-10-19**.
4. **Incoming endpoint and protected queue.** A separately exposed, deployable
   skeleton, inactive and unadvertised, with bounded input, rate, concurrency,
   queue, storage, permission, locking, corruption, and recovery tests.
   - 4A: minimal receiver contract, fixed resource budgets, source policy,
     accepted-target rules, error responses, and NFS permission matrix —
     **completed 2026-10-19**.
   - 4B: durable bounded pending queue and rate-state machine in disposable
     storage, still without a public route or remote fetch — **completed
     2026-10-19**.
   - 4C: minimal Python CGI endpoint matching the contract in a local deployment
     fixture, still unadvertised — **completed 2026-10-19**.
   - 4D: owner-approved the configured Git host permission and behavior rehearsal,
     still unadvertised — **completed 2026-10-19**.
5. **Incoming structural verifier.** Bounded SSRF-resistant fetches at every
   hop, 0.4 templates, provenance and relation checks, duplicate/update/gone
   behavior, resource limits, and hostile fixtures — **completed 2026-10-20**.
6. **SSH synchronization.** One-way validated protected export, idempotent local
   archive, last-known-good recovery, offline/error behavior, no publication or
   repository coupling, no repeated surprise authentication prompts, and no
   commands or paths derived from mention values — **completed 2026-10-20**.
7. **Mentions interface.** Mockup first; then the approved small Reader/Mentions
   presentation and explicit actions. Imported data remains untrusted and
   cannot silently create drafts, subscriptions, comments, or public changes.
8. **Security gate — adversarial review before public receiver deployment.**
   Produce a threat model and attack-surface inventory; review every handler,
   fetch, queue transition, synchronization path, dependency, and permission;
   run adversarial SSRF, rebinding, redirect, malformed-input, exhaustion,
   concurrency, corruption, recovery, and privilege-boundary tests; demonstrate
   that the receiver can be disabled without affecting the static site. This
   gate has its own checkpoint commit and blocks deployment on critical issues.
   - **2026-10-21 PHP2Shell hosting precheck:** the Stage 4D server profile is
     PHP- and CGI-capable even though Blynger's planned receiver is Python CGI
     and the hosted public tree currently contains no PHP-like files. The NFS
     realm's default/8.3 CLI runtime and 8.3 minor-version link resolve to the
     fixed `8.3.36-nfsn1` build (with fixed `8.2.35-nfsn1` and
     `8.4.27-nfsn1` builds also installed), but this read-only check did not
     execute or upload a web PHP probe and therefore did not independently
     prove the site's selected web SAPI/version. Treat the unnecessary
     PHP-capable profile as avoidable attack surface: before receiver
     activation, either confirm a provider-supported CGI-without-PHP profile or
     add and test an Apache-level denial for PHP-like extensions while proving
     that the Python CGI receiver and static site still work. Preserve the
     fixed hosted runtime as a deployment gate until that surface is removed.
   - 8A threat model and attack-surface inventory — **completed 2026-10-21**.
     See `docs/WEBMENTIONS_SECURITY_GATE.md`. It identified a predeployment
     total-fetch-deadline risk and retained PHP removal/denial as a deployment
     blocker. No receiver or synchronization component was activated.
   - 8B adversarial network/parser gate — **completed 2026-10-21**. One
     monotonic deadline now covers DNS, redirects, headers, and response bodies
     for bounded Webmention fetches and posts. Slow DNS/header/body, mixed DNS,
     unsafe alternate-document, pathological JSON, hostile metadata, SSRF,
     response bounds, and outbound delivery cases pass. The checkpoint passed
     171 focused tests and all 480 repository tests.
   - 8C durability/concurrency/privilege gate — **completed 2026-10-21**.
     Failure injection covers every queue/verifier/export/archive/registry
     transition, uncertain completion, full storage, corrupt pairs, replay,
     conflict, rollback, and overlapping workers. Verifier and registry locks
     now reject symlinks/hard links and require exact owner-only permissions.
     The checkpoint passed 185 focused tests and all 494 repository tests.
   - Next checkpoint: 8D is the owner-approved deployment/disable rehearsal,
     including actual NFS ownership, task, PHP-denial, and static-site checks.
9. **Fresh-eyes independent security audit.** Create
   `docs/WEBMENTIONS_SECURITY_REVIEW.md` as a reviewer handoff. A reviewer who
   did not implement the feature begins read-only, independently traces hostile
   inputs and publication/outbox recovery, reviews shared Reader networking,
   reproduces findings in disposable fixtures, and classifies evidence as a
   confirmed vulnerability, high-confidence risk, defense-in-depth advice, or
   no issue found. Owner-approved fixes are separate small commits and retested.
10. **Deployment and approved live interoperability.** Configure protected
    storage and scheduled verification; advertise only after Stages 8 and 9;
    test both directions only with explicit approval.
11. **Postdeployment security review.** Inspect the actual the configured Git host
    routes, permissions, protected files, scheduled worker, resource limits,
    logging, queue growth, corruption behavior, and receiver-disable path. Use
    only owner-approved, non-disruptive live tests and record what remains
    unverified.
12. **Documentation and release cleanup.** Update all user/developer/conformance
    documents. Do not bump the app version or cut a release without approval.

### Stage 2 acceptance criteria

Stage 2 is complete. Sending was activated only after automated, disposable
crash/restart tests demonstrated all of the following:

- An eligible notification is not permanently lost when the approved Git push
  succeeds and Blynger crashes before, during, or after durable enqueueing.
- A lost push response or otherwise uncertain local result is reconciled against
  the hosted commit and restores only its notification work.
- Recovery can be repeated without duplicate logical outbox events, including
  after restart with pending or retrying records.
- A crash after a remote endpoint accepts a notification but before Blynger
  records success results only in a protocol-safe delivery retry, not another
  logical event.
- Multiple references, changed target versions, removed references, withdrawal,
  and first-time enablement behave correctly without replaying unrelated
  historical references.
- Every event is derived from the exact approved hosted commit, never a draft,
  filesystem scan, or later working tree.
- Endpoint discovery and delivery hold no publication/editor lock and cannot
  freeze writing, contaminate a later publication, or turn a successful Git
  publication into a reported failure.
- Any condition that might permanently lose notification work leaves a durable,
  recoverable record or clear diagnostic.

## Open risks and security decisions

Implemented safeguards remain subject to the independent audit. “Implemented”
does not mean “verified” until the required evidence has been examined.

| Risk or decision | Severity | Mitigation | Stage | Required evidence | Status |
| --- | --- | --- | --- | --- | --- |
| Successful hosted publication can crash before notification work is durable | Critical | A repeatable publication checkpoint must retain the exact approved commit until idempotent outbox enqueueing is durably complete | 2C | Failure-injection tests before/during/after enqueue, uncertain push recovery, repeated restart recovery | Implemented and tested; audit pending |
| A remote endpoint accepts delivery before local success is recorded | High | Stable logical event keys and protocol-safe retry of the same source/target pair | 2B | Disposable endpoint acceptance/crash/restart test | Implemented and tested; audit pending |
| Webmention networking delays or changes publication results | High | Background worker outside publication/editor locks; publication result remains authoritative | 2B-2D | Concurrency, unavailable-endpoint, and publication-independence tests | Implemented and tested; audit pending |
| Initial enablement either floods history or suppresses the first new relation | High | Establish the already-local finalized commit (or a preserved publication's verified parent) as the baseline before later publication | 2C review | Historical fixture, first-new-reference, uncertain-publication, and interrupted-old-record tests | Corrected and tested; audit pending |
| SSRF, DNS rebinding, redirect escape, or unsafe endpoint storage | Critical | Validate and pin global addresses at every hop with bounded redirects, time, size, and schemes | 1C, 5, 8 | Hostile URL/rebinding fixtures, code inspection, independent audit | Implemented for outbound discovery; audit pending |
| Shared strict-fetch changes regress ordinary Reader imports or weaken either caller | High | Keep caller modes explicit and add cross-caller regression coverage; avoid unnecessary refactoring | 1C, 8, 9 | Reader RSS/Atom/Blyg tests plus strict-discovery tests and independent inspection | Partially verified; independent audit pending |
| Public receiver permits resource exhaustion or storage growth | High | Cheap validation plus request, rate, concurrency, queue, batch, retry, retention, and storage limits | 4, 5, 8, 11 | Boundary/load fixtures and deployed measurements | Stage 4B intake storage/rate limits implemented and tested; endpoint, verifier, audit, and deployment evidence open |
| Receiver executable and writable data share privileges or public exposure | Critical | Separate owner-controlled code from narrowly writable `/home/protected` data; test permissions, traversal, symlinks, locks, and recovery | 4, 8, 11 | Local deployment fixture and live permission/route inspection | Open |
| Forged or malformed claims appear as verified relations | High | Verify the actual remote item, identity, path/template, provenance, target, and structural relation; store pointers/metadata only | 5, 8, 9 | Hostile/malformed fixtures and independent audit | Open |
| Incoming SSH sync corrupts or overwrites local state, blocks publication, or executes attacker-controlled values | High | Separate job and locks; fixed commands/paths; validate bounded JSON; atomic last-good archive and idempotent merge | 6, 8, 9 | Outage, corruption, partial-transfer, repetition, and injection tests | Implemented and tested; audit pending |
| Incoming data reaches privileged authoring or publishing behavior | Critical | Separate mention store and sandboxed presentation; no automatic drafts, subscriptions, comments, relations, or publication | 6-9 | Data-flow review, bridge tests, and adversarial independent audit | Open |
| Private queues, exports, logs, or credentials are web-accessible | Critical | Store outside `/home/public`, minimize privileges, enumerate routes, and verify the real deployment | 4, 8, 11 | HTTP exposure tests and live filesystem/route inspection | Open |
| Outbox corruption or concurrent writers lose records | High | Atomic `0600` writes, verified backup, damaged-file preservation, shared locking, and read-only failure mode | 1B, 9 | Existing corruption/concurrency suite plus independent audit | Implemented; audit pending |
| Authors cannot inspect or pause active outgoing delivery | Medium | Thicket provides inspection and durable pause/resume without discarding work | 3 | UI/state tests and owner-approved mockup | Implemented and tested; audit pending |
| Terminal outbound records and diagnostics grow without a retention policy | Medium | Define bounded retention/export behavior without deleting pending/retrying work | 3, 8 | Long-lived queue fixtures and audit review | Reviewed in 3C; deletion deferred to the broader storage policy in Stage 8 |
| Outbound responsibilities remain in one large module before inbound work begins | Medium | Stabilize the Stage 3 status API, then split planning, storage, discovery/delivery, and service before Stage 4 | after 3, before 4 | Import-boundary plan plus unchanged full regression suite | Split completed with all 359 tests passing; audit pending |

## Invariants

- **SSRF/DNS rebinding:** every hop must resolve and pin only global addresses;
  endpoints and source pages are untrusted. Enforce scheme, credentials,
  redirects, time, size, and fetch-count limits.
- **Resource abuse:** apply cheap checks and layered rate/queue caps before any
  fetch. Scheduled work must have a bounded batch and lock.
- **False attribution:** accept structural relations only from an item document
  whose final URL is valid for its asserted, path-sensitive origin and template.
- **Duplicate/lost notification:** persistent transitions and idempotency must
  survive crashes at every point around push, enqueue, finalization, delivery,
  receiver acceptance, verification, and local sync.
- **Publication independence:** Webmention networking cannot block Git push or
  make a successful public commit unsuccessful.
- **Trust boundary:** incoming records never become drafts, public comments,
  subscriptions, feed/archive entries, or published content automatically.
- **Secret boundary:** no credentials or private state in Git or `/home/public`.
  The host verifier has no access to Blynger's local data or publishing key.
- **Static-site preservation:** existing public history and HTML are not broadly
  rewritten merely to add this feature.

## Decisions made

- Use exact approved commit documents as the only outgoing source of truth.
- Keep Webmention code modular and its durable state separate from Reader items.
- Initially reject/ignore plain lower-trust W3C mentions; accept Blygger
  structural mentions only.
- Prefer PHP for the tiny request endpoint and a scheduled worker for network
  verification; confirm the final language split with a local deployment fixture.
- Keep host-side authoritative status history and an idempotent local archive.
- Prefer SSH pull from `/home/protected` over a public authenticated export API.
- Do not advertise, deploy, live-test, backfill, or bump protocol/app versions
  without reaching the corresponding checkpoint and obtaining required approval.
- Keep Stage 3 small and use the shared Blygger term **Thicket** for Webmention
  activity. The stabilized outbound module was split before public receiver
  work began.
- Put inbound source policy in the native macOS menu, not the main workspace.
  When denylist mode is active, a verified IN row in Thicket shows plain black
  clickable `BLOCK` text beside its URL, shifting purple-red on hover; clicking
  asks for confirmation before blocking that site. The later SSH control path
  must update only a fixed owner configuration file and derive no command or
  path from mention data.
- A denylisted source, or one excluded by allowlist mode, receives the same
  generic `202` as queued work but creates no queue entry, verification job,
  diagnostic, or Thicket history. This is deliberate non-disclosure, not a
  statement that the source was verified.

## Unresolved questions

- Whether the scheduled verifier should be PHP or Python after testing the
  closest local equivalent to the configured Git host execution.
- How much outbound status belongs in the main UI versus Recovery/Mentions.
- Exact outbound terminal-record retention and diagnostic-pruning policy.
- Read, acknowledge, dismiss, and gone-record behavior in the Mentions UI; mockup
  and approve before implementation.
- The exact 0.4 compatibility sequence for manifest templates, link labels, and
  generation sources. Recheck the living spec immediately before that work.
- Whether later versions should accept plain W3C mentions as a clearly separate
  low-trust class. This is explicitly out of scope for the first receiver.

## Checkpoint discipline

Every implementation stage begins from a known Git state, has one bounded
objective and proportionate tests, preserves existing Blynger behavior, updates
this journal, and ends in a descriptive commit. Work expected to exceed roughly
20–30 minutes should be split before it begins. Do not amend or squash earlier
checkpoint commits, discard unrelated work, or begin a large stage when compute
or context is low.

At every stopping point, report:

**WEBMENTIONS CHECKPOINT**

- Last completed stage and commit hash
- Current Git status and tests run/results
- Features working and features not yet implemented
- Deployment status and open security concerns
- Next smallest independently committable task
- Whether this handoff is updated and the commit is safe to resume from

## Stage journal

### Stage 0 — investigation and architecture

- Status: completed 2026-10-18.
- Starting commit: `6c62c818d86be8ce7e1c41a4b880e1645ca11912`.
- Stage deliverable commit: `dc4bcf4` (`Document Webmention architecture and rollout`).
- Files changed: `docs/WEBMENTIONS_HANDOFF.md` only.
- Behavior implemented: none.
- Validation: documentation whitespace check; no application tests required for
  a documentation-only change.
- Persistent state/deployment: none created or changed.
- Known limitation: all sending, receiving, synchronization, and UI work remains
  unimplemented.
- Next acceptance criterion: Stage 1A adds a pure, inactive extractor that reads
  exact Blyg documents, emits only eligible cross-origin relations, computes
  stable idempotency keys, compares versions without noisy resends, and passes
  malformed/same-origin/duplicate/withdrawal fixtures. It performs no network
  call and is not yet wired into publication.
- Safe to run and publish: yes.

### Stage 1A — inactive outgoing reference planning

- Status: completed 2026-10-18.
- Starting commit: `fc661e149032dd4e6d212972c637e574aec90c56`.
- Stage deliverable commit: `181ea74` (`Add inactive Webmention reference
  planning`).
- Files changed: `webmentions.py`, `test_webmentions.py`, and this journal.
- Behavior implemented: a pure planner reads exact old/new Blyg item documents,
  identifies eligible cross-origin stubs, transclusions, forks, and 0.4
  generation sources, groups duplicate relations by target, suppresses unchanged
  references and same-origin references, plans one stub withdrawal, and assigns
  deterministic event keys. Malformed references are isolated as issues.
- Behavior deliberately absent: the module is not imported by the application,
  creates no persistent state, performs no network requests, and has no
  publication hook. Ordinary HTML links are not scanned.
- Validation: all 6 focused planner tests pass. The full suite ran 310 tests;
  every executable test passed except the existing privileged-UI test that the
  restricted test environment prevented from binding a loopback socket; 1 test
  was skipped. The failure occurred before application code ran and is not a
  Webmention regression.
- Persistent state/deployment: none created or changed.
- Next acceptance criterion: Stage 1B adds a separate durable private outbox,
  atomic writes and verified-backup recovery, idempotent enqueueing, and tested
  status/retry metadata. It remains disconnected from publication, discovery,
  and delivery.
- Safe to run and publish: yes.

### Stage 1B — inactive durable outgoing outbox

- Status: completed 2026-10-18.
- Starting commit: `181ea7418a11ee13da78d9e656572c5ffd76a4a0`.
- Stage deliverable commit: `a81baa6` (`Add inactive durable Webmention
  outbox`).
- Files changed: `webmentions.py`, `test_webmentions.py`, and this journal.
- Behavior implemented: planned events can be stored idempotently in a private
  JSON outbox with atomic `0600` writes, a validated rolling backup, preserved
  damaged files, and explicit pending/retrying/delivered/rejected/no-endpoint/
  abandoned states. Retry counts, endpoint URLs (including query strings),
  errors, and next-attempt times survive reloads.
- Concurrent safety: queue objects for the same file share a lock and reload the
  latest durable state before each read or mutation, preventing overlapping
  publisher/worker activity from silently overwriting a newer record.
- Recovery behavior: a damaged main file is preserved and restored from a
  structurally validated backup whose candidate checksums are rechecked. If
  neither copy is trustworthy, the damaged file is preserved and the outbox
  becomes read-only rather than silently discarding or replacing records.
- Behavior deliberately absent: Blynger does not instantiate this outbox, no
  real private data file was created, and there is still no publication hook,
  endpoint discovery, network delivery, receiving, advertisement, or UI.
- Validation: all 12 focused planning/outbox tests pass, including duplicate
  enqueue, reload, retry metadata, terminal transitions, concurrent writers,
  verified-backup recovery, tamper rejection, and no-backup read-only recovery.
  The full suite ran 316 tests: 314 passed, 1 was skipped, and the existing
  privileged-UI test was blocked before application code ran because the
  restricted test environment prohibits binding its loopback test socket.
- Persistent state/deployment: none created or changed outside disposable test
  directories.
- Next acceptance criterion: Stage 1C performs bounded, SSRF-resistant manifest
  and W3C endpoint discovery, honors 0.4 item templates and endpoint query
  strings, treats no endpoint as a normal final result, and passes hostile URL,
  redirect, malformed-manifest, and discovery-precedence fixtures. It remains
  disconnected from publication and delivery.
- Safe to run and publish: yes.

### Stage 1C — inactive safe endpoint discovery

- Status: completed 2026-10-18.
- Starting commit: `a81baa661f70f42c2c53166013024c18f5574b1e`.
- Stage deliverable commit: `26aa2b5` (`Add inactive safe Webmention
  discovery`).
- Files changed: `reader_network.py`, `webmentions.py`,
  `test_webmentions.py`, and this journal.
- Behavior implemented: discovery checks a target Blyg's manifest first, then a
  W3C `Link` response header, then the first HTML `link` or `a` advertising
  `rel=webmention`. HEAD is tried before GET. Relative endpoint URLs are
  resolved correctly, endpoint query strings are retained, and the absence of
  an advertised endpoint is a normal final result rather than an error.
- Blyg 0.4 support: custom item templates containing `{id}` are expanded with
  query strings intact. When a frozen cited page is unavailable, the exact live
  item document is fetched from the manifest location and its identity, origin,
  final URL, and public `page` are checked before use.
- Security behavior: the shared network transport now offers a strict bounded
  mode used by discovery. It permits only HEAD/GET, limits redirects to three,
  uses five-second requests and at most 1 MB bodies (256 KB for manifests),
  resolves and pins only global addresses at every hop, retains TLS hostname
  verification, and separately revalidates an advertised endpoint before it
  could be stored. Unsafe schemes, credentials, local/private addresses,
  redirect escapes, malformed templates, and identity mismatches are rejected.
- Behavior deliberately absent: the application does not call discovery, the
  outbox has no worker, no POST is sent, publication has no Webmention hook, and
  no real site or third-party endpoint was contacted.
- Validation: all 21 focused Webmention tests pass, plus the existing Reader
  address-pinning compatibility test. Coverage includes manifest precedence,
  custom templates, HEAD-before-GET, HTTP-header-before-HTML precedence,
  query preservation, absent endpoints, fallback behavior, hostile endpoints,
  redirect revalidation, redirect limits, and item-location enforcement. The
  full suite ran 325 tests: 323 passed, 1 was skipped, and the existing
  privileged-UI test was blocked before application code ran because the
  restricted test environment prohibits binding its loopback test socket.
- Persistent state/deployment: none created or changed outside disposable test
  directories.
- Next acceptance criterion: divide Stage 2 into bounded commits for delivery
  semantics and then exact-publication integration. Test form encoding, 2xx/
  4xx/5xx/429 classification, retry timing, crash boundaries, no historical
  backfill, and absolute publication independence before enabling any live
  network behavior.
- Safe to run and publish: yes.

### Reliability and security planning checkpoint

- Status: completed 2026-10-18.
- Starting commit: `26aa2b5b6df2ceccb2a24a55e71ba792e9c94d80`.
- Stage deliverable commit: this documentation checkpoint.
- Files changed: this journal only.
- Behavior implemented: none. Completed Stages 1A-1C and their commits/tests
  were preserved without redesign.
- Planning change: Stage 2 is split into 2A-2D with an explicit crash/restart
  acceptance gate. The roadmap now includes a separately tested public-receiver
  security boundary, shared Reader-network regression review, mandatory
  predeployment security gate, fresh-eyes read-only audit, and postdeployment
  inspection of the real the configured Git host installation.
- Risk tracking: the focused risk register above records severity, mitigation,
  responsible stage, required evidence, and current status; documentation alone
  does not mark a mitigation verified.
- Validation: documentation diff and whitespace checks; no application code or
  test behavior changed.
- Persistent state/deployment: none created or changed.
- Next acceptance criterion: Stage 2A implements only the inactive outbound POST
  contract, response classification, finite retry schedule, and withdrawal
  semantics against disposable endpoints. It does not consume the outbox,
  connect to publication, send to a third party, or activate the feature.
- Safe to run and publish: yes.

### Stage 2A — inactive outbound delivery semantics

- Status: completed 2026-10-18.
- Starting commit: `b7a936b` (`Move SSH checks into background publishing`).
- Stage deliverable commit: this checkpoint (`Add inactive Webmention delivery
  semantics`).
- Files changed: `reader_network.py`, `webmentions.py`,
  `test_webmentions.py`, and this journal.
- Protocol recheck: the live Blygger 0.4 specification still points to source
  revision `da5fa2f`; §15.2 still specifies form-encoded `source`/`target`, any
  2xx as success, retry for network errors/5xx/429 at 15 minutes, 1 hour, 4
  hours, 12 hours, and 24 hours, terminal other 4xx, and one ordinary re-send
  for a withdrawn stub. The W3C Recommendation still specifies the same
  form-encoded POST contract.
- Behavior implemented: an already-discovered event can be encoded as exactly
  one bounded `application/x-www-form-urlencoded` POST. Successful, retryable,
  rejected, and exhausted responses are classified without mutating queue or
  publication state. Endpoint query strings are retained. Withdrawals carry no
  private wire flag: they re-send the same source/target pair so the receiver
  can re-fetch the withdrawn source.
- Network safety: the default POST transport validates and address-pins one
  public HTTP(S) endpoint, retains TLS hostname verification, uses a five-second
  timeout, and limits the response body to 64 KB. It does not follow POST
  redirects; 3xx responses are terminal rather than silently changing the
  approved endpoint or POST semantics.
- Behavior deliberately absent: no worker calls this helper, no real outbox is
  consumed, no publication hook exists, and no live third-party endpoint was
  contacted. The disposable endpoint existed only inside the test process.
- Validation: 25 focused Webmention tests pass, including a real disposable
  loopback receiver that checks the exact form, withdrawal encoding, response
  classes, all five retry intervals, retry exhaustion, network failure, query
  retention, bounded response handling, and address pinning. The full suite
  passes all 331 tests.
- Persistent state/deployment: none created or changed outside disposable test
  directories.
- Next acceptance criterion: Stage 2B adds an inactive asynchronous outbox
  worker that discovers and delivers pending entries, durably records finite
  retry transitions, resumes safely after restart, and treats a lost response
  after remote acceptance as a retry of the same logical event. It remains
  disconnected from publication and uses only disposable endpoints.
- Safe to run and publish: yes.

### Stage 2B — inactive asynchronous outbox worker

- Status: completed 2026-10-18.
- Starting commit: `c86501d` (`Add inactive Webmention delivery semantics`).
- Stage deliverable commit: this checkpoint (`Add inactive Webmention outbox
  worker`).
- Files changed: `webmentions.py`, `test_webmentions.py`, and this journal.
- Behavior implemented: an in-process daemon worker takes a snapshot of due
  pending/retrying records, discovers each endpoint, performs one delivery, and
  durably records delivered, rejected, no-endpoint, retrying, or abandoned
  state. Retry times survive process restart and only become eligible when due.
  The five protocol intervals are persisted, followed by terminal abandonment.
- Concurrency behavior: `start()` returns immediately. The worker's own run
  guard prevents overlapping passes on one worker, while network operations do
  not hold the outbox lock. New logical events can therefore be enqueued while
  a remote endpoint is slow. No Studio, Reader, editor, Git, or publication lock
  is imported or acquired.
- Lost-response recovery: if a receiver accepts the POST but the process stops
  before durable success is recorded, the outbox retains the same event key.
  Restart sends the identical source/target pair again, as W3C idempotent update
  semantics permit, without creating a duplicate logical event.
- Failure isolation: absent endpoints become terminal `no_endpoint`; discovery
  or network failures enter the finite retry schedule. An unexpected worker or
  state-write failure leaves the event pending/retrying and records the worker
  error in memory rather than falsely marking delivery complete.
- Behavior deliberately absent: Blynger does not construct this worker, no
  publication hook or real private outbox exists, and no live third-party
  endpoint was contacted. Publication behavior is unchanged.
- Validation: 30 focused Webmention tests pass. Worker coverage includes prompt
  asynchronous return, enqueueing during a slow delivery, due-time persistence
  across restart, absence versus transient discovery failure, all five durable
  retries and abandonment, and a simulated process loss after remote acceptance
  but before local success recording. The full suite passes all 336 tests.
- Persistent state/deployment: none created or changed outside disposable test
  directories.
- Next acceptance criterion: Stage 2C creates a repeatable, crash-safe handoff
  from the exact approved and successfully hosted Git commit into this outbox.
  It must survive failure before/during/after enqueue, uncertain push results,
  and repeated restart recovery; establish a first-enable baseline; and never
  replay unrelated historical references.
- Release target: working outbound and inbound Webmentions will be released as
  Blynger 0.13.0; this inactive checkpoint does not change the current version.
- Safe to run and publish: yes.

### Stage 2C — crash-safe exact-publication handoff

- Status: completed 2026-10-18.
- Starting commit: `7e57e60` (`Add inactive Webmention outbox worker`).
- Stage deliverable commit: this checkpoint (`Queue exact published
  Webmentions crash-safely`).
- Files changed: `core.py`, `test_webmention_publication.py`, and this journal.
- Durable transaction: once the exact approved commit is confirmed on the host,
  Blynger first saves a reconciliation record containing that commit and its
  exact previous hosted commit. Normal publication finalization then clears
  `pending_publication` while deliberately retaining reconciliation work. Only
  after finalization does idempotent outbox enqueueing remove the record.
- Exact source of truth: both old and new item documents are read with `git
  archive` from the two recorded commits. Drafts, current generated files,
  mutable working-tree state, and later publications are never consulted when
  planning those events.
- Crash recovery: a retained record is replayed at startup. If enqueueing wrote
  some or all events before interruption, stable event keys make the replay
  harmless. A bounded completed-commit ledger prevents a finalized record from
  being recreated when a crash left the older `pending_publication` marker in
  place.
- Publication independence: a damaged or temporarily unavailable outbox leaves
  the reconciliation record and a diagnostic, but successful Git publication
  still finalizes successfully. Multiple finalized publications may retain
  separate ordered records and reconcile later without contaminating each
  other.
- Initial enablement as originally implemented here: the first successfully
  finalized publication established the exact baseline and sent nothing. The
  pre-Stage 3 review later confirmed that this also suppressed a legitimate new
  relation in that publication. The follow-up checkpoint now establishes the
  already-local finalized commit before publication, preserving flood
  prevention without dropping the first new relation.
- Withdrawal: a later exact withdrawn-stub document produces one distinct
  withdrawal event; unrelated republication remains silent through the Stage 1
  planner's version comparison.
- Failure-injection validation: tests cover interruption after the durable
  record, after publication finalization, before enqueue, during partial
  enqueue, and after enqueue before cleanup; restart with and without
  `pending_publication`; an already-hosted commit whose push response was lost;
  mutable working files changed after approval; a second publication while an
  older record remains unresolved; first-enable historical suppression; and
  exact withdrawal replay.
- Validation: all 9 exact-publication handoff tests pass; the combined
  publication/Webmention suites pass after the disposable receiver is permitted
  to bind its local test port; the full suite passes all 345 tests.
- Persistent state: private Studio state may now contain
  `webmention_reconciliations`, `webmention_reconciled_commits`,
  `webmention_baseline_commit`, and bounded `webmention_diagnostics`. Eligible
  post-baseline events are stored in the existing private, mode-`0600`
  `webmentions-outbox.json`. No website file or protocol output changes.
- Behavior deliberately absent: the application still does not start the
  outbound worker, discover a real endpoint, or send a request. No third-party
  site was contacted and no receiver exists.
- Next acceptance criterion: Stage 2D activates the background local worker only
  after successful reconciliation, keeps all endpoint discovery and POST work
  outside publication/editor locks, resumes due work on restart, and exposes a
  recoverable diagnostic without changing the publication outcome. Tests use
  disposable endpoints only; a live interoperability test still requires
  explicit approval.
- Release target: complete working sending and receiving remains Blynger 0.13.0;
  this checkpoint does not change the current application version.
- Safe to run and publish: yes. Publication can create private pending outbound
  records, but nothing sends until Stage 2D explicitly activates the worker.

### Stage 2D — active independent outbound service

- Status: completed 2026-10-18.
- Starting commit: `e9ab196` (`Queue exact published Webmentions crash-safely`).
- Stage deliverable commit: this checkpoint (`Activate background Webmention
  delivery`).
- Files changed: `app.py`, `webmentions.py`, `test_webmentions.py`,
  `test_publication_flow.py`, and this journal.
- Behavior implemented: Blynger constructs one private outbound service at
  application startup. Its daemon thread immediately resumes pending and due
  retry work, checks periodically while the application remains open, and can
  be woken promptly when a successful publication adds exact-commit events.
- Publication independence: the service wake occurs only after both Reader and
  Studio publication locks are released. Discovery and POST work remain on the
  service thread. Failure to wake or run that service does not change a
  successful Git publication into a failure; the durable outbox remains the
  recovery source and a later wake or restart retries it.
- Diagnostics: the service retains its most recent run time and unexpected
  error, reports durable state counts and outbox recovery/read-only status, and
  clears a transient service error after a successful later pass. Stage 3 will
  expose a deliberately small user-facing status rather than adding an
  intrusive publication dialog. If private outbox storage cannot be opened at
  startup, a diagnostic fallback keeps Blynger usable; publication retains its
  exact reconciliation work for a later healthy restart.
- Lifecycle: startup and publication wake calls return immediately. Normal app
  shutdown signals the service before closing the local HTTP server. A due
  retry is noticed within sixty seconds while Blynger remains open; closing the
  app leaves durable work for the next launch.
- Validation: 19 focused lifecycle/publication tests pass. New coverage proves
  immediate startup return, startup recovery, wake-after-enqueue, due retry
  while the app remains open, service-level failure and later recovery, wake
  after both publication locks are released, and publication success despite a
  wake failure. It also proves that an outbox-open failure cannot prevent app
  startup. The combined outbound/publication suites pass all 58 tests; the full
  suite passes all 352 tests.
- Network/deployment: automated tests use injected or disposable local
  endpoints only. No third-party endpoint was contacted, no receiver was
  deployed or advertised, and no public website file changed. In ordinary use,
  eligible post-baseline outgoing stub, transclusion, and fork events may now
  be delivered automatically.
- Next acceptance criterion: Stage 3 adds minimal outbound status and then, only
  with explicit approval, performs one controlled live interoperability test.
  Receiving, synchronization, Mentions UI, security gates, and public endpoint
  advertisement remain later stages.
- Release target: complete working sending and receiving remains Blynger 0.13.0;
  Stage 2D does not change the current application version.
- Safe to run and publish: yes. The queue is durable, sending is background
  work, and publication remains authoritative.

### Pre-Stage 3 review — first-publication correction and scope decision

- Status: completed 2026-10-18.
- Starting commit: `43f8718` (`Activate background Webmention delivery`).
- Stage deliverable commit: this checkpoint (`Preserve first outgoing
  Webmention after activation`).
- Confirmed defect: Stage 2C made the first newly published commit the silent
  baseline. A new Stub, transclusion, or fork in that publication was therefore
  never queued. The existing test explicitly encoded that incorrect behavior.
- Correction: Studio now initializes an absent baseline locally when it opens,
  before later writing is published. It uses a preserved publication's exact
  reviewed parent when present, otherwise the last fetched/finalized commit or
  local HEAD. No network request or endpoint delivery occurs during this step.
  Normal publication still verifies the hosted head, and reconciliation still
  compares the exact `pending["base"]` and approved commit documents.
- Backfill behavior: relations already present in the baseline commit remain
  silent. The first later publication queues only new, changed, or withdrawn
  eligible relations. A Stage 2C-era interrupted record marked as a silent
  baseline is migrated to use its recorded predecessor and is reconciled
  normally. If no local commit can be resolved, Blynger records a diagnostic
  and retains the conservative silent-first-publication fallback rather than
  risk an indiscriminate historical flood.
- Known historical limit: if an installation already fully finalized its first
  post-Stage-2C publication under the old silent-baseline rule, there is no
  remaining reconciliation record that safely identifies which relation was
  intended as new. Blynger does not guess or backfill it automatically. That
  narrow case requires deliberate commit inspection if it is known to have
  occurred.
- Installation/recovery cases: an existing installation uses its finalized
  commit; a fresh installation uses its current repository commit; an
  unavailable remote does not block startup because initialization is local; a
  preserved uncertain publication uses its verified parent; interruption
  before the atomic Studio save simply repeats initialization on restart.
- Stage 2 correctness: exact-commit planning, durable idempotent enqueueing,
  crash recovery, finite persisted retries, uncertain-push recovery, background
  startup/wake/periodic work, and publication independence remain intact. No
  additional correctness defect was confirmed in the bounded review.
- Current module sizes: `core.py` 2,096 lines; `app.py` 327;
  `webmentions.py` 982; shared `reader_network.py` 202;
  `test_webmentions.py` 874; `test_webmention_publication.py` 296; and
  `test_publication_flow.py` 179. There are no other Webmention-specific source
  modules yet.
- Responsibility review: `core.py` owns the exact publication transaction and
  about one focused reconciliation section; `app.py` owns lifecycle wake/start/
  stop integration; `reader_network.py` owns shared bounded, address-pinned
  transport; `webmentions.py` currently owns four coherent but separable areas:
  planning, outbox persistence, discovery/delivery, and worker/service lifecycle.
- Architecture decision: do not delay the small Stage 3 interface with a broad
  split. After Stage 3 stabilizes the status/control API, refactor
  `webmentions.py` into a package before Stage 4 adds public receiver code.
  Likely boundaries are planning, outbox, discovery/delivery, and service. Keep
  host receiver/verifier code in a separate deployment package. Main regression
  risks are circular imports, changed monkey-patch seams, shared lock identity,
  and accidental changes to durable record validation; require the unchanged
  full suite across that split.
- Background review: startup performs an immediate pass; the service checks at
  most sixty seconds apart while open; publication wake is prompt and happens
  after Studio and Reader locks are released; one service thread and the
  worker's run guard prevent competing passes; failures wait rather than spin;
  queue state survives shutdown; later passes continue after unexpected
  exceptions; and wake/start failure cannot change publication success.
- Active sending: cross-origin `stub_of`, `transclusions[]`, and `forked_from`
  references send under current 0.3 output. A plain-URL Stub is eligible through
  W3C discovery; ordinary prose/HTML links are not scanned; same-origin
  relations are ignored; 0.4 generation sources are not invented. Existing
  pending or due entries may send at startup. No author-facing pause or record
  inspection exists yet; this is Stage 3's principal operator-control gap.
- Minimal Stage 3 proposal: add one compact **Outgoing Webmentions** section to
  Recovery, not a top-level workspace. Its collapsed summary shows Running or
  Paused, any recovery warning, and counts for pending, retry scheduled,
  delivery accepted, rejected, no endpoint, and abandoned. Expansion shows
  source, target, relation, last attempt/update, next retry, and a concise error.
  Label 2xx as **Delivery accepted**, explicitly not verified or displayed.
  Add a durable **Pause delivery** / **Resume delivery** control that preserves
  queued work. Do not add a terminal-failure retry button in the first UI.
- Live test boundary: after that interface is approved and implemented, prepare
  one named source/target/content combination. Do not publish it or contact the
  receiver until the owner explicitly approves all three. Record both HTTP
  acceptance and any independently observable recipient verification.
- Security/maintenance additions: the risk register now tracks missing operator
  pause/visibility, unbounded terminal-record retention, and the planned module
  split. Existing SSRF, shared transport, corruption, concurrency, receiver
  trust-boundary, independent-audit, and postdeployment gates remain open where
  appropriate. Outbound success does not establish inbound receiver security.
- Validation: focused exact-publication/outbound/publication suites pass all 61
  tests, including new first-publication, historical-suppression, uncertain-
  publication, and interrupted-old-record cases. The full suite passes all 355
  tests.
- Next independently committable task: present/approve the compact Recovery
  mockup and implement only its read-only status summary plus durable pause
  state; keep the controlled live test as a following explicit-approval step.
- Safe to run and publish: yes. This correction prevents loss of the first new
  eligible notification without replaying existing historical relations.

### First confirmed live outbound Webmention — 2026-10-18

- Blynger published the stub source at
  `https://example.com/blyg/t/2s06a3s98awz4wa54qh1gksyct/`, targeting
  Aneesh Sathe's thread at
  `https://blyg.aneeshsathe.com/t/7t1fzzxswe9p609dfckj5mx5rh/`.
- The durable outbox recorded the `stub` relation as `delivered`. Discovery
  selected `https://blyg.aneeshsathe.com/webmention`; delivery was created at
  `2026-10-18T20:07:22Z` and accepted at `2026-10-18T20:07:24Z`, with no error.
- Independent recipient-side confirmation was visible on Aneesh's published
  thread under **Responses**: “Example Author at example.com · stubbed this · Oct
  18, 2026.” A user-supplied mobile screenshot captured that rendered receipt.
- This is Blynger's first confirmed end-to-end live outbound Webmention:
  publication, durable queueing, endpoint discovery, accepted delivery, and
  visible rendering by the receiving Blyg all succeeded.

### Stage 3A — read-only outgoing status backend

- Files changed: `webmentions.py`, `app.py`, `test_webmentions.py`, and this
  journal.
- Added the token-protected local `GET /api/webmentions-status` interface. It
  reports service health, recovery/read-only state, counts for every durable
  queue status, and the 200 most recently updated records without changing
  delivery state.
- Each record exposes only the operator-facing source, target, relation,
  withdrawal flag, attempt/retry timing, endpoint, and concise error. URL query
  strings, fragments, and embedded user information are removed from the
  returned status snapshot; the durable outbox retains its exact delivery data.
- The response reports its full record count and whether the returned list was
  truncated. An unavailable outbox returns the same stable shape with an empty
  record list and a sanitized diagnostic.
- Behavior deliberately absent: no UI, pause/resume, retry, deletion, or queue
  editing was added in 3A.
- Validation: the focused Webmention, security, publication-handoff, and
  publication-flow suites pass all 73 tests, including the new protected API
  and non-mutating redaction coverage. The full Python suite passes all 357
  tests.
- Next checkpoint: Stage 3B adds the owner-approved compact read-only
  **Thicket** workspace for outbound delivery activity.

### Stage 3B — read-only Thicket interface

- Status: completed 2026-10-18.
- Stage deliverable commit: this checkpoint (`Add read-only Thicket status
  interface`).
- Replaced the earlier Recovery-panel concept with the owner-approved
  top-level **Thicket** workspace, the shared Blygger term for Webmention
  activity.
- The top line is a compact 24-hour dashboard with side-by-side **OUT** and
  **IN** boxes. OUT counts accepted deliveries and shows a red failed count
  only when failures exist. IN remains an explicit unavailable placeholder
  until the separately secured incoming stages provide real data; Blynger does
  not invent an incoming zero.
- The activity ledger initially shows the three most recent outgoing records,
  expands on request, and presents a compact two-line entry: direction and
  local title, destination site, local time, protocol-derived type, and a
  success/pending/failure symbol. Supported outbound labels are `STUB`,
  `FORK`, `TRANSCLUDE`, `SOURCE`, and `WITHDRAWAL`; quotes do not currently
  create a distinct Webmention relation.
- Clicking an entry copies its sanitized status record for support. The failed
  count filters the ledger to failed records. This checkpoint remains
  read-only and adds no retry, deletion, or queue mutation control.
- The tab includes the approved darker blue unread style, but 3B does not
  activate it because incoming unread state does not exist yet. Stage 4 and
  later incoming work must drive that state from real verified records.
- The local status response now includes the public source item id and enriches
  it with the published local title when available. Draft content, URL query
  strings, credentials, and private state remain excluded.
- Validation: the full Python suite passes all 357 tests. JavaScript syntax,
  Python compilation, status API title enrichment, source-id exposure, static
  Thicket structure, compact 24-hour calculation, three-row limit, clipboard
  diagnostics, and unread styling were checked.
- Next checkpoint: Stage 3C adds durable pause/resume without discarding queued
  work, then performs the bounded outbound cleanup review. Incoming remains
  unimplemented and unadvertised.

### Stage 3C — durable outbound control and verification

- Status: completed 2026-10-19.
- Stage deliverable commit: this checkpoint (`Add durable Webmention pause and
  resume`).
- The private outbox now stores a durable Boolean pause state. Existing schema-1
  outboxes migrate to schema 2 without losing or changing any event. Pausing
  prevents new discovery and delivery attempts; work already pending or
  retrying remains intact and work published while paused can still be added to
  the queue. An attempt already in progress may finish before the pause takes
  effect.
- Resume starts or wakes the background service immediately. The pause survives
  application restart and a resumed service delivers the same preserved logical
  event rather than creating a replacement.
- The token-protected local API accepts only an explicit Boolean pause value.
  Thicket exposes a small **Pause outgoing** / **Resume outgoing** control beside
  its bottom status light, uses an amber paused state, and explains that queued
  work is preserved. A damaged read-only outbox disables the control rather
  than pretending that a state change succeeded.
- Activity type labels now use the approved compact all-caps forms: `STUB`,
  `FORK`, `TRANSCLUDE`, `SOURCE`, and `WITHDRAWAL`.
- Cleanup decision: 3C does not silently delete terminal delivery evidence.
  Thicket remains bounded to the 200 newest status records, while durable
  retention/export policy remains part of the broader Stage 8 storage review.
  No manual retry, deletion, queue editing, or incoming behavior was added.
- Verification: 117 focused Webmention, publication, and application tests pass;
  the full Python suite passes all 359 tests. JavaScript syntax and repository
  whitespace checks also pass. Coverage includes schema migration, pause across
  restart, no delivery while paused, preserved pending work, immediate delivery
  after resume, protected API behavior, and unchanged publication independence.
- Live interoperability was not repeated: the confirmed Aneesh exchange already
  proves end-to-end delivery and display, and 3C changes only local operator
  control around that established outbound path.
- Next checkpoint: the separately approved behavior-preserving outbound package
  split. Incoming remains unimplemented and unadvertised.

### Post-Stage 3 — behavior-preserving outbound package split

- Status: completed 2026-10-19.
- Stage deliverable commit: this checkpoint (`Split outbound Webmentions into
  package`).
- Replaced the 1,088-line `webmentions.py` module with a package whose internal
  responsibilities are explicit: `planning.py` plans events from exact
  published documents; `outbox.py` owns durable private state; `delivery.py`
  owns endpoint discovery and bounded delivery; `service.py` owns worker and
  lifecycle behavior; and `shared.py` owns validation and safe status
  redaction.
- `webmentions/__init__.py` preserves the existing public imports used by the
  application, publication path, and tests. The startup fallback remains at the
  package boundary so an unavailable private outbox still cannot prevent
  Blynger from opening.
- No receiver, incoming record, endpoint advertisement, queue transition,
  retry rule, publication hook, UI behavior, network request, or protocol output
  changed in this checkpoint.
- Validation: all 65 focused Webmention/publication tests pass and the complete
  Python suite passes all 359 tests. Package compilation and repository
  whitespace checks also pass.
- Next checkpoint: Stage 4A is contract and threat-boundary work only. It must
  fix the receiver's resource budgets, off/open/denylist/allowlist policy modes,
  accepted targets, error behavior, and NFS permission layout before receiver
  implementation begins.

### Stage 4A — inactive inbound receiver contract

- Status: completed 2026-10-19.
- Added `webmentions/inbound_contract.py`, a pure executable contract with no
  networking, storage, route, lifecycle hook, or public export. Importing it
  cannot activate receiving.
- Fixed the cheap request boundary: POSTed strict UTF-8 form data only, exactly
  one source and target, 8 KiB body, 2,048-character absolute public HTTP(S)
  URLs, no credentials/fragments, distinct normalized URLs, and generic errors
  that do not reflect hostile input.
- Fixed accepted targets to exact owner-generated registry entries for a
  current item page or live item document under the full Blyg identity origin.
  Withdrawn items remain addressable; numbered aliases, pins, frozen versions,
  arbitrary host pages, and guessed IDs do not qualify.
- Fixed operator policy modes (`off`, `open`, `denylist`, `allowlist`) while
  recording that the claimed source host is unverified and neither an allowlist
  nor denylist is authentication.
- Fixed layered limits for peer address, claimed host, registrable-domain group,
  global intake, concurrent writers, lock wait, pending pairs, total records,
  and terminal retention. A duplicate pending pair is acknowledged without a
  duplicate record; no refusal may trigger a fetch.
- Fixed status behavior: eligible work receives `202` only after durable
  queueing, while policy-suppressed sources receive the indistinguishable
  generic `202` without queueing or logging. `400`, `405`, `413`, `415`, `429`,
  and `503` have narrow meanings and never expose values, paths, stack traces,
  policy contents, or internal counts.
- Recorded the exact the configured Git host code/config/inbox/verified/worker layout
  and the six live privilege tests Stage 4D must pass before advertisement.
- Full rationale and tables are in `docs/WEBMENTIONS_RECEIVER_CONTRACT.md`.
- Validation: the dedicated contract suite covers accepted pages/documents,
  normalization, malformed/oversized/unsafe input, exact target membership,
  every policy mode, fixed budgets, and fixed capacity responses.
- Next checkpoint: Stage 4B implements only the durable pending queue and rate
  state in disposable storage. No endpoint, DNS, source fetch, deployment,
  advertisement, or inbound UI belongs in that checkpoint.

### Stage 4B — inactive durable inbound queue and rate state

- Status: completed 2026-10-19.
- Added `webmentions/inbound_queue.py`; it is not imported by the application or
  package root and has no HTTP route, network access, source fetch, deployment
  hook, advertisement, or UI connection.
- One strictly validated JSON state holds current pair records and hashed rolling
  rate buckets. A separate advisory lock works across threads and processes;
  every mutation is bounded by the two-second lock budget.
- Saves use same-directory temporary files, file flush, atomic replacement, and
  directory flush. The last validated state is backed up before replacement.
  Missing/damaged main state recovers only from that backup; bounded damage is
  preserved once by fingerprint, while unrecoverable, oversized, symlinked, or
  hardlinked state fails closed.
- Rate charging enforces the fixed peer-address, claimed-host,
  registrable-domain-group, and global rolling windows before exact target
  membership. Raw peer addresses are not retained. Invalid target probes are
  charged without becoming mention records.
- Pair keys are deterministic. Duplicate pending claims refresh one record, and
  re-sent terminal claims reopen that record for future verification. A lost
  completion after an atomic write can therefore cause a safe retry but not a
  duplicate logical pair.
- Pending work is never pruned. At the total cap, only terminal records at least
  90 days old are removed, oldest first; otherwise intake fails closed. The
  whole state also has a fixed 16 MiB ceiling. Emergency overrides may only
  lower reviewed limits.
- Dedicated tests cover durability/reload, duplicate and terminal re-send,
  target-probe charging, each rate dimension and expiry, pending/total/size
  exhaustion, retention, same-process and separate-process concurrency, lock
  timeout, IPv4/IPv6, missing/damaged recovery, symlink refusal, interrupted
  replacement, and uncertain completion followed by idempotent retry.
- Next checkpoint: Stage 4C implements the minimal PHP endpoint plus exact target
  registry in a disposable local deployment fixture. It must match this state
  format and contract, remain unadvertised, and perform no remote fetch.

### Stage 4C — inactive CGI intake endpoint and exact target registry

- Status: completed 2026-10-19.
- Language decision: the local rehearsal changed the preferred endpoint from
  PHP to Python CGI. the configured Git host already provides Python 3.11 and CGI, and
  using Python lets the public valve reuse the exact Stage 4A parser/policy and
  Stage 4B durability/rate implementation. A PHP endpoint would duplicate that
  security-critical behavior in a second language. Stage 4D must prove the real
  host supports this boundary before the decision becomes deployable.
- Added `webmentions/inbound_endpoint.py`, an unadvertised CGI response surface.
  It accepts no request-derived paths or commands, performs no DNS lookup or
  remote fetch, reflects no submitted values, ignores forwarding headers, and
  converts unexpected failures to the fixed generic `503` response.
- The endpoint validates an owner-only mode/domain/path configuration, a
  read-only exact-target registry, a versioned Public Suffix List snapshot, and
  a pre-created non-world-accessible inbox directory. Unsafe permissions,
  links, malformed JSON, or missing dependencies fail closed.
- Cheap method, media, size, form, URL, and policy decisions happen before
  storage. A suppressed source returns the same fixed `202` as accepted work
  and creates no queue, rate, diagnostic, or target-probe record. Eligible work
  acquires one of four nonblocking writer slots and then uses the Stage 4B lock,
  rolling rate state, exact target check, atomic replacement, backup, and
  recovery behavior.
- Added `webmentions/inbound_targets.py`. It deterministically generates the
  immutable registry from exact current item documents, accepting only each
  fragment/thread/withdrawn item's canonical page and current item-document
  URL. It supports the 0.3 default surface and 0.4 item templates without
  changing Blynger's declared protocol version. Aliases, pins, frozen versions,
  foreign pages, duplicate IDs, and guessed IDs are excluded.
- The disposable CGI fixture executes the receiver in separate processes and
  proves durable acceptance without a source fetch, duplicate refresh, exact
  page/document membership, silent deny/allow suppression, off/method/media/
  size/form failures, target-probe rate charging, generic configuration and
  registry failure, PSL grouping, writer-slot exhaustion, query non-reflection,
  and queue-directory symlink refusal.
- Validation: 44 focused inbound tests and all 403 Python tests pass. Package
  compilation and repository whitespace checks also pass. No app import, route, manifest advertisement,
  public website file, NFS file, network request, or application version changed.
- Next checkpoint: Stage 4D rehearses the actual the configured Git host CGI path,
  installs a current versioned PSL snapshot, and proves the permission matrix
  while the endpoint remains unadvertised. Any failed privilege or runtime test
  blocks deployment.

### Stage 4D — live NFS permission and behavior rehearsal

- Status: **completed 2026-10-19**.
- The SSH environment has Python 3.11.15. The site owner is a member of the
  site-private group and `web`; `/home/protected` is owner/`web` traversable,
  while `/home/private` is owner-only. Those modes can express the planned
  config/inbox/verified/worker separation.
- The first attempt correctly stopped because the site's former **Apache 2.4
  Static Content** server type returned executable CGI and PHP fixtures as
  source. After the owner selected **Apache 2.4, PHP, CGI**, a fresh shell CGI
  executed successfully. NFS documents `.cgi` execution at
  <https://faq/q/cgi> and the `web` user boundary at
  <https://faq/section/programming/>.
- The real CGI identity was uid/gid `web` with no supplementary group. It could
  read `0640` owner/`web` config and runtime files but could not alter them. It
  could create `0660` inbox data in the narrowly writable `0770` inbox, and
  could neither read nor alter `0700` verified storage or private worker code.
- An owner-side fixture read and validated the CGI-created record, created a
  new owner-owned `0600` verified record, and removed the web-owned inbox copy.
  Direct HTTP requests for protected and private fixture paths returned `404`.
  SSH ownership and the site's `0002` umask remained usable.
- The actual inactive `webmentions.inbound_endpoint` package ran as CGI against
  its real config, exact target registry, queue, and PSL. A valid form POST
  returned generic `202` and created exactly one durable `pending` record
  without fetching its deliberately unreachable source.
- Installed the official Public Suffix List snapshot
  `2026-10-17_18-52-06_UTC` (upstream commit
  `52b71b3c4576ff77450cc7ebcfc7f34a916af3f9`, 338,207 bytes, SHA-256
  `3e6ca639b7ef33f86ec0e6fe9a475857cf2585f28fdf485f38f14d5f00c1c2a4`)
  plus its metadata under `/home/protected/webmentions/config/`, both mode
  `0640` and owner/`web`.
- Left the production directory skeleton with config/runtime `0750`, inbox
  `0770`, and verified/private storage `0700`. No executable exists below the
  web-writable inbox. All public rehearsal scripts and isolated fixture data
  were removed; their URLs returned `404`; the live home page, Blyg page, and
  manifest remained available; and no Webmention endpoint is advertised.
- Stage 4's host boundary is therefore proven. Deployment remains gated on the
  Stage 5 verifier, Stage 6 synchronization, Stage 7 interface, and Stage 8
  adversarial review.

### Stage 5 — inactive incoming structural verifier

- Status: **completed 2026-10-20**.
- Added `webmentions/inbound_verifier.py` as isolated host-worker code. It is
  not imported by the application package root, has no route, and remains
  undeployed and unadvertised. Each scheduled run holds a nonblocking private
  worker lock and processes no more than 20 pending pairs.
- Every untrusted fetch uses the existing address-pinned public transport with
  a five-second timeout, 1 MiB body ceiling, three-redirect ceiling, and a
  maximum of three fetches for one claim. HTML sources must name a JSON
  alternate; JSON sources must be the live item document. The live document's
  asserted full origin and id must resolve exactly to its final default item
  URL or to the source origin's own Blyg 0.4 item template.
- Verification recognizes exactly one relation in protocol priority order:
  Stub, Transclusion, Fork, then Source. Citation display metadata is ignored.
  A Fork succeeds only when the receiver's own registry says the named target
  version is pinned. Ordinary links, wrong pages, mirrored documents, malformed
  identities, invalid templates, oversized author metadata, and unrecognized
  relations fail without retaining fetched bodies.
- Upgraded the owner-generated exact-target registry to schema 2 so it retains
  each target's id, canonical page, current document URL, kind, and known pinned
  versions while preserving the same exact target list used by intake.
- Final records are individual owner-only `0600` JSON files inside a `0700`
  directory. They contain bounded pointer/provenance metadata and fixed error
  codes only—never remote content or exception text. The queue and verified
  store use a provisional/final reconciliation protocol: crashes at either
  boundary recover on the next run, and a duplicate received during a fetch
  remains pending for a fresh verification rather than being hidden by stale
  completion.
- Re-sent pairs update one record. A previously verified relation that is now
  structurally absent becomes `gone`; a transient network failure preserves the
  last verified relationship and records a separate failed-check diagnostic.
  Queue completion is conditional on the exact receipt count the worker processed.
- Hostile fixtures cover duplicate JSON keys, malformed HTML/JSON, missing
  alternates, wrong source pages and item locations, custom 0.4 templates,
  unpinned Forks, oversized metadata, fixed diagnostics, symlink/tamper/size
  refusal, duplicate and update behavior, mid-fetch receipt races, and restart
  reconciliation. Validation: 58 focused inbound tests and all **420** Python
  tests pass; repository whitespace checks pass.
- No app UI, application version, public website file, NFS executable, manifest
  advertisement, live queue, or live verified record changed. Stage 6 may read
  only `phase: final` records and must keep synchronization one-way and
  idempotent.

### Stage 6 — inactive one-way SSH synchronization

- Status: **completed 2026-10-20**.
- The Stage 5 worker can now atomically refresh a checksummed, bounded export
  containing only `phase: final` records. The export is `0600`, contains no
  fetched remote content, and excludes provisional crash-recovery work.
- Added `webmentions/inbound_sync.py` as an inactive module. Its SSH reader can
  read only the fixed path
  `/home/protected/webmentions/verified/export.json`; neither a mention nor any
  imported field can affect the remote command or path. Hostname and username
  are validated configuration values and process arguments are never assembled
  from shell text.
- SSH is noninteractive: batch mode, password and keyboard-interactive
  authentication disabled, identities-only mode, strict host-key checking, and
  fixed connection and whole-process timeouts. Output is read incrementally
  with the same 16 MiB ceiling as the export; stderr and remote exception text
  are not retained or shown.
- The Mac-side `InboundMentionArchive` is a separate `0700` private directory
  with atomic `0600` main and backup files. It validates every record and the
  export checksum before merging. Repeated pulls are idempotent; newer receipt
  counts replace the same logical pair; records omitted by later host snapshots
  remain available locally for offline display. A private cross-process lock
  serializes refresh-and-merge so concurrent background pulls cannot lose one
  another's records.
- A lower receipt count or conflicting content at the same count fails closed.
  Unavailable SSH, timeouts, truncated/malformed/oversized exports, unsafe
  links or permissions, and local corruption never erase the last good records.
  Fixed diagnostic codes are durable, and missing/damaged main state recovers
  from the last good backup while preserving bounded damage evidence.
- Synchronization has no import from or call into Git publication, drafts,
  Reader subscriptions, or public-site generation. It remains a callable data
  path rather than an app-start or publication dependency; Stage 7 will decide
  when the UI invokes it in the background.
- Hostile and recovery fixtures cover fixed command construction, option
  injection, output/time limits, checksum tampering, provisional exclusion,
  repetition, updates, omissions, rollback/conflict, offline behavior, partial
  transfers, unsafe permissions, symlinks, concurrent merges, damaged/missing
  main state, and the verifier-to-export handoff. Validation: 73 focused inbound
  tests and all **435** Python tests pass; repository whitespace checks pass.
- No application version, app UI, public website file, manifest advertisement,
  NFS file, live SSH connection, or live receiver state changed. Public receiving
  remains blocked on Stages 7–9 and the final deployment checkpoint.

### Stage 6E — registry durability and semantic incoming activity

- Status: **completed 2026-10-20** in five bounded code checkpoints:
  `1e17521`, `22c6de8`, `c9945aa`, `526074c`, and compatibility follow-up
  `86cfa67`.
- Exact-target registries now have a checksummed artifact envelope binding them
  to the exact hosted Git commit and its predecessor. The inactive host-side
  store validates before using atomic replacement, keeps a last-good backup,
  confirms the installed digest, treats same-commit retries idempotently, and
  uses Git ancestry supplied by the deployment helper to refuse divergent work
  and prevent a delayed older refresh from replacing a newer registry.
- Successful Blyg publications durably record registry reconciliation work from
  the exact approved commit before publication finalization clears its snapshot.
  The record contains only commit identities, expected digest, timestamp, and a
  bounded diagnostic; the artifact is rebuilt from immutable Git objects on
  every retry. Non-Blyg and unchanged commits correctly create no work.
- The fixed-command SSH installer and single-flight background runner are
  implemented but inactive. SSH failures, timeouts, invalid or lost
  confirmations, crashes, restarts, and successive publications leave durable
  work for idempotent replay. The runner does no authoring or publication work
  and is not wired into the application until the deployment gate supplies the
  reviewed remote helper and configuration.
- Verification records are schema 2, with backward-compatible schema 1 import.
  A temporary fetch failure no longer destroys a last-known verified or gone
  relationship; it updates only the receipt/check diagnostic. Deterministic
  structural removal still produces `gone`, and a later successful check clears
  the transient diagnostic.
- The private inbound archive is schema 2 and now derives a durable semantic
  activity ledger. First verification is `new`, meaningful relationship or
  source-version change is `update`, and confirmed removal is `withdrawal`.
  Receipt counts, check timestamps, transient errors, and identical
  reverification do not create activity. Read state is stored separately from
  the authoritative record and survives restart.
- Failure-injection coverage includes the publication/record boundary, crash
  before atomic install, lost confirmation after install, unavailable SSH,
  restart replay, single-flight overlap, successive publications, same-commit
  retry, delayed older work, divergent history, and legacy record/export/archive
  migration. All **452** Python tests pass; repository whitespace checks pass.
- No application UI, application version, public website file, NFS file,
  endpoint advertisement, live SSH operation, or public receiver state changed.
  Stage 7 may now consume the activity ledger and activate only the local
  background synchronization schedule. Stages 8 and 9 remain mandatory before
  receiver deployment or advertisement.

### Stage 7A — local background synchronization and status API

- Status: **completed 2026-10-20** as a bounded backend checkpoint. Stage 7B
  UI work has not started.
- Blynger now has one single-flight incoming synchronization service. Once
  explicitly enabled, it performs one delayed startup pull, polls every ten
  minutes while the app is open, and accepts an immediate asynchronous wake.
  Repeated wakes cannot overlap SSH work. Shutdown wakes and joins the worker.
- Synchronization remains off by default through the private
  `webmentions.inbound_sync_enabled` setting. Disabled or invalid configuration
  performs no network operation and reports a fixed local diagnostic. This does
  not activate, advertise, or deploy the public receiver.
- The worker uses the existing noninteractive publishing SSH identity and the
  fixed remote export path. It runs outside Studio, Reader, editor, and
  publication locks, so a slow or unavailable host cannot freeze the interface
  or change publication success.
- Token-protected local endpoints now expose a read-only status/activity
  snapshot and request a background refresh. The refresh endpoint returns
  immediately; it never performs SSH in the request thread. No UI consumes
  these endpoints yet.
- Coverage verifies disabled behavior, delayed startup, immediate manual wake,
  non-overlap under repeated requests, shutdown, archive-derived unread status,
  strict configuration typing, and token-protected status/refresh endpoints.
  All **458** Python tests pass; repository whitespace checks pass.
- Next checkpoint: Stage 7B may render the already-approved compact Thicket
  incoming UI and persist read state. Stop for user review before proceeding.

### Stage 7B — incoming Thicket interface and exact read state

- Status: **completed 2026-10-20** in commit `d41c61e` (`Show incoming
  Webmentions in Thicket`). Stage 7C has not started.
- Thicket now combines incoming semantic activity with the existing outgoing
  ledger in reverse chronological order. The compact two-line rows, initial
  three-record view, expandable history, 24-hour OUT/IN dashboard, outgoing
  failure filter, pause control, and click-to-copy behavior remain intact.
- Incoming rows show the local published title when available, verified author
  and source host, relation type, activity time, withdrawal state, and an
  explicit read indicator. A verified source page opens only through the
  existing external-browser boundary after another HTTP(S) check. Incoming
  metadata is built with text nodes rather than interpreted HTML.
- The IN dashboard distinguishes not enabled, not yet synchronized,
  unavailable, stale last-known data, and a confirmed empty archive. The
  darker-blue Thicket tab is driven only by the backend semantic unread count;
  merely opening Thicket acknowledges nothing.
- Archive schema 3 replaces the mutable unread Boolean with a private durable
  map of the exact acknowledged semantic fingerprint. A later meaningful
  update or withdrawal therefore becomes unread even if its predecessor was
  acknowledged. Duplicate receipts and transient diagnostics remain quiet.
  Schema-2 archives migrate compatibly, and the read ledger survives restart
  and ordinary backup recovery.
- `BLOCK` is intentionally absent. The fixed, protected owner-policy write
  mechanism required to change the NFS denylist has not been implemented or
  reviewed; 7B does not pretend that a local button can perform that privileged
  operation.
- Incoming synchronization remains disabled by default and no public receiver,
  endpoint advertisement, scheduled NFS task, live inbound test, publication,
  Reader subscription, draft, or public-site output changed.
- Validation: all **462** Python tests pass. Focused local API, security,
  archive migration/recovery, semantic activity, mixed-ledger, hostile-label,
  safe-URL, and outgoing-regression checks pass. JavaScript syntax, editor
  safety, Reader UI, new Thicket UI, and repository whitespace checks pass.
- Stage 7C acceptance criteria: perform the separate regression/security pass,
  inspect the rendered compact layout and keyboard behavior, exercise every
  empty/stale/error state, confirm untrusted fields never reach HTML or unsafe
  navigation, verify publication/Reader isolation, and record any defect as a
  bounded fix. Do not deploy or advertise the receiver during 7C.

### Stage 7C — regression and security verification

- Status: **completed 2026-10-20** in this checkpoint commit. No product-code
  defect was found and no behavior was expanded.
- All **463** Python tests pass, including the full inbound archive, semantic
  activity, synchronization, local API, publication, Reader, and privileged-UI
  security suites. Repository whitespace checks pass.
- The current application was reopened against the matching Stage 7 backend and
  the real Thicket screen was inspected without changing either saved draft.
  The 24-hour boxes remain one compact row, the ledger remains two lines per
  entry, only the most recent three appear initially, and the disabled incoming
  state displays an em dash plus an explicit explanation rather than a false
  zero.
- Keyboard behavior was exercised in the running application. Enter and Space
  both activate an outgoing row and copy the bounded JSON diagnostic; the prior
  clipboard contents were restored after each check. Native controls retain
  their ordinary keyboard behavior.
- Empty, unavailable, stale-last-good, current-empty, and unread incoming states
  are covered at the service and presentation-helper boundaries. First
  verification, semantic update, withdrawal, duplicate reverification,
  transient failure, restart persistence, and later-activity-after-read remain
  covered by the archive regression suite.
- Incoming labels are transferred only through bounded JSON fields and rendered
  with text nodes/`textContent`. Incoming navigation rechecks the URL as
  HTTP(S) at the action boundary and then uses Blynger's existing external-open
  bridge. A withdrawn record has no verified `source_page`, so it cannot be
  presented as a currently verified link. No incoming value constructs HTML,
  a DOM identifier, local path, shell command, Reader subscription, draft, or
  publication action.
- Incoming synchronization remains a separate single-flight background service
  outside Reader and publication locks. Its unavailable and stale states keep
  the last-good archive, while publication and Reader regression coverage
  remains green.
- `BLOCK` remains intentionally absent pending the separately reviewed
  privileged owner-policy write path. No public endpoint, NFS task, receiver
  advertisement, live inbound request, publication, or version number changed.
- Next checkpoint: Stage 8 is the mandatory pre-deployment security gate.

### Stage 8D — live deployment rehearsal and disable proof

- Status: **completed 2026-10-21**; Stage 8 is complete. Production remains
  blocked on the independent Stage 9 audit.
- The real NFS host ran the reviewed fixed registry installer and verifier
  command. Local and remote hashes matched. The verifier completed an empty
  bounded run; no scheduled task was activated.
- A disposable policy-off Python CGI returned generic `503`, `no-store`, and
  `Retry-After` without queueing. The public wrapper was then removed and the
  Blyg manifest remained unadvertised.
- The actual web PHP runtime was 8.1.34-nfsn2 (NFGI), distinct from the patched
  8.3.36-nfsn1 CLI. The site now permanently denies PHP-like extensions at
  Apache level. A disposable PHP probe changed from execution to 403 while
  Python CGI and static content continued to work.
- The rehearsal caught a group-inheritance defect in atomic registry refresh.
  `RegistryArtifactStore` now preserves an administrator-provided setgid
  directory. The live configuration directory is 2750 and current/backup
  registries are owner-written, web-group-readable 0640. Current, repeated, and
  delayed-older installs proved install/already/superseded behavior.
- Homepage, post, site feed, Blyg feed, manifest, content types, cache
  validators, hosted Git commit, and `.git` denial passed after the hosting
  change. All disposable routes and files were removed.
- Inactive runtime/configuration and owner-only helper code remain for Stage 9
  inspection. Receiver policy is off; there is no public endpoint, advertised
  endpoint, verifier schedule, local inbound synchronization, or live inbound
  test.

### Stage 9 — independent security audit

- Status: **completed 2026-10-21 after remediation.** The initial independent
  read-only review targeted `4dd47df` and traced every hostile-input,
  persistence, network, SSH, UI, publication, and deployment boundary.
- Three independently reproduced defects were fixed in separate commits:
  `50aaea2` makes the outgoing queue recoverable and cross-process durable;
  `fe2a7ce` bounds verified-record retention with the intake ledger; and
  `da5f2f6` refuses the Blyg 0.4 generation-source relation from 0.3 documents.
- The independent remediation review then caught a prune/reappearance conflict
  created by the first retention fix. `498459c` makes exports strictly ordered
  authoritative snapshots, removes expired Mac archive rows, rejects rollback
  and altered replays, and proves both unchanged and removed-relation
  recurrences end to end.
- No SSRF/rebinding bypass, remote HTML/script execution, mention-derived shell
  or path use, automatic authoring action, or publication-success coupling was
  found.
- All **506** Python tests pass. The full classification, evidence, remaining
  defense-in-depth item, and Stage 10 blockers are recorded in
  `docs/WEBMENTIONS_SECURITY_REVIEW.md`.
- Production remains inactive. Stage 10 must wire and prove exact-commit
  registry refresh before enabling the receiver, then configure the scheduled
  verifier, enable local synchronization, advertise the endpoint last, and run
  the bounded live test.

### Stage 9.5 — Save/Stage publication-privacy gate

- Status: **completed 2026-10-22.** A separate high-level review reproduced
  both defects below using disposable sites; no real content or deployment was
  changed.
- **9.5A — interruption-safe preparation (`7b21c50`):** preparation now works
  in an isolated state snapshot. Every intermediate disk save retains the
  complete authoritative private state; exceptions and process interruptions
  cannot persist the filtered draft collection. Reopening regressions preserve
  unrelated private Posts and Openers.
- **9.5B — private Series isolation (`5886b11`):** staging an installment builds
  its automatic Series dependency from the published Series page (or the
  Series record when it is new), never from an unstaged private edit. After the
  exact dependency is hosted, the private Series prose is restored, unstaged,
  and rebased onto the new managed list. Explicitly staging the Series page
  still publishes that edit normally.
- The invariant now has direct end-to-end coverage: **Save remains private;
  only Stage authorizes writing for Review & publish.** The complete suite
  passes: **510 tests, 0 failures**.

### Stage 9.6 — subsequent adversarial activation gate

- Status: **complete; focused re-audit passed 2026-10-23.** Inbound
  Webmentions remain disabled pending the controlled Stage 10 activation.
- A 2026-10-22 adversarial review confirmed the existing Save/Stage fixes and
  complete 510-test suite, found no evidence of compromise, and confirmed that
  the receiver, synchronization, schedule, and endpoint advertisement remain
  inactive.
- **9.6A — poisoned-item isolation:** strictly bound author-field types, nesting
  depth, and lengths. A malformed or recursive item must fail by itself while
  later mentions and exports continue. Regress with a hostile item followed by
  a valid one.
- **9.6B — deletion semantics:** preserve structured HTTP status information;
  treat confirmed 404/410 sources as withdrawals while retaining and retrying
  verified relationships across temporary network, rate-limit, and server
  failures. Regress both paths.
- **9.6C — hosting trust boundary:** `/home/protected` was observed as
  group-writable (`0770`) with the writable inbox group. Move owner-executed
  helpers and trusted configuration beneath a provider-supported,
  owner-controlled ancestor chain; keep inbox data physically separate; update
  registry refresh; and prove on the live host that the web identity cannot
  replace any trusted ancestor, helper, or configuration. Do not blindly change
  the shared parent without checking the configured Git host requirements.
- **9.6D — focused re-audit:** rerun the three adversarial cases, the full suite,
  and the inactive-deployment checks. Record the evidence before opening the
  Stage 10 activation gate.
- **Completed checkpoints:** poisoned-item isolation is committed at `ba12d07`,
  deletion and durable retry semantics at `d24a122`, and the hosting trust
  boundary at `5b0147b`.
- **9.6D evidence:** 62 focused verifier, transport, registry, and NFS deployment
  regressions passed; the complete Python suite passed **522 tests with 0
  failures**; JavaScript syntax plus Editor, Reader, and Thicket checks passed;
  and `git diff --check` passed.
- The actual NFS boundary remains fail-closed: owner-executed code is under
  owner-only `/home/private`, `/home/protected` retains sticky mode `1770`, and
  the receiver CGI and disposable rehearsal CGI are absent. The public home,
  Blyg index, and manifest returned 200 and do not advertise Webmentions.
- The dormant verifier module on NFS predates the 9.6A/9.6B fixes. This is not
  reachable or scheduled, but Stage 10 must deploy and hash-confirm the exact
  reviewed runtime before installing the verifier runner, receiver, schedule,
  synchronization, or endpoint advertisement.
- Full findings and rationale are recorded in
  `docs/WEBMENTIONS_SECURITY_REVIEW.md`.

### Stage 10 — controlled activation and live interoperability

- Status: **complete 2026-10-24.** The remaining work is Stage 11
  operational review and Stage 12 release, not receiver functionality.
- Installed and hash-confirmed the reviewed runtime in both the owner-only and
  web-readable runtime locations. Installed the public Python CGI wrapper, the
  owner policy helper, and the silent bounded verifier runner. The NFS task
  exists as `blyngerwm`; successful empty runs produce no output, preventing
  routine scheduled-task email.
- Receiver policy is **denylist** with an empty list. The owner Settings path
  can select Off/Open/Deny list/Allow list, and verified inbound Thicket rows
  expose the confirmed `BLOCK` action only in deny-list mode.
- Enabled private Mac synchronization. It runs outside editor/publication locks,
  uses bounded noninteractive SSH, preserves last-known-good state, and reports
  current availability without delaying publication.
- Published exact commit `3e93672fbb86cea4a3fc62b98fe84256909bc8af`
  to advertise the endpoint in the Blyg manifest, both feeds, and generated
  Blyg pages. No numbered page changed in that publication.
- At the author's direction, receiver discovery is site infrastructure rather
  than a forward-only design choice. A second byte-checked publication,
  `bbbbb0e189ee7bf09f007893f42a5ee7682285e4`, added only the managed
  `rel=webmention` link to 114 public HTML pages. The exact target registry was
  confirmed current at both commits.
- The first live intake probe exposed two NFS cross-identity lock defects. The
  shared inbox now requires set-group mode `2770` (`421ffb0`), and lock files
  receive mode `0660` only when created and are thereafter validated without an
  ownership-protected chmod (`07c1c47`). Both defects failed closed with generic
  503 responses; no unverified activity entered Thicket.
- Live interoperability then passed: the receiver returned 202, the owner
  verifier confirmed a real self-transclusion from
  `/blyg/t/0wfws68ydg9va4crab9vzy9h77/` to
  `/blyg/f/437byvnta71wy3866a0xk93wqh/`, private synchronization imported it,
  and Thicket reported one new unread verified transclusion.
- The host scheduler was then proven independently of a manual worker run. It
  processed a second receipt at 2026-10-24 14:34:55 UTC; the protected record
  remained verified and advanced from receipt count 1 to 2. A subsequent Mac
  synchronization advanced the local record to count 2 while retaining exactly
  one activity and one unread item, proving that reverification does not create
  a duplicate notification. The temporary execution probe was removed and the
  `blyngerwm` task was restored to the permanent owner-only verifier runner.
- The emergency Off test returned generic 503 with `Retry-After: 3600`; policy
  was restored and re-read as deny-list mode. Public GET remains 405.
- Final regression evidence: **537 Python tests passed**; JavaScript syntax,
  Editor, Reader, and Thicket suites passed; and `git diff --check` passed.

### Stage 11 — operational review

- Status: **complete 2026-10-24.** No content was published and receiver policy
  remained in deny-list mode.
- Public health checks returned 200 for the home page and Blyg index. The home
  page and Blyg manifest advertise the expected HTTPS receiver. Public GET on
  the receiver returns 405 with `no-store`, HSTS, content-type, framing,
  referrer, permissions, and content-security protections.
- A fresh protected export generated by the continuing host schedule
  synchronized successfully. The private archive contains two verified
  semantic activities and one expected terminal invalid-source record. Both
  activities are acknowledged, with no duplicate unread activity and no sync
  error.
- The outgoing archive is writable and unpaused: eight deliveries, with zero
  pending, retrying, rejected, abandoned, or missing-endpoint records and no
  recovery warning.
- A post-activation review identified one genuine availability weakness: the
  single resolver slot could remain occupied after a DNS deadline and delay
  every unrelated Webmention lookup. Bounded network requests now use a small
  fixed resolver pool and share same-host work. Regression coverage proves a
  timed-out hostname cannot block an unrelated hostname and concurrent callers
  do not duplicate one hostname's lookup.
- The shared inbox remains intentionally set-group and writable by the receiver
  and verifier identities. Trusted executable code, configuration, and verified
  output remain outside it behind the rehearsed owner-controlled ancestor
  boundary. Compromise of the receiver identity could damage unverified intake
  availability, but cannot install trusted code or manufacture a verified
  relation; this is recorded as residual defense-in-depth rather than an
  activation bypass.
- HTTP sources remain an explicit interoperability choice. Verification proves
  the relation present at retrieval time but HTTP does not authenticate its
  origin against an on-path attacker. HTTPS remains preferred; this is not an
  SSRF or code-execution route.
- Complete regression evidence: **539 Python tests passed**; JavaScript syntax,
  Reader UI, and Thicket UI tests passed; and `git diff --check` passed.

### Stage 12 — release checkpoint

- Status: **complete 2026-10-24.** Blynger's application version is `0.13.0`;
  the published Blyg protocol output intentionally remains `0.3`.
- README, conceptual documentation, Openers guidance, changelog, and application
  metadata agree on the release. The changelog leads with the user-visible
  sending, receiving, Thicket, and policy behavior.
- The final gate retained the Stage 11 live-health evidence and passed all
  **539 Python tests**, JavaScript syntax, Editor safety, Reader UI, Thicket UI,
  release-metadata consistency, and `git diff --check`.
- Webmentions implementation is complete. Later work on Blynger's own writing
  as a Reading source and the broader Thicket/UI redesign is separate product
  work, not another Webmentions activation stage.

### Deferred after Webmentions — own writing in Reading

- Add “your own blyg” as a Reading source so published Posts and Openers can be
  used like other Blyg items without subscribing to the public site.
- Consider context-menu shortcuts on a local Post or Opener for **Stub** and
  **Transclude** into a new Post or new Opener, plus the already-planned Quote,
  Link, and Fork-from-a-pin actions. Keep this out of the Stage 10 activation
  change set so the new authoring path receives its own UX and safety review.
