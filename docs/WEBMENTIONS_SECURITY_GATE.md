# Blynger Webmentions — Stage 8 security gate

Status: **Stages 8A-8D complete; production activation remains blocked on the
independent Stage 9 audit.** This is the implementer's predeployment review.

Reviewed through the Stage 8D checkpoint plus the documented PHP2Shell
precheck. No public receiver route, verifier schedule, inbound synchronization,
or endpoint advertisement remains active after this review.

## Security objective

A hostile Internet sender may spend only bounded public-host resources to lodge
an untrusted claim. Only an owner-side worker may fetch that claim's source and
turn it into bounded metadata. Only the private Mac may import that metadata,
and imported data may never become executable content, a filesystem path, a
subscription, a draft, or a publication action.

Loss of the receiver, queue, worker, export, synchronization, or registry
refresh must not prevent the static site from serving or Blynger from
publishing. A receiver-disable operation must not require changing public
content or Git history.

## Assets and invariants

| Asset | Required invariant |
| --- | --- |
| Static site and Git publication | Public intake and verification cannot edit, delete, or delay it. |
| Drafts, Reader state, and local configuration | Never reachable from the public host or derived into a remote command/path. |
| Exact-target registry | Derived from the exact hosted commit; owner-written; monotonically installed; last-good survives failure. |
| Pending intake queue | Bounded, durable, non-executable, and writable only where required. |
| Verified export | Owner-written bounded metadata only; no hostile response body is retained. |
| Local incoming archive | Validated, private, atomic, last-known-good, and independent of publishing. |
| SSH identity and host trust | Fixed configuration only; no interaction prompts and no mention-derived arguments. |
| Thicket UI | Text-only presentation of bounded fields; navigation accepts only revalidated HTTP(S) URLs. |

## Trust boundaries and data flow

1. **Internet to public CGI intake.** `webmentions/inbound_endpoint.py` accepts
   only a bounded form POST. `inbound_contract.py` normalizes the two URLs,
   applies owner policy and rate budgets, and `inbound_queue.py` durably records
   one unverified pair. This boundary does no DNS lookup or fetch.
2. **Queue to owner verifier.** `inbound_verifier.py` reads pending pairs and
   uses `reader_network.fetch_bounded` for DNS-checked, address-pinned,
   redirect-revalidated fetches. It retains only validated structural metadata.
3. **Verifier to protected export.** Final records are strictly validated,
   sorted, checksummed, size-limited, and atomically replaced.
4. **Protected host to private Mac.** `inbound_sync.py` executes one fixed SSH
   command to read one fixed file, validates the complete export, and merges it
   into a private last-known-good archive.
5. **Archive to local UI.** `app.py` exposes data only through the token- and
   host-protected loopback API. The frontend renders incoming values as text;
   opening a link rechecks that it is HTTP(S).
6. **Publication to target registry.** `core.py` builds an artifact from the
   exact approved Git commit. `inbound_registry_refresh.py` sends it to one
   fixed owner helper; `inbound_registry.py` refuses rollback and unrelated
   history and atomically preserves the previous registry.
7. **Published references to remote endpoints.** `planning.py`, `outbox.py`,
   `delivery.py`, and `service.py` create durable events only after successful
   publication and discover/deliver through the same public-address guard.

## Attack-surface inventory

| Surface | Hostile input or failure | Existing control | Stage 8 disposition |
| --- | --- | --- | --- |
| CGI method, headers, length, and body | Malformed form, duplicate fields, reflection, oversized or partial body | 8 KiB declared/read limit, exact media type and fields, generic no-store responses | Adversarial parser and short-read tests required |
| Source policy | Spoofed domain, policy probing, allow/deny abuse | IDNA-normalized hostname policy; suppressed sources receive indistinguishable 202 and create no record | Test subdomains, Unicode, and response indistinguishability |
| Target acceptance | Enumeration, aliases, invented IDs, stale registry | Exact owner-written registry membership under the full Blyg origin | Test every excluded target class and registry failure |
| Rate and capacity state | Flooding, duplicate spam, lock starvation, disk exhaustion | Peer/host/domain/global buckets; writer slots; pending/record limits; fail-closed storage | Concurrency, exhaustion, corruption, and recovery tests required |
| Public suffix grouping | Crafted hostname broadens or evades bucket | Versioned immutable PSL; conservative fallback | Test wildcard, exception, IDNA, IP, and unknown suffix cases |
| DNS and HTTP fetch | SSRF, rebinding, redirects, mixed public/private DNS, large body | Reject any non-global answer, pin checked address, TLS hostname verification, revalidate every redirect, bounded body/fetch count | Existing SSRF fixtures plus total-deadline work described below |
| Blyg parsing | Duplicate keys, deep/large JSON, false relation, hostile author data | Strict JSON, structural/location checks, relation priority, bounded author and record | Add recursion/depth, alternate-link, origin, pin, and hostile-metadata matrix |
| Queue-to-record transition | Crash between provisional record and queue completion | Provisional/final reconciliation and idempotent queue completion | Inject every persistence-boundary failure |
| Verified export | Truncation, tampering, replay, conflicting record | Strict schema, checksum, ordering, record and byte limits; local conflict rejection | Test rollback/replay semantics and last-good preservation |
| SSH synchronization | Command injection, prompts, hang, oversized output, overlap | Fixed command/path, validated host/user, argv invocation, BatchMode, strict host key, hard wall-clock deadline, single background loop | Test hostile configuration and process boundaries |
| Local archive/UI | HTML/script/path injection, unsafe URL opening, repeated unread activity | Strict record validation, semantic fingerprint, text rendering, action-boundary URL validation | Re-run UI injection/navigation tests with hostile fixtures |
| Registry refresh | Crash, uncertain result, delayed old install, corrupted receipt | Durable exact-commit work, idempotent receipt, ancestry/rollback checks, atomic last-good | Existing failure injection retained; add remote-helper review |
| Outbound discovery/delivery | SSRF, unsafe endpoint, retry flood, response abuse | Same pinned fetch transport, endpoint guard, bounded POST response, durable retry policy | Re-run SSRF/redirect/retry tests as one gate |
| Host permissions | Public download/write/execute crossover | Separate public/protected/private locations; no web-writable executable path | Repeat permission rehearsal at deployment |
| PHP-capable Apache profile | Unneeded vulnerable runtime exposed beside Python CGI | NFS currently supplies fixed `8.3.36-nfsn1`; hosted tree has no PHP files | Remove or deny PHP execution before activation and regression-test Python CGI/static site |
| Disable/recovery path | Receiver failure affects static site | Policy `off`; unadvertised endpoint; static publication independent | Demonstrate disable without Git/public-content change |

## Findings after 8A

### Confirmed deployment blocker: unnecessary PHP-capable surface

The Stage 4D NFS profile supports both PHP and CGI although Blynger needs only
Python CGI. The installed NFS 8.3 runtime is patched for CVE-2026-109618 and
CVE-2026-109619, so no current exposure to those two defects was demonstrated.
The unnecessary capability remains avoidable attack surface. Before inbound
activation, either obtain a provider-supported CGI-without-PHP profile or deny
PHP-like extensions at Apache level and prove that the static site and Python
CGI still work. Do not substitute NFS's Static Content profile: it also disables
CGI.

### Resolved in 8B: total HTTP fetch deadline

`reader_network.fetch_bounded` and `post_bounded` now share one monotonic budget
across bounded DNS resolution, connection setup, redirects, headers, and body
reads. A small fixed resolver pool prevents timed-out DNS work from spawning
an unbounded set of stuck threads while letting unrelated hostnames proceed.
Concurrent callers for the same hostname share one in-flight resolution. An
active cutoff shuts down the pinned socket when slow headers or a slow-trickle
body reach the deadline. Ordinary Reader fetching retains its existing
behavior.

Deterministic fixtures cover slow DNS, a deadline consumed across redirects,
slow headers, slow bodies, mixed public/private answers, invalid budgets, and
the shared outbound POST path. The existing redirect/address revalidation,
response-size, SSRF, relation, form, policy, and retry tests were rerun. Parser
fixtures now also cover pathological JSON nesting, unsafe alternate-document
locations, and hostile author strings remaining inert bounded metadata.

The 8B checkpoint passed 171 focused Webmention/security tests and all 480
repository tests on 2026-10-21. The receiver and verifier remain inactive.

### Resolved in 8C: owner-side lock validation

The verifier worker's existing lock did not use `O_NOFOLLOW` or validate an
already-existing lock's type, link count, and exact mode. The target-registry
installer rejected non-regular and multiply linked locks but accepted group
write permission. Neither component is deployed, and their containing
directories are owner-controlled, so no live exploit existed. Both locks now
require one regular owner-only `0600` file; the verifier also refuses symlinks
at open time.

Failure injection now covers provisional record writes, both sides of the
queue transition, final records, export replacement and rebuild, archive writes
before and after replacement, corrupt main-plus-backup archives, registry
backup/current replacement, uncertain completion, simultaneous registry
installs, worker overlap, lock symlinks/hard links/modes, exact file modes,
replay, conflict, rollback, queue exhaustion, and cross-process intake.

A corrupt local incoming archive may recover from its verified backup. A
corrupt exact-target registry deliberately fails closed rather than restoring
an older registry and silently rolling back which URLs count as published.
Actual deployed UID/GID ownership remains an 8D host check. The 8C checkpoint
passed 185 focused Webmention/security tests and all 494 repository tests on
2026-10-21.

### Defense-in-depth review items

- Revalidate parent-directory ownership/permissions for every protected path at
  deployment, not only the final file, so a privileged setup error cannot turn
  file-level symlink checks into false confidence.
- Confirm the site's selected *web* PHP SAPI/version in the NFS member panel;
  the read-only precheck verified installed CLI/minor-link builds but did not
  upload or execute a PHP web probe.
- Review the installed remote registry helper and scheduled verifier bytes
  against the checkpoint commit before enabling either task.
- Establish bounded log and terminal-record retention without deleting pending
  or retrying work.

No receiver-side route to Git, drafts, subscriptions, publication, shell
construction from mention values, or rendering of remote HTML was found in 8A.

## Remaining Stage 8 checkpoints

### 8B — Adversarial network and parser gate — complete 2026-10-21

- Add a hard total fetch deadline and deterministic tests for slow DNS,
  slow-trickle bodies, redirect chains, address changes, mixed DNS answers,
  TLS/port variants, and oversized responses.
- Expand malformed form, URL, PSL, JSON, alternate-document, relation, and
  hostile-metadata fixtures.
- Re-run outbound discovery/delivery against the same SSRF cases.

### 8C — Durability, concurrency, and privilege gate — complete 2026-10-21

- Inject failures at every queue, provisional/final record, export, sync,
  archive, and registry-refresh persistence boundary.
- Exercise writer/worker overlap, lock starvation, full storage, corrupt
  main/backup pairs, replay, conflict, and rollback.
- Review every created file's type, link count, mode, owner/group expectation,
  and executable/writable separation.

### 8D — Deployment rehearsal and disable proof

Status: **complete 2026-10-21.**

- On an owner-approved disposable route, verify the exact deployed scripts,
  fixed commands, directories, modes, selected Python, PSL, registry, and
  scheduled task.
- Remove or deny PHP execution and verify static paths, MIME types, caching,
  feeds, Git checkout, and Python CGI.
- Prove that policy `off` and removal of endpoint advertisement disable inbound
  work without affecting the static site or publication.
- Leave production unadvertised until Stage 9 independently reviews the result.

The live host ran Python 3.11.15. Its CLI PHP was 8.3.36-nfsn1, while the actual
Apache/NFGI web runtime was 8.1.34-nfsn2; both are patched branch releases. A
disposable web probe confirmed the latter before a permanent Apache rule denied
PHP, PHP-number, PHPS, PHTML, and PHAR extensions. The same rule returned 403
for the probe while the Python CGI continued to execute.

The exact fixed registry helper and verifier command were installed owner-only,
their hashes matched the reviewed local files, and the verifier completed an
empty bounded run. The NFS schedule is intentionally not configured yet. The
receiver runtime and policy-off configuration are installed, but the public CGI
wrapper was removed and the Blyg manifest has no endpoint advertisement.

The rehearsal found and fixed one deployment defect: registry initialization
stripped the host's setgid directory bit, causing later atomic registries to
lose the web-readable group. The store now preserves an administrator-supplied
setgid boundary. The deployed registry directory is mode 2750 and current and
backup artifacts are owner-written, group-readable mode 0640. Installation was
proved current, idempotent, and rollback-resistant against a delayed older
artifact.

After removal, every disposable public probe returned disabled/absent behavior.
The homepage, numbered post, both feeds, manifest, MIME types, ETags/modified
metadata, and hosted Git commit remained correct; `.git` remained HTTP 404.

## Gate decision

**Ready for Stage 9; not ready to activate.** The implementer's gate is clear,
the receiver is policy-off, absent from the public tree, and unadvertised, and
the verifier has no schedule. Stage 9 must independently review the code and
the rehearsed host boundaries before any endpoint deployment, advertisement,
schedule activation, inbound synchronization activation, or live inbound test.
