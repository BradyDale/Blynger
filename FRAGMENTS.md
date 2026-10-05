# Intentional fragments — Blynger 0.5.0

Use **Fragment** in the Write toolbar, or press **Control + Shift + F**. Put the cursor anywhere in a body paragraph: that paragraph begins a new fragment, while eligible text above it forms the preceding fragment. Fragment is additive and never silently removes an existing boundary; invoking it again at the same boundary is a harmless no-op. **Remove fragment** is the separate removal action and merges the adjacent sections while retaining the first identity. Changing a body block to H2 automatically adds a boundary before that heading, without duplicates or empty fragments. Changing the heading back does not silently remove that explicit boundary.

A small margin dot shows each break without inserting article text. The body start/end are implicit boundaries; title, signature, and date are excluded automatically. Existing published fragment objects remain available if a future draft removes their designation.

Inserting reviewed TK output makes the generated block its own fragment, and designates surrounding body sections separately. The title, Example Author signature, and standalone date are excluded. TK content may itself contain headings. Existing posts are not retroactively fragmented merely by opening them.

**Save draft** persists the choices privately. Blynger still uses explicit saves, not autosave. HTML source remains editable on fragment-aware posts: returning to Write or saving maps unchanged blocks to their stable identities, maps a same-size edited block list by position, and repairs displaced boundaries before validation. Clear fragment choices returns the post to ordinary editing without withdrawing published objects. If a structural edit is genuinely ambiguous, saving fails with an explanation rather than silently publishing the wrong prose. Clear choices and re-designate if needed. Whole block movements retain their anchors; arbitrary cut/paste of partial text is treated as prose editing.

## Private model

`fragments` is an optional version-1 object on a draft: ordered `blocks` with stable random local IDs and HTML, `dividers` referencing the block immediately after a boundary, and explicit `ranges` with a stable local `key`, a starting block ID, and an exclusive end block ID (or null for document end). These are structural anchors, not character offsets. Browser-only `data-fragment-block` attributes and margin overlays are stripped before serialization. The server validates the metadata against sanitized article content and rejects stale, overlapping, reversed, duplicate, or excluded ranges.

If ordinary browser editing merges or removes the paragraph carrying a divider, the editor moves the private boundary to the next surviving body paragraph, or removes it when there is no next paragraph. Existing fragment identity is retained whenever any of that fragment remains. A server-side safety check also discards an orphaned editor-only divider rather than preventing the draft from being saved; it never changes the prose.

`fragment_ids[page][range-key]` reserves Blyg identities during publication preparation. Draft divider insertion itself allocates no public item or history. `fragment_posts` retains private editable source after successful publication; `fragment_history` retains that source for restoring a parent revision. Existing state gains empty maps lazily. No existing IDs or posts are migrated. Preserve the private Blynger-support data directory in backups, as before.

## Publication

Preparation resolves designated ranges into ordinary Blyg 0.2 fragment documents, using the existing media, sanitization, hashing, history, feed, pin, and Git publication machinery. Identity uses 128 random bits encoded in lowercase Crockford base32. Unchanged fragments keep their version; changed ones retain identity and increment by one after publication. Repeated preparation does not create historical versions. Only a successful push records publication history.

The parent becomes/remains a thread. Its Markdown contains standalone `![[id]]` references among ordinary prose. Its protocol HTML contains required `blockquote.blyg-transclusion` snapshots and its `transclusions` array records exact `{id, version}` pairs. Child documents are resolved in the same publication batch. The regular article unwraps only its own extracted fragments to preserve normal prose layout; protocol JSON retains the required wrappers. Public articles include a tiny right-margin permalink dot for each designated fragment. These presentation markers stay out of protocol HTML and Markdown; private authoring controls are never published. TK fragments carry generation provenance in their own `generated` arrays, including model/time when available; no instructions are emitted. Newly styled TK passages use a dashed grayscale enclosure and a small monochrome robot at the lower-left corner. Existing published pages retain any earlier embedded TK style.

Generated fragments have JSON at `blyg/items/{id}.json` and human pages at `blyg/f/{id}/`. Newly generated in-post fragment pages identify their enclosing post with a `FROM:` heading and link back through `Full thread`; their permalinks are included in the sitemap. On newly rendered human pages, the robot mark is a hover/focus/tap control for the version's self-reported `generated[]` details; this presentation never enters `content_html`. The parent thread is the sole RSS announcement—its reusable child fragments remain available through the archive and sitemap without flooding ordinary feed readers. New Openers remain individual feed entries because each Opener is itself the published unit. They appear in the existing Quote post picker after publication. Removing a designation does not delete a previously published object or its index/feed presence. Pinning remains explicit; quoting does not auto-pin. Existing posts without metadata follow the original path.

Intentional multi-paragraph ranges may exceed the protocol's recommended 2,000-character fragment cap; this preserves the author's chosen unit and the requested TK surrounding sections. Blyg 0.2 expressly requires readers to accept longer fragments. Use additional dividers for shorter units when useful.

Every H2 in a fragment-enabled post is also a fragment boundary. This is enforced when a post opens as well as when the H2 toolbar button is used, so headings introduced through HTML source receive the same behavior. If a legacy page contains invalid paragraph/list nesting that the browser expands into valid top-level blocks, Blynger reconciles the private block map, preserves the earlier fragment key on the first resulting section, adds the missing H2 boundaries, and leaves the repair visibly unsaved until the author saves it.

## Interoperability review

Authoritative contract: [Blyg 0.2](https://blygger.org/spec/0.2/), especially §§5, 7, 8, 10, 13. Compared against [aneeshsathe/blygger-desktop](https://github.com/aneeshsathe/blygger-desktop/tree/6151e4dbccc7d72c20d2511860088c1b29c82acf), commit `6151e4dbccc7d72c20d2511860088c1b29c82acf`:

- `crates/blyg-render/src/transclusion.rs`: same standalone ID directive, baked HTML, ID/version provenance. Its renderer also supports imported items and nested threads. Those are outside Blyg 0.2; Blynger does not emit them.
- `crates/blyg-core/src/model.rs`: fragment/thread kinds, integer versions, Markdown hash, content HTML, and transclusion references are structurally compatible. Its reader consumes stored HTML with snapshots already baked. No claim of running its complete native client was made.
- `crates/blyg-core/src/api/wire.rs` and `docs/SERVER.md`: the desktop client requires owner API authentication/read/sync extensions. These are not public Blyg requirements. Blynger retains its static host and local studio API; it cannot act as that client's owner API server.
- Its 1,000-character studio limit is an authoring policy, not a reader validity rule. Its newer remote/thread/fork functionality is not copied into the 0.2 publication contract.

## Verification

`test_fragments.py` tests private persistence/no history on save; multi-paragraph ranges; implicit ends; title/signature rejection; legacy posts; full local Git push; save/reopen after publication; stable identity and next version on edits; unchanged fragment versions; immutable private history; metadata leakage; removal/clearing without deletion; generation provenance per fragment; and human page generation. The existing core, metadata, TK, and Apache permalink tests remain in the suite.

`test_fragments_browser.cjs` contains browser checks for keyboard default prevention, insertion/removal, layout preservation, metadata roundtrip, and TK separation. The same checks were run in the in-app browser against an isolated HTTP test fixture, extended through save/reopen and the actual Git publish path to a local bare repository. The published test post and its machine documents were inspected. This is a real local Git publication, not a live-site deployment. No test article or changes were pushed to example.com.

Final result: all 31 Python tests passed, including the Apache routing test. Browser checks passed with TK inserted mid-paragraph, then whole sections moved and saved/published. The native app was restarted only after its UI showed Ready; `/health` and the native window both confirmed 0.4.0, with the Fragment menu present.

Files changed: `core.py`, `fragments.py`, `static/app.js`, `static/fragments.js`, `static/index.html`, `static/style.css`, `test_fragments.py`, `test_fragments_browser.cjs`, `version.py`, `README.txt`, `CHANGELOG.md`, and this document. No new runtime dependency was added. Test publication artifacts are retained in the chat workspace under `outputs/fragments/published-fixture/`.
# Recovery

Authored quotation marks are normalized consistently in both article HTML and
private fragment blocks, so punctuation alone cannot make the two disagree. If
a post's private fragment map is nevertheless damaged, its save error offers
**Remove all fragments and save draft**. The recovery keeps all writing and
ordinary formatting while clearing reusable fragment boundaries from that
draft; fragments can be added again afterward. Published fragment history and
previously shared fragment pages are not deleted.
