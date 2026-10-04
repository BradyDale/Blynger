# Reader quoting and response stubs — current behavior in Blynger 0.9.21

The October 3, 2026 revision of the living Blyg 0.3 specification promoted partial transclusion into the normative protocol. Blynger still publishes a highlighted passage as an ordinary frozen citation: the private draft remembers the enclosing source and exact selection, but public item JSON carries no selector or transclusion reference, public Markdown carries no `![[id]]` directive, and the HTML does not claim `blyg-transclusion`. No selected passage receives a synthetic item ID. This remains an explicit interoperability limitation; it is separate from the whole-item Stub repair described below.

Ordinary RSS/Atom and plain-web selections remain semantic blockquotes/citations with their actual URL and no Blyg ID, version, kind, or selector. **Quote** alone never creates `stub_of`. **Stub** is the explicit response action and records exactly one immutable target: `{origin, id, version}` for a genuine Blyg item, or the normative `{url}` form when a plain-web response is supported. A Blyg target may also carry the specification's optional `cited` context. Repeated selections from that same source can be added to the current response; each quotation keeps its own frozen snapshot/selector while the response keeps one target.

A Stub can create a normal response post or a quick Opener. Both begin with a
genuine whole-item transclusion when the target is a Blyg item. Write mode treats
that source as one protected block: the author may delete the whole block but
cannot casually edit the source's words. Publication re-resolves it from the
local Reader snapshot, emits `![[id]]`, records the baked version in
`transclusions[]`, and reconciles `stub_of.version` to that version as Blyg 0.3
requires. Removing the transclusion does not clear `stub_of`; the relationship
is metadata, not an inference from quoted HTML. A plain-web target has no
versioned Blyg identity and therefore remains ordinary editable quoted context.
The server repeats that enforcement when saving: protected blocks are restored
from their private source record, while obsolete copied Blyg Stub context is
upgraded from the exact cached Reader version. Publication strips every editor-
only class and token and writes the bare Blyg 0.3 transclusion block to canonical
JSON. Tests inspect those final JSON files rather than stopping at draft markup.

Empty editable paragraphs are placed before and after a newly inserted quotation so the author can write on either side. They are removed from publication if left empty. The earlier automatic “respond here” sentence is gone. A composer Blockquote is independent authored HTML, optionally with `cite` and a visible `<cite>` link; it never becomes a transclusion merely because it is a quotation.

Pinned-version **Fork** is a different operation: it copies source content into an independent editable draft and records immutable `forked_from` lineage. It adds no transclusion by itself. See `READER.md` for pin eligibility and blogroll behavior.

# Historical 0.7.0 implementation report

## Using it

Open an item in Blyg reader. The existing Quote button follows the selection:

- Nothing selected: quote the complete item.
- Click a small source-fragment dot, or highlight precisely that fragment: quote its real identity and imported version.
- Highlight other text: Quote selection inserts only those words, with paragraph breaks and source attribution.
- Ordinary RSS/Atom articles use the same flow and retain ordinary article attribution.

The headline remains yours to edit and is website presentation, not a Blyg item title field. All quoted material and attribution stay inside the gray quotation while editing. Write normally before or after it. Highlighted excerpts and ordinary-web citations remain frozen. Genuine whole-item and genuine fragment transclusions are re-resolved from the latest locally cached snapshot whenever their containing thread is published, as Blyg 0.3 requires; publication still performs no network request.

The remainder of this file is a historical implementation report. Where it describes selector-bearing public excerpts, frozen whole-item transclusions, or a title field, the current rules above supersede it.

## Implementation and inspection findings

1. **Files:** `reader.py`, `core.py`, `app.py`, `fragments.py`, `static/fragments.js`, `static/app.js`, `static/style.css`, `version.py`, `test_selections.py`, `test_reader_browser.html`, `test_selection_browser.html`, `serve_selection_tests.py`, and documentation (`READER.md`, `README.txt`, `CHANGELOG.md`, this file).
2. **Existing imports:** the Blyg importer already retained whole source JSON, including `transclusions`, rendered wrappers, IDs, origin, versions, and unknown keys. No flattening migration or second cache was needed.
3. **Importer changes:** ordinary RSS/Atom was not actually supported by the earlier reader. Added it within the same Reader, subscriptions, item store, and media cache. Supports RSS content/description and Atom text/HTML/XHTML, discovery through alternate-feed links, author/date/link metadata, stable feed GUID/internal cache keys, conditional refresh, and deduplication. No existing items are migrated or rewritten.
4. **Blyg vs ordinary feeds:** genuine Blyg discovery uses its manifest and existing item/index validation. Plain feeds are marked `l0`; they do not receive protocol IDs, kinds, versions, or transclusion metadata. Internal cache keys are not Blyg IDs. A separate ordinary feed is not upgraded simply because its host also has a Blyg manifest.
5. **Real fragments:** selectable wrappers must agree with the imported item's direct `transclusions` references. The right-margin dot is empty, absolutely positioned, and has a tooltip. It is never source text or publication content. The imported source ID, origin, and exact wrapper version are retained. Unverifiable wrappers are not presented as selectable protocol fragments.
6. **Selections:** only ranges wholly within the open content container are accepted. Exact fragment ranges take precedence; partial and cross-fragment ranges cite the enclosing item. Selection text, punctuation, order, and paragraph breaks are stored, never summarized. An open-view fingerprint prevents quoting a silently changed cache entry.
7. **Plain RSS:** citations retain URL, title, feed name, author/date when supplied, and selected text. Their published blocks have ordinary source links and no Blyg identity/version claim.
8. **Identity:** new local quotation tokens identify editor records only. They are not protocol IDs and are stripped from publication. Genuine whole/fragment quotes use the original Blyg ID and version; excerpts carry the enclosing origin/ID/version as `data-source-*` HTML attributes plus readable attribution, not an independent identity.
9. **Frozen snapshots:** private quote records live in the existing draft and saved authoring-source records, alongside fragment metadata. Historical authoring records include them. Selected media is copied into the existing authoring uploads area so reader eviction cannot delete it. Refresh, autosave, reopening, publication, and restoring a historical revision preserve the snapshot. No new subscription system/database/cache or dependency was added.
10. **Serialization:** full Blyg objects produce the existing `![[id]]` Markdown directive, `blyg-transclusion` HTML wrapper and direct JSON `{id, version, origin}` reference. The author creates no item endpoint for the remote source. Arbitrary excerpts are ordinary quoted HTML/Markdown; the enclosing Blyg origin/ID/version appears in the HTML and attribution, never as a fake excerpt object or a misleading whole-object transclusion. Ordinary RSS has ordinary citations only. Reader dots and editor tokens are removed. Both numbered HTML pages and machine-readable item HTML are tested.
11. **Protocol limits:** the normative [0.2 specification](https://blygger.org/spec/0.2/) does not define arbitrary-excerpt identity, and this change adds none. The existing app already uses the cross-origin/thread reference fields in the [0.3 implementation plan](https://github.com/blygger/blygger-spec/blob/main/docs/v0.3-plan.md) and [independent desktop implementation](https://github.com/aneeshsathe/blygger-desktop); these are not mislabeled as normative 0.2 features. The specification describes resolving directives again on publication. The user's explicit freeze requirement instead retains the imported snapshot for these new explicit reader quotes, including revisions. This is a local authoring policy difference, using existing wire fields rather than inventing version-qualified directive syntax. Other editors may re-resolve an imported directive; Blynger cannot guarantee their editing policy. `data-source-*` excerpt attributes are ordinary HTML annotations, not a standardized excerpt protocol primitive. A source permalink may now show a newer version; the copied text and quoted-version label remain fixed. Legacy/local directive quoting still follows the existing resolution behavior.
12. **Verification:** 105 Python tests pass, including 20 new selection/import/snapshot regressions. The browser workflow passes all four modes, exact/partial/cross-fragment selection, punctuation and paragraph breaks, dot tooltip/layout, outside-content rejection, draft reload, and publication to a disposable local Git remote. It verifies public HTML has no private editor tokens. No real subscription, post, or live publication is created by these tests.

## Tests

Run the existing Python environment with `python -m unittest discover -q`.
For UI checks, run `python serve_selection_tests.py`, open its printed localhost URL, and click “Run all four quote workflows.” All data and its Git remote are disposable. Stop the server to clean them up.
