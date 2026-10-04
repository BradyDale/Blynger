# Openers — current behavior in Blynger 0.9.18

## Using it

Open **Openers**, then **New opener**. Write the text and choose **Add opener**. Blynger inserts it at the top, dates it using the Mac’s local calendar, and saves a local draft. A second entry on the same date labels the first I and the second II; subsequent entries continue III, IV, etc. Existing same-day anchors and fragment identities remain stable. Other dates are unchanged. Cancel and blank submissions create nothing. Further editing uses the existing page editor and Save draft.

New Opener dialogs default **Pin this version when published** to checked. The
choice is stored with the draft, appears in publication review, and produces
the normal irrevocable Blyg pin only when that prepared publication succeeds.
It can be unchecked before adding the Opener. A quick Reader Stub to Opener
uses the same default and publishes as a `thread` with immutable `stub_of`.
Its editor begins with a linked **Stub of:** line and the complete source item,
followed by the new response. That copied source is editable prose rather than
a frozen quotation, so it may be shortened or deleted while the response
identity remains. Ordinary Openers remain `fragment` items.

Each dated Opener automatically represents one reusable fragment, including all of its paragraphs. The quiet right-margin dot has a “Fragment” tooltip. A normal publication adds a similarly small dot to the public page, linking to `/blyg/f/{id}/` for an ordinary Opener or `/blyg/t/{id}/` for a response. Public dots occupy no text space and are not included in protocol content. Nothing is automatically pushed when adding an Opener.

## Shared model and migration

Openers use the existing version-1 post `blocks`, `dividers`, and `ranges` schema and the same `fragment_posts`, `fragment_ids`, and `fragment_history` stores. `purpose: openers` is private authoring information, never a protocol subtype. A range remembers its heading anchor, original date label, and legacy HTML anchor. The heading/date remains outside the fragment’s content; the page introduction is ordinary prose.

The one-time migration writes only private state, first saving a backup under `migrations/openers-fragments-v1.json`. Repeated runs do not duplicate entries or allocate new identities. It preserves the original public file byte-for-byte until publication, including dates, order, links, and duplicate legacy anchors. Existing private metadata is retained where available. There were 121 entries at activation, including the two newly added entries. No historical creation/modification timestamps are fabricated: original dates remain intact, while new Blyg publication records begin with actual publication.

The oldest archive uses one `strong` date heading; it is recognized alongside the usual `h3` headings. Stable private heading IDs distinguish the archive’s duplicate HTML anchors without changing those old URLs. Edits through the editor carry these anchors forward.

New entries use exactly the same model automatically. Draft references are `{page, key}` and can be passed around internally through `Studio.fragment_objects`; public IDs are exposed by that service only after successful publication. This is also the service available for post fragments. There is no second fragment store. Published Openers appear in the existing Quote post picker and use ordinary Blyg transclusion directives. A larger draft-fragment browser was deliberately not added.

## Publication and versions

Adding, migrating, or editing a draft creates no public history. Preparation reserves ordinary Blyg IDs using the existing post fragment machinery. Successful publication records version 1; subsequent text changes preserve identity and produce the next version. Unchanged fragments do not gain versions. Each fragment uses normal generated-content provenance, sanitization, hashing, media handling, JSON endpoint, permalink, and history code. Parent Openers page identity and existing URLs remain unchanged.

A saved draft can differ from its published version. The existing publication workflow publishes the page and its selected fragments together. The new-entry dialog controls only the first version's normal Blyg pin; it is not a separate per-Opener publish button. A thread’s baked transclusion retains the source version captured when that thread was published. Existing pin immutability remains in effect.

Post dividers now designate body sections directly on first use. Explicitly unmarked sections stay ordinary prose. The eight saved dividers in 43.html were resolved into nine fragment ranges in a local draft; its body was verified unchanged. No unrelated post was fragmented.

## Interoperability

The authoritative contract is [Blyg 0.2](https://blygger.org/spec/0.2/). The comparison implementation was [aneeshsathe/blygger-desktop](https://github.com/aneeshsathe/blygger-desktop/tree/6151e4dbccc7d72c20d2511860088c1b29c82acf), commit `6151e4dbccc7d72c20d2511860088c1b29c82acf`.

Both use stable fragment IDs, integer versions, Markdown hashes, rendered HTML, and ID/version provenance. Ordinary Openers emit `kind: fragment`; a response Opener with immutable `stub_of` emits the protocol-required `kind: thread`. There is never an Opener-specific kind. Machine-readable `/blyg/items/{id}.json` and human-readable standalone pages remain separate.

The reference client’s owner authentication/sync API, imported items, nested threads, and newer fork behavior are extensions beyond the published 0.2 contract. They were not copied. Its 1,000-character studio limit is an authoring choice. Blynger preserves multi-paragraph Openers; the specification requires readers to accept fragments beyond the recommended size. Compatibility was checked structurally and with real HTTP/Apache route tests, not by running the reference native application against this site.

## Changed files and verification

- `fragments.py`: shared Openers range mapping and saved-divider conversion.
- `core.py`: additive migration, shared internal fragment objects, publication markers, historical metadata, and preparation baseline handling.
- `app.py`: migration at startup and authenticated private fragment-object endpoint.
- `static/fragments.js`, `static/app.js`, `static/index.html`: automatic Openers, dialog, dates/numerals, quiet existing indicators, and direct post-divider behavior.
- `version.py`, `CHANGELOG.md`, `FRAGMENTS.md`, `README.txt`, and this document: version and usage notes.
- `test_openers.py`, `test_permalinks.py`, `test_fragments_browser.cjs`, and Openers browser fixtures: migration, editing, publication, identity, routes, and UI checks.

All 39 Python tests passed, including migration without duplication, text/order preservation, reload, private drafts, local Git publication, stable IDs and new versions, shared post services, historical snapshots, Apache fragment routing, JSON endpoints, marker exclusion, and repeated preparation.

Browser checks passed on a disposable copy of the 121-entry archive: tooltip, unchanged wrapping, blank rejection, automatic dates, I–IV and IX/XIV numbering, stable identity/order, safe literal text, save/reload, unpublished state, local Git publication, normal protocol output, one public dot per Opener, and no public layout shift. The actual dialog was used to create and save a test entry, correctly continuing the existing September 26 entries with III. Test content was confined to the disposable fixture.

The native app and health endpoint both report 0.5.0. Migration retained all 121 real Openers. No changes were pushed to example.com; use Review & publish when ready.

To repeat the browser fixture, run `python serve_opener_tests.py`, open its printed local URL, and choose Run isolated checks. Optional `--openers /path/to/openers.html` copies an archive into that disposable fixture. Restart the fixture between runs.

Post editor browser regression checks also passed: keyboard shortcut, divider toggling, automatic section designation, metadata roundtrip, TK separation, stable identity after reordering, and unchanged layout.

## RSS going forward (0.6.0)

Since 0.9.4 the feeds are deliberately separate. The complete Blyg protocol
feed at `/blyg/feed.xml` includes every Opener fragment publish event, including
historical items and later edits, because Blyg uses RSS as its notification
plane. The ordinary site feed at `/feed.xml` keeps the quieter editorial rule:
the one-time private `opener_rss_legacy_keys` baseline excludes entries already
present at migration, each future Opener appears once at first publication,
and later edits do not resurface it. Saving a draft syndicates nothing. The
aggregate Openers page is in neither feed. Stable IDs, dates, item endpoints,
and the complete archive index remain intact.
