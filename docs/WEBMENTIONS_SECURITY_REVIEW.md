# Blynger Webmentions — Stage 9 independent security review

Status: **passed. The original Stage 9 review passed after three initial defects
and one remediation regression were fixed. A subsequent adversarial review
found two new activation blockers and one deletion-handling defect; Stage 9.6
fixed all three and the focused re-audit passed on 2026-10-23. Stage 10 may now
begin, but receiving remains inactive until every deployment gate below is
completed.**

Reviewed: 2026-10-21. Initial review target:
`4dd47dfe9c9341d64f68c3f697dec37e609037c3`.

## Method

A fresh reviewer who had not implemented the Webmention stages traced each
trust boundary from hostile form input through queueing, network verification,
protected export, SSH synchronization, local archive, Thicket rendering,
publication reconciliation, target-registry refresh, and outbound delivery.
The reviewer inspected the actual source and deployment helpers, reproduced
suspected failures using disposable local data, and made no code, host, or
configuration changes.

The implementation owner then fixed each confirmed defect in a separate commit
with a focused regression. The independent reviewer rechecked those commits
before this gate was closed.

## Confirmed findings and resolution

### High — outgoing work could be lost when the main outbox disappeared

The outbox ignored a valid backup when its main file was absent and could reopen
as an empty writable queue after publication reconciliation had already been
completed. It also lacked directory durability and cross-process locking.

Resolved in `50aaea2`:

- the main and backup now both contain the latest committed queue state;
- a missing main recovers from the verified backup;
- atomic replacement fsyncs the containing directory;
- a validated owner-only file lock serializes separate Blynger processes;
- regressions cover missing-main restart, unsafe locks, and a deterministic
  two-process overwrite attempt.

### High — verified inbound storage could eventually freeze exports

The intake queue pruned old terminal relationships, but derived verification
files accumulated forever. At 2,001 lifetime files the bounded 2,000-record
export failed on every run.

Resolved in `fe2a7ce`:

- verification retention now follows the authoritative bounded intake ledger;
- only records whose intake relationship has already been deliberately pruned
  are removed;
- record deletion is directory-durable;
- a bounded rollover regression proves that current records remain exported
  after the oldest terminal relationship expires.

### Medium — Blyg 0.3 could claim a 0.4-only generation-source relation

The verifier accepted `generated[].sources[]` from a document declaring Blyg
0.3 even though generation-source Webmentions are a 0.4 feature.

Resolved in `da5f2f6`: the `source` relation is considered only for a document
declaring Blyg 0.4, with a negative 0.3 regression.

### High — the first retention fix could block a later recurrence

The independent remediation review found that deleting an expired host record
while retaining its old Mac archive row allowed a later recurrence to reuse
receipt count 1 and conflict permanently with the stale local count 1.

Resolved in `498459c`:

- each protected export advances a strictly increasing revision, even for
  multiple exports in the same clock second;
- a newer export is an authoritative snapshot, so the Mac removes deliberately
  expired records and their activity/read state;
- lower revisions and altered same-revision replays fail closed;
- a damaged installed export is preserved rather than overwritten with an
  unknowable or lower revision;
- an end-to-end regression covers verification, pruning, synchronization,
  count-1 recurrence, another prune, and recurrence without the relation.

## No issue found

- No SSRF or DNS-rebinding route was found. All resolved addresses must be
  global, the checked address is pinned, TLS remains bound to the hostname, and
  every redirect is revalidated under one total deadline.
- No mention-derived shell command, remote command argument, filesystem path,
  draft, Reader subscription, publication, or other privileged authoring action
  was found.
- Incoming labels remain bounded metadata rendered as text. Opening a verified
  source revalidates it as HTTP(S) at the action boundary; remote HTML is never
  inserted into Thicket.
- The public CGI performs no fetch. It applies fixed body, URL, writer, queue,
  and rate limits before exact-target admission and returns generic errors.
- Exact publication commits, not mutable working files, drive outgoing
  reconciliation and target-registry artifacts. Webmention failure remains
  separate from publication success.
- Export, authoritative archive snapshot, registry, SSH command, rollback,
  replay, crash, and last-good
  recovery boundaries remained intact in review and regression testing.

## Stage 10 activation blockers

These are planned deployment work, not accepted residual vulnerabilities:

1. Wire the existing `RegistryRefreshWorker` into the running application (or
   an equivalently durable owner-side runner), wake it after publication, and
   prove that its SSH work is outside editor/publication locks. The receiver
   must not be enabled while its exact-target registry can become stale.
2. Deploy and hash-confirm the exact reviewed verifier runtime and owner runner.
   The dormant NFS verifier module predates Stage 9.6 and must not be scheduled
   or made reachable.
3. Install the reviewed public CGI wrapper, choose the initial receiver policy,
   and keep the already-tested PHP denial in force.
4. Configure the nonoverlapping ten-minute verifier task and bounded operational
   monitoring on the configured Git host.
5. Enable local inbound synchronization only after the protected export exists.
6. Advertise the endpoint only after the preceding steps pass, then perform one
   bounded live interoperability test and demonstrate the disable path again.

Parent ownership and permissions for every protected deployment path must be
rechecked during activation. Stage 11 post-deployment review and Stage 12
release/documentation work remain mandatory.

## Verification

- The independent reviewer reproduced the three original defects and the
  retention-remediation regression in disposable fixtures before fixes.
- Focused regressions passed after each fix, and the independent final review
  passed at `498459c`.
- The complete Python suite passed: **506 tests, 0 failures**.
- `git diff --check` passed.
- No public receiver, endpoint advertisement, verifier schedule, inbound sync,
  or live inbound test was activated during Stage 9.

## Subsequent adversarial review — Stage 9.6 gate

Reviewed: 2026-10-22. The reviewer ran additional disposable adversarial tests
and inspected the inactive the configured Git host deployment without changing files,
settings, or public behavior. The complete 510-test Python suite and the
Save/Stage regressions passed. No evidence of compromise was found.

### High — a group-writable ancestor can undermine protected helper code

The individual Webmention directories have sensible permissions, but
`/home/protected` was observed as group-writable (`0770`). Its group matches the
writable inbox group and it has no sticky bit. A process with that group access
could potentially rename and replace the entire `webmentions` directory even
though files inside the original directory are owner-only. Registry refresh
currently executes a helper from that directory through the owner's SSH
account.

This is a permissions weakness, not a demonstrated unauthenticated remote
exploit. Before activation, owner-executed helpers and trusted configuration
must live beneath an owner-controlled ancestor chain that the web identity
cannot rename, replace, or write. The complete real path, ownership, modes, and
symlink boundaries must be checked on the actual host; checking only the leaf
files is insufficient.

### High — a deeply nested author object can poison a verifier batch

A valid-size JSON item with an approximately 3 KB deeply nested `author` object
can pass the byte-size check and then raise an uncaught `RecursionError` while
being copied. The item remains pending, so repeated scheduled runs can fail on
the same record before later mentions or export updates are processed.

Before activation, author data must receive explicit type, nesting-depth, and
field-length validation. Malformed remote data, including recursion failures,
must become an item-specific terminal failure while the worker continues with
later entries. A regression must place a hostile item immediately before a
legitimate one and prove the legitimate mention is still processed.

### Medium — a deleted source can remain displayed as verified

After a relationship is verified, an HTTP `410 Gone` response currently becomes
an undifferentiated fetch failure. The old relationship remains `verified` and
the pending work is removed, so a deliberately deleted source can continue to
appear valid.

The network layer must preserve structured HTTP status information. Confirmed
`404` and `410` responses should withdraw the relationship; timeouts, DNS
failures, `429`, and server errors should remain temporary failures with bounded
retry behavior. Coverage must include `verified -> 410 -> withdrawn` and a
temporary failure that does not erase a valid relationship.

### Stage 9.6 remediation plan

1. **9.6A — poisoned-item isolation:** bound author structure and convert every
   malformed item into an isolated failure without aborting the batch.
2. **9.6B — deletion semantics:** carry HTTP status through the transport,
   distinguish withdrawal from temporary failure, and test both paths.
3. **9.6C — hosting trust boundary:** establish a provider-supported layout
   that physically separates web-writable inbox data from owner-executed code
   and trusted configuration; update registry refresh and rehearse the complete
   ancestor-chain permissions using the actual host identities.
4. **9.6D — focused re-audit:** rerun all three adversarial cases, the complete
   regression suite, and the inactive-deployment checks. Stage 10 may begin
   only after this gate passes.

## Stage 9.6 focused re-audit result

Reviewed: 2026-10-23. Result: **passed; Stage 10 gate opened without activating
receiving.**

- The hostile, deeply nested author fixture becomes one bounded
  `invalid_document` result and a following legitimate mention still verifies.
  Malformed remote content is isolated; record or queue write failures still
  escape as operational failures.
- A `404` or `410` on the actual notified source becomes a withdrawal. The same
  status on a supporting alternate document is not misclassified as deletion.
  Temporary failures retain the last verified relationship and a durable,
  bounded retry schedule across restart while later due work continues.
- On the actual NFS account, owner-executed code and helpers are beneath
  owner-only `/home/private`; `/home/protected` is owner-controlled with sticky
  mode `1770`; the web-writable inbox remains separate; and the installed
  registry helper's hash matches the reviewed deployment copy. Its live
  fail-closed boundary check passed.
- The Stage 9.6C actual-web-identity rehearsal proved that the web identity can
  write the disposable inbox while it cannot write or rename trusted entries or
  read owner-only code. All disposable public and protected fixtures were
  removed. The focused re-audit confirmed that both the receiver CGI and the
  rehearsal CGI remain absent.
- Public health checks returned 200 for the home page, Blyg index, and manifest;
  none advertised Webmentions. The absent receiver and rehearsal endpoints
  returned 404. No public receiver, schedule, inbound synchronization, endpoint
  advertisement, or live inbound test was enabled.
- The dormant NFS verifier module is older than the Stage 9.6A/9.6B reviewed
  runtime. Because it has no public wrapper or scheduled runner, this is an
  activation prerequisite rather than a current exposure. Stage 10 must deploy
  from the exact approved commit and hash-confirm it before enabling any inbound
  component.
- Focused regressions: **62 passed**. Complete Python suite: **522 passed, 0
  failed**. JavaScript syntax and Editor, Reader, and Thicket checks passed.
  `git diff --check` passed.

Resolution commits: `ba12d07` (poisoned-item isolation), `d24a122` (deletion and
durable retry semantics), and `5b0147b` (hosting trust boundary).

## Stage 10 activation evidence

Activated: 2026-10-24. The reviewed runtime and fixed owner helpers were
installed and hash-confirmed before endpoint advertisement. The receiver is a
Python CGI; PHP-like extensions remain denied by Apache.

- Trusted executable code remains below owner-only `/home/private`. The public
  wrapper imports the matching read-only runtime copy beneath
  `/home/protected/webmentions/runtime/current`. Configuration and the exact
  target registry are owner-written and web-group-readable; verified exports
  remain owner-only.
- The activation rehearsal found a shared-inbox ownership failure that the
  single-identity tests could not reproduce. The queue directory now requires
  set-group mode `2770`, and both owner and web identities inherit its web
  group. A second failure showed that reopening the other identity's valid lock
  must not call chmod. Shared locks are now created atomically at `0660` and
  subsequently require an exact safe mode without mutation. Both failures
  returned generic 503 and accepted no unverified activity.
- Focused lock and deployment regressions pass. Installed runtime and runner
  hashes match their reviewed local files. The verifier is bounded,
  nonoverlapping, and silent on successful runs; failure output remains
  available to the hosting task monitor.
- Endpoint discovery was published only after the runtime, policy, schedule,
  registry refresh, and Mac synchronization were ready. Sitewide advertisement
  was byte-checked to add only the managed discovery link.
- A live valid Blyg self-transclusion returned 202, verified structurally,
  entered the protected export, synchronized to the private Mac archive, and
  became one unread Thicket activity. A deliberately unsuitable HTML source
  produced a terminal `invalid_source` record and no activity, demonstrating
  that intake acceptance alone does not grant display trust.
- Automatic operation was proven with a queued duplicate left for the NFS
  scheduler rather than a manual verifier invocation. The scheduled run at
  2026-10-24 14:34:55 UTC advanced the verified record's receipt count from 1
  to 2. Local synchronization preserved a single semantic activity and one
  unread item, so repeated verification cannot manufacture a new notification.
  The disposable execution probe was removed and the task again invokes the
  reviewed owner-only verifier directly.
- The Off path returned generic 503 and `Retry-After: 3600`; deny-list mode was
  then restored and confirmed. Public GET returns 405.
- Complete post-activation regression evidence: **537 Python tests passed**;
  JavaScript syntax, Editor, Reader, and Thicket tests passed; and
  `git diff --check` passed.

Stage 10 activation is not a substitute for Stage 11 operational review or the
mandatory Stage 12 release checkpoint.

## Stage 11 operational review

Reviewed: 2026-10-24. Result: **passed after one availability remediation.**

- Scheduled verification continued after activation and produced a fresh
  protected export. Local synchronization was current with two verified
  activities, one expected terminal invalid-source record, no duplicate unread
  activity, and no synchronization error.
- Outgoing delivery remained healthy: eight delivered records and zero pending,
  retrying, rejected, abandoned, or missing-endpoint records.
- Public discovery and receiver method/security headers remained correct.
- A post-activation review confirmed that one DNS lookup surviving its caller's
  deadline could retain the single global resolver slot. The transport now uses
  a fixed four-slot pool, shares concurrent same-host work, preserves the total
  deadline, and prevents one stalled hostname from blocking unrelated work.
- The set-group shared inbox is intentionally the only cross-identity writable
  area. Owner-executed code, trusted configuration, and verified output remain
  outside that area. Receiver-identity compromise could disrupt unverified
  intake state but cannot create a verified relationship or replace trusted
  executables; this remains a documented defense-in-depth limitation.
- HTTP remains accepted for Webmention interoperability. Such relations are
  verified against retrieved content but do not receive HTTPS transport
  authenticity; HTTPS is preferred.
- Full regression evidence: **539 Python tests passed**; Reader and Thicket
  JavaScript checks passed; `git diff --check` passed.

## Stage 12 release checkpoint

Completed: 2026-10-24. Blynger `0.13.0` retains Blyg protocol output `0.3` and
passes the complete 539-test Python suite, JavaScript syntax, Editor safety,
Reader UI, Thicket UI, release-metadata consistency, and `git diff --check`.
No activation gate or recorded residual risk was removed for the release.

