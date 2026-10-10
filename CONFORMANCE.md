# Blyg conformance in Blynger

Blynger targets the living Blyg 0.3 Level 2 publication and reader contract.
Conformance is judged from the final static files, not from the editor's intent.

The 0.9.27 review used the published living 0.3 text and its source revision
`8e7a0800b224395232120299b952c3b6937e5bfa`, the toolkit proposal at
`98af8da`, and Blygger Studio's 0.21.0 production harness. The current Studio
source was also inspected at `53be5a1`; the older harness is intentional
because it is the version targeted by that toolkit proposal.

The 0.9.34 review rechecked the live specification and official source at
`fde93b694a401d3c458b34dfac84fc833ba861dd`. Blynger already accepts the newly
normative optional `changelog[].generated` and plain-web `stub_of.cited`
members as ignorable/extensible data. Fork import now follows the newer
flattening rule: inherited baked transclusions lose their verification tokens,
become ordinary attributed quotations, and retain truthful generated-text
disclosure. Static-only Blynger still does not advertise or receive
Webmentions, which remains conformant.

Every preparation runs `conformance.validate_surface()` against the complete
in-memory Blyg surface before those files are written to the website folder. It
independently checks current item documents, archive rows, pinned snapshots,
the protocol feed, content hashes, version sequences, withdrawals, absolute
HTML addresses, whole-item directive/transclusion agreement, Stub version
agreement, generation disclosure, and the absence of private quote metadata.
A required-rule failure stops preparation before any public file changes.

The checker intentionally has no dependency on `core.py`: it observes only the
same bytes a reader would. It is a bounded implementation check, not a proof of
the protocol and not a replacement for the official schemas or cross-client
tests. Recommended rules appear as warnings rather than being silently promoted
to requirements.

## Official toolkit adapter

`conformance/adapter.mjs` makes Blynger an implementation adapter for the
official Blyg conformance and intent toolkit proposed in
[`blygger/blygger-spec#11`](https://github.com/blygger/blygger-spec/pull/11).
It invokes `conformance_fixture.py`, which drives the real Blynger
save/prepare/review/publish machinery against disposable Git repositories and
exports the exact resulting static surface. No personal settings, website,
Reader cache, drafts, credentials, or network publication are used.

From a checkout of the toolkit proposal:

```sh
cd conformance/schemas
npm install
BLYNGER_PYTHON=/path/to/python \
  node run.mjs --offline \
  --impl /path/to/Blynger/conformance/adapter.mjs \
  --out /tmp/blynger-conformance
```

The toolkit and its independent-oracle approach were created by Aneesh Sathe
for the Blygger project. Blygger Studio is the MIT-licensed reference client.
Blynger adapts the public adapter interface and testing ideas to its own static
Python publication pipeline; it does not copy Studio's application architecture.

## Scope limits

- The built-in gate covers Blynger's publish side. Reader import behavior has
  its own malformed-input, recovery, cross-origin, and lossless-sync tests.
- The adapter currently supplies production-path artifact samples and static
  field coverage. The toolkit's own reference grammar still supplies the
  independent bracket-grammar authority; Blynger's local grammar regressions
  exercise its parser through final publication.
- Network promises such as CORS headers and continued hosting of already
  published pins require deployment checks and cannot be established from a
  local static directory.
- Webmention remains optional and is not advertised by Blynger.
