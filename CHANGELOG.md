## 0.10.4 — Reader presentation module

- Move Reader cards, Saved timestamps, private-activity rows, generated-text disclosure, conversation controls, and opened-item markup into the focused `static/reader-ui.js` module.
- Keep Reader network requests, private state, quotation and Stub authoring, and workspace transitions in their existing owners so the extraction does not change behavior or trust boundaries.
- Add a direct JavaScript regression for opened Reader presentation, pins, fragments, disclosures, and conversation navigation.
- Make the optional native build script's default installation path portable instead of embedding one developer's home-directory path.
- Keep this refactor behavior-neutral. It does not alter subscriptions, private activity, drafts, protocol objects, or website files.

## 0.10.3 — Readable browser source

- Expand the browser interface, editor helpers, fragment editor, styles, markup, and browser regressions into consistently formatted source suitable for human review.
- Add a pinned Prettier configuration for future browser-source changes and exclude unrelated native and schema files from formatting.
- Make source-presence regressions insensitive to harmless whitespace so tests protect behavior and safety hooks without requiring compressed code.
- Keep this pass behavior-neutral. It does not alter drafts, website files, publication formats, or private Reader data.

## 0.10.2 — Reviewable source boundaries

- Move Reader network validation, DNS pinning, redirects, and bounded HTTP transport into the focused `reader_network.py` module.
- Move generated-page templates and forward-only presentation styles into `page_templates.py`, while retaining the established imports used by tests and integrations.
- Add `DEVELOPMENT.md` with a reviewer-oriented code map and an explicit rule against adding new compressed, semicolon-packed code.
- Keep this refactor behavior-neutral. Publication formats, private state, Reader data, and website files are unchanged.

## 0.10.1 — Known conversation paths

- Add a small local conversation lens to opened Reader items. A known `stub_of` parent appears above the item as a left-aligned **← Backward** button; locally cached direct responses appear below it as right-aligned **Forward →** buttons.
- Treat forward navigation honestly as the Reader's known neighborhood. Multiple cached responses remain visible as branches, and Blynger does not imply that an incomplete subscription graph is the whole conversation.
- Stop repeating a derived Reader headline at the beginning of its card preview. If removing the repeated text leaves no useful excerpt, the empty preview line is omitted.
- Open links clicked inside imported Reader writing in the normal web browser. Blynger's own conversation controls still navigate cached items inside Reader.

## 0.9.34 — Visible Stub context and durable Mac permissions

- Show a **Stub of:** target on Stub cards and at the top of opened Reader items. Use the frozen `cited` caption when available, open a cached Blyg target inside Reader, and otherwise open its safe public address.
- Add **Center** to the editor toolbar. Centering is saved as authored HTML and receives a small forward-only public style only on pages that use it.
- Give locally built Mac applications a stable designated signing requirement so macOS can retain the user's Documents-folder permission across later Blynger rebuilds. An existing installation may ask once more when it adopts the stable identity.
- Update fork handling for the current Blyg 0.3 rules: inherited transclusions become ordinary editable quotations with visible attribution, verification classes and attributes do not survive, and inherited generated spans keep a truthful generation disclosure.
- Recheck the live Blyg 0.3 specification and its official source at revision `fde93b694a401d3c458b34dfac84fc833ba861dd`, including the 2026-10-06 revisions covering generated changelog notes, plain-web `cited`, fork presentation, and flattened fork provenance.

## 0.9.33 — Bounded and authenticated Reader imports

- Close the Reader's DNS-rebinding window by resolving each requested or redirected hostname once, rejecting any local/private result, and connecting TLS or HTTP to that exact validated address. HTTPS still verifies the certificate against the original hostname.
- Parse untrusted RSS, Atom, and Blyg discovery XML with `defusedxml`, rejecting entity expansion, external entities, and other unsafe XML constructs.
- Bound each ordinary feed to 500 entries, each Blyg archive to 2,000 rows, each refresh to 100 changed canonical items, each item to 16 media files, each media response to 8 MB, and all media for one subscription refresh to 64 MB. Deferred changed items remain queued for later refreshes.
- Reject content-hash mismatches, origin mismatches, and same-version content changes before they can replace or enter the Reader cache. Preserve the last known-good item and display an explicit rejection warning in Reader.
- Add adversarial regressions for connection pinning, hostile XML, bounded feed/media work, and integrity-failure quarantine.

## 0.9.32 — Editable Reader quotes and reliable links

- Restore the intended distinction between Reader actions: **Quote** inserts a lighter editable citation headed **From:** with the linked page title, while **Stub** alone requests the protected genuine Blyg transclusion used for strict response provenance.
- Keep ordinary Quote publications out of `transclusions[]` and free of `![[id]]` directives without weakening Stub version agreement or its publication-time snapshot verification.
- Apply editor links only after closing the modal and restoring the saved selection, so the browser is no longer asked to edit an inert background document. Fall back to inserting a visible linked address if the browser declines the formatting command.
- Preserve the newly normative optional `cited` label on plain-web Stub targets as well as Blyg targets.
- Label new response-source links **Stubbing:** instead of **Stub of:** in both post and quick-Opener drafts.

## 0.9.31 — Reader trust boundary

- Render every imported Blyg, RSS/Atom, and ordinary-web document in an opaque sandbox rather than sharing Blynger's privileged document origin. A narrow, randomized message bridge preserves excerpt selection, genuine-fragment selection, and safe link opening without exposing the application DOM or private API token.
- Give the Reader frame its own deny-by-default policy: no network connections, forms, nested frames, objects, base-URL changes, parent navigation, or arbitrary scripts. The only script admitted is Blynger's exact local selection-bridge file; cached media remain local.
- Give the main application UI its own deny-by-default Content Security Policy, no-referrer policy, and restricted browser-feature headers. Keep preview pages separately sandboxed.
- Replace Bleach with maintained `nh3` sanitization. Imported HTML loses scripts, styles, forms, fake controls, event handlers, dangerous URLs, arbitrary IDs, and arbitrary classes; only deliberately interoperable Blyg generated-text and transclusion markers survive.
- Retain Reader formatting, local cached images/media, source badges, Saved/Liked state, generated-text disclosure, Quote, Stub, Fork, and exact source-fragment identity across the isolation boundary.
- Add hostile-content regressions for UI-name collisions, CSS/control spoofing, local-route attempts, parent navigation, malformed HTML, permitted Blyg markers, the opaque sandbox, and the privileged UI policy.

## 0.9.30 — Public generated-text disclosures

- Turn the existing robot on newly generated or legitimately republished pages into an accessible hover, focus, and tap control.
- Show the version's self-reported model, generation date range, and source count, explicitly labeled as self-reported rather than verified. Generated text quoted from another Blyg points readers back to that item's disclosure.
- Keep `content_html` and `generated[]` unchanged: the button, popover, and private presentation metadata exist only on human HTML pages and never enter protocol objects or feeds.
- Preserve forward-only static history. Existing pages are not rewritten merely to add the interactive disclosure; new frozen pins and touched generated fragments receive it naturally.
- Adapt Blygger Studio's MIT-licensed generated-disclosure interaction, reviewed at revision `f32519b`, to Blynger's static, embedded-style pages and robot convention.

## 0.9.29 — Faster ordinary-feed refresh

- Stop reimporting every ordinary RSS/Atom entry when only channel metadata or XML formatting changes. Entry wire hashes provide a fast path, with a normalized-content comparison as a safe fallback.
- Download and inspect media only for genuinely new or changed entries. Unchanged entries retain their original observation time, cached media, Saved state, Like, and private response.
- Replace cached full ordinary-feed response bodies with compact hashes while retaining ETag and Last-Modified support. Existing caches migrate during their next successful refresh.
- Check up to six independent subscription origins concurrently; per-origin Blyg item downloads remain bounded at four.
- Report real changed-entry counts instead of treating every entry in a refreshed ordinary feed as downloaded.
- Adapt the content-change short-circuit introduced in Blygger Studio 0.26.1 and its bounded-polling approach, reviewed in the MIT-licensed 0.28.1 source at revision `f036594`, to Blynger's file-backed Reader.

## 0.9.28 — Private interaction history

- Add a private, append-only activity log for Saved/unsaved, Like/unlike, emoji responses, and successfully published remote quotes, Stubs, and forks.
- Keep Like as its own `👍` action and add five separate private responses: `🤯`, `🙄`, `👎`, `😂`, and `❓`. One emoji response can be active per item without changing its Like state.
- Show the history under **Saved → Private activity**, newest first, with local search and honest labels for records reconstructed from existing private state.
- Record publication interactions only after a push succeeds; abandoned drafts and failed publications create no response history. Retry completion is idempotent.
- Store every record exclusively in the configured private Reader data. No reaction, activity, or interaction field enters website HTML, Blyg JSON, RSS, OPML, the site repository, or the public Blynger source export.
- Adapt the interaction-log concept from MIT-licensed Blygger Studio 0.28.1 at source revision `f036594`, while keeping Blynger's file-backed local architecture and vocabulary.

## 0.9.27 — Independent Blyg publication checks

- Add an independent, read-only validator for the final Blyg 0.3 static surface and run it before publication preparation can write website files or save its generated protocol state.
- Verify current items, archive rows, content hashes, contiguous versions, withdrawals, frozen pins, absolute HTML addresses, whole-item directives, baked transclusions, Stub version agreement, generation disclosure, feed events, and private-metadata exclusion.
- Include a Blyg-check summary in publication review data; required-rule failures stop preparation with artifact-specific diagnostics.
- Add a production-path adapter for the official conformance and intent toolkit proposed in `blygger/blygger-spec#11`, using only disposable sites, private state, and Git remotes.
- Advertise Blynger's public source with the recommended manifest `generator_url`.
- Credit Aneesh Sathe's toolkit and Blygger Studio's independent-oracle approach while documenting exactly what the local checker does and does not establish.
- Verify against living Blyg 0.3 source revision `8e7a080`, toolkit proposal `98af8da`, and the compatible Blygger Studio 0.21.0 harness. The 203-check run finishes with no Blynger failures or warnings; its remaining seven warnings and two informational findings belong to the reference-client/grammar columns.

## 0.9.26 — Everyday authoring and Reader distinctions

- Keep the next-version pin choice visible for every editable Post, including revisions made after the first publication.
- Replace the link prompt with a link dialog that accepts safe public or root-relative addresses and can choose an existing permanent Page. Reserve bare numeric filenames exclusively for Posts; use descriptive Page names such as `year-2018.html`.
- Give Blyg-native and ordinary Web/RSS entries distinct, subdued Reader cards and opened-item backgrounds, with an explicit source badge.
- Render the shared `blyg-tk-gen` robot convention inside Reader and show the imported version's self-reported model, date, and source-count disclosure without claiming verification.
- Consult and credit Blygger Studio's open MIT-licensed implementation of generated-text disclosure; this release adapts the interaction concept to Blynger's existing static Reader rather than copying its application architecture.

## 0.9.25 — Draft-state recovery and Page-safe post numbering

- Explicitly clearing fragments now overrides every older fragment-aware source when saving a recovery draft.
- Fragment repair state is initialized before every editor repair path.
- Only Posts and Openers can retain fragment metadata; legacy fragment sidecars on static Pages are removed without changing their HTML.
- Fragment validation errors now identify the actual affected post, so recovery controls cannot clear the wrong draft.
- Standalone Pages no longer participate in numbered post allocation.
- Added regressions for stale fragment cleanup, numeric standalone Page filenames, and the complete repaired-H2 save/reopen/publication path.
- Credit the open-source Blygger Studio reference implementation in the project documentation before future interoperability work begins.

## 0.9.24 — Reliable H2 fragment boundaries

- Make every H2 in a fragment-enabled post start a fragment even when the heading arrived through HTML source or repaired legacy markup instead of the H2 toolbar button.
- Repair browser-expanded legacy blocks whose invalid paragraph/list nesting previously hid several H2 headings inside one saved fragment. Preserve the authored words and the existing fragment identity, mark the repair as unsaved, and explain it before the author saves.

## 0.9.23 — Favicons on Blyg permalinks

- Include the configured site favicon on generated Blyg thread, fragment, Opener-permalink, pinned-version, and Blyg-index pages so browser tabs retain the site's identity outside ordinary HTML pages.
- Treat this as functional metadata repair: the next reviewed publication may list existing generated Blyg HTML pages whose only change is the missing favicon.

## 0.9.22 — Upload from the Images workspace

- Restore the missing **Upload image** action directly on the Images page. Uploaded PNG, JPEG, GIF, and WebP files appear in the library immediately and remain queued for the next publication without requiring an open draft.
- Reuse the existing validated, content-addressed image upload path rather than creating a second storage mechanism.

## 0.9.21 — Stub transclusions verified at the publication boundary

- Repair the real Reader-to-publication failure shared by full Post and Quick Opener Stubs. If older UI code submits editable copied context for a genuine Blyg target, saving now replaces it with the exact locally cached source version and a protected private snapshot before the draft is accepted.
- Match legacy Quick Opener Stub blocks to their private ranges structurally instead of assuming the archive's raw HTML and normalized block map are byte-identical.
- Let a protocol-only maintenance revision preserve existing authored typography byte-for-byte instead of applying the normal new-writing quotation-mark normalization.
- Restore protected source blocks from their private snapshot during every save, including after an HTML-source round trip. Deleting the entire block remains intentional and leaves `stub_of` intact without a transclusion.
- Emit the bare Blyg 0.3 transclusion wrapper in final `content_html`; editor-only citation classes, private tokens, and convenience attributes no longer leak into the wire representation.
- Replace the misleading copied-context Opener regression with remote-source publication tests that inspect final canonical item JSON on disk. Add equivalent full-Post, save/reload, HTML-tampering, whole-block deletion, legacy-UI, and plain-web regressions.
- Confirm these rules against the living Blyg 0.3 specification published from revision `e6740e8`, including whole-item directives, publish-time snapshot resolution, reference/version agreement, bare baked wrappers, and the separate `{url}` plain-web Stub form.
- Do not rewrite or republish the two forensic failures, post 73, or any other existing website content.

## 0.9.20 — Blyg-native response stubs

- Start every new Blyg-target Stub—full post or quick Opener—with a genuine whole-item transclusion backed by the Reader's private source record. Publication re-resolves the local snapshot, emits `![[id]]` in `content_md`, records the exact baked version in `transclusions[]`, and keeps `stub_of.version` in agreement.
- Treat that source quotation as one protected block in Write mode: its words cannot be casually edited, but the entire block can be deleted without removing the Stub relationship. Plain-web Stubs remain ordinary editable context because no Blyg item identity exists to verify.
- Share the same publish-time transclusion resolver between ordinary posts and response Openers. Existing published Stubs, including post 73, are not rewritten.
- Keep deleted posts out of the normal Updated, Created, and Alphabetical lists. A separate **Deleted** view retains access to Restore without promoting withdrawals above active writing.

## 0.9.19 — Recoverable fragment validation

- Normalize authored quotation marks in the saved fragment block map at the same time as the article, preventing harmless curly punctuation from producing a false fragment mismatch.
- When a post still has damaged fragment metadata, offer **Remove all fragments and save draft** directly in the error dialog. This preserves the writing and ordinary formatting, removes only reusable fragment boundaries from that draft, and lets the author add them again later.

## 0.9.18 — Visible, editable response stubs

- Put a linked **Stub of:** line and the complete source item directly into every new Stub editor, whether the response is a full post or a quick Opener. The copied source is ordinary editable material, not a frozen quotation, so it can be shortened or removed without losing the immutable protocol target.
- Preserve `stub_of` during the first save of a quick Opener response and publish it as `kind: thread`; ordinary Openers remain fragments.
- Generate the correct Apache alias for standalone threads instead of routing every standalone item through the fragment directory.

## 0.9.17 — Explicit responses and everyday editor controls

- Separate **Stub** from **Quote** in Reader. A Stub creates an immutable response target at the exact Blyg origin, ID, and version seen; it can become either a full post or a quick Opener response, and the composer shows a non-authored response marker.
- Stop Reader-link navigation from silently subscribing to WordPress comments feeds. Ignore comments-feed autodiscovery, retire unmistakable legacy comment subscriptions while retaining Saved/Liked items, and preserve deliberate manual feed subscription.
- Keep 77 entries in the ordinary site RSS feed while retaining the Blyg protocol feed's 50-event notification window.
- Add Command-F/K/B/I in Write, active Bold/Italic toolbar state, and one-container multiline blockquote paste with preserved internal paragraphs and one citation.
- Offer an irrevocable publication pin for new writing: checked by default for a new Opener and unchecked for a new post, persisted with the draft and shown during publication review.
- Normalize curly quotation marks in newly saved authored prose to straight ASCII quotes while preserving Blyg snapshots, cited blockquotes, Reader content, and fork source fidelity.
- Keep the current workspace controls unchanged when a tab change is canceled, and make every opened document—including a native-menu New Post—select its matching workspace.
- Confirm existing `rel="blyg"` discovery against the living Blyg 0.3 specification at source revision `ac932cfeeaa2872f8429c248c39307226bbc6d8a`; feed/object discovery behavior is unchanged.

## 0.9.16 — Stable Saved workspace

- Clear Reader results immediately when opening Saved so unrelated posts never appear beneath the Saved heading while its local shelf loads.
- Ignore delayed Reader responses after the user changes workspaces; the newest screen selection now always wins.
- Keep subscription-sync progress and errors in Reader. Saved uses its own loading and saved-item count messages.

## 0.9.15 — Responsive Reader sync

- Move Reader network operations off the general authoring lock so page opening and draft saving remain responsive while subscriptions refresh.
- Check up to three independent subscriptions concurrently while retaining bounded per-item downloads, overlap prevention, isolated failures, exact version checks, and one atomic cache save.
- Recognize identical Blyg and ordinary RSS/Atom response bodies when a server does not provide ETag or Last-Modified support, while retaining the daily full integrity sweep.
- Make Saved a strict saved-item shelf rather than a Reader view that can drift back to All posts; retain source/search filtering and provide a clear empty state.
- Record and display the local date and time an item enters Saved; label older saved items without fabricating a historical timestamp.

## 0.9.14 — TK robot button

- Replace the TK assistant button's generic star with the same monochrome robot marker used on generated passages.

## 0.9.13 — Quiet Reader status

- Replace noisy per-subscription timing messages with one locally formatted Last sync date and time while continuing to show genuine feed errors.

## 0.9.12 — Workspace tabs and Blynger identity

- Replace the mixed website sidebar with full-width Posts, Openers, Pages, Images, Reader, and Saved workspaces while retaining the beveled Windows-era controls and neutral writing surface.
- Give each workspace a dark-green-to-blue tab and matching foundation color; toolbars and the editable document remain neutral.
- Add post search plus Updated, Created, and Alphabetical ordering. Keep permanent Pages in their own simpler list.
- Make Openers a full editor workspace with the ordinary formatting toolbar, including the explicit Blockquote action; TK remains post-only.
- Add an Images workspace that shows each image's dimensions and the HTML pages that currently use it. Existing insertion and upload behavior remains available from an open draft.
- Move Settings and About Blynger into the native application menu, add File and View menus, and place Rebuild Blyg archive under Help.
- Keep post-only authoring controls out of the Openers and Pages workspaces, add Queue and Preview to the File menu, and provide a concise Help window that maps the six workspaces and publication controls.
- Adopt the new robot-counter B mark as Blynger's in-app and macOS application icon, with its interior matched to the Posts tab green.

## 0.9.11 — Explicit Blyg discovery

- Advertise the configured Blyg origin with `<link rel="blyg" href="/blyg/">` on newly generated or legitimately republished Blyg post/thread pages, standalone fragment and Opener permalinks, new pinned-version pages, the Blyg index, and a touched homepage.
- Keep Portfolio, the aggregate Openers page, Privacy Policy, and ordinary standalone Pages outside Blyg discovery and identity metadata.
- Advertise the ordinary site feed as `/feed.xml` with standard RSS autodiscovery; never use `/blyg/feed.xml` as the ordinary-page autodiscovery target. The manifest and protocol feed chain remains unchanged.
- Preserve forward-only static history: unchanged historical website pages and generated fragment pages are not rewritten solely to backfill discovery links.
- Add Blynger's mission statement to the README.

## 0.9.10 — Durable editor saves and portable forks

- Resolve relative links and media addresses against the source Blyg origin before pinned writing enters a fork draft. Root-relative, path-relative, and already-absolute addresses now remain correct when the fork is published on another website.
- Preserve declared media missing from `content_html` when copying a pinned version, while using only the exact selected current or historical pinned document. Sanitization and immutable fork lineage remain unchanged.
- Serialize editor saves and retain an explicit unsaved state when a request fails or newer typing occurs while a save is pending. A completed older save can no longer reload over newer writing.
- Ignore delayed page loads and background refreshes after a newer request or edit. Publication and other save-dependent actions stop when the current editor state has not been saved successfully.
- Add delayed, failed, retry, overlapping-operation, historical-pin, address-resolution, and fork-publication regressions.

## 0.9.9 — Stable addresses and reliable publication retry

- Preserve an item's first published `page` permalink when later edits change it from a fragment into a thread. Previously shared links and the ordinary RSS GUID remain stable while the item's current `kind` can still advance.
- Record the exact approved local commit before pushing. If the push fails, **Retry publication** now retries that commit after checking the hosted branch, and can also safely finish bookkeeping when the host accepted a push whose connection response was lost.

## 0.9.8 — Stop stale-Mac overwrites

- Compare a refreshed hosted branch with its common local baseline before publication. If the hosted site has newer versions of any files the prepared publication would replace, stop with a clear conflict instead of overlaying stale local pages or Blyg history onto the newer commit.
- Continue inheriting unrelated hosted additions, such as a newly added `robots.txt`, without turning them into local deletions.

## 0.9.7 — Preserve hero-image placement with fragments

- Prevent an image intentionally placed outside a post's article from being shown a second time inside the article when Blynger renders fragment links. The managed image remains in the Blyg item, while the human page keeps its original historical placement.

## 0.9.6 — Safer forks and durable publication

- Sanitize pinned remote Blyg markup before it becomes editable fork content, removing scripts, event handlers, unsafe URLs, and other active remote HTML before any static page can be generated.
- Reuse unchanged published quote snapshots without requiring their original Reader cache to remain available, so unrelated work can still be prepared and published safely.
- When a genuine quoted source advances while a response is still a draft, retain the response identity but record the source version actually quoted in the published `stub_of` lineage.
- Keep ordinary RSS entries on their original publication date and stable identity while serving the current corrected post content.

## 0.9.5 — Complete feed publication and clearer archive maintenance

- Include the top-level `/feed.xml` in Blynger's strict website publication allow-list so the new ordinary-reader feed is actually reviewed and published alongside the Blyg protocol feed.
- Rename the rarely needed **Refresh Blyg copies** control to **Rebuild Blyg archive** and explain in the interface that ordinary publishing is automatic; use this maintenance action only after a Blynger upgrade or to repair the archive.

## 0.9.4 — Blyg 0.3 conformance

- Bring the published Blyg surface into line with the living 0.3 Level 2 specification at official source revision `4fb29cfe600007a5cb9ac3996b0d4c4cf075f46d`.
- Keep Blynger headlines as private authoring and website presentation while removing the non-protocol `title` and `url` members from item JSON. Emit origin-relative `page` permalinks and add the recommended JSON alternate link to human pages.
- Make `/blyg/feed.xml` the complete protocol notification feed: one entry per publish event, a 50-event window, latest rolled-up content on historical events, derived RSS titles, all fragments and threads, and exactly one entry for a withdrawal.
- Add a separate `/feed.xml` for ordinary site readers. It keeps the site's quieter policy of first publications of posts and new Openers only, without `blyg:` metadata; edits, reusable in-post fragments, and ordinary site pages stay out.
- Publish Level 2 manifests, titleless item documents, media-free pin documents, valid thread stubs and withdrawal endcaps, and silent `[[id]]` internal links. Reject the reserved `![[id@vN]]` form.
- Re-resolve genuine whole-item and source-fragment transclusions from the latest local Reader snapshot whenever their containing thread is published, with bare protocol blockquotes and exact origin/version provenance. Keep highlighted excerpts as ordinary frozen citations because partial transclusion remains ruled but nonnormative.
- Treat Blyg item titles received from other clients as unknown fields rather than protocol headlines. Reader display labels are presentation-only; RSS/Atom and web titles remain ordinary source metadata.
- Preserve existing public HTML unless a page is actually authored or needs the specific discovery/correctness repair. No website files were published by this release work.

## 0.9.3 — Queued work and Reader corrections

- Add an explicit Queue control beside Review & publish. It saves the current page as a private draft for the next publication and leaves the author free to work elsewhere; it never publishes by itself.
- Add subscription removal to Manage subscriptions. Removing a feed stops future syncs and clears ordinary cached entries while retaining locally Saved or Liked items.
- Link blogroll names to the website root rather than its feed address, including ordinary RSS/Atom subscriptions such as xkcd.
- Sort Reader items by their original publication time so later revisions and observations do not keep old posts pinned above newer writing.
- Make Open original honor a Blyg item's declared `page` permalink, with the canonical item URL and conventional Blyg permalink as fallbacks.
- Expose transcluded fragments in an opened Reader thread as named choices that can be selected and quoted independently.
- Keep HTML source editable on fragment-aware pages and reconcile its blocks back to stable private fragment identities when returning to Write or saving.
- Append an unobtrusive linked source host such as `—apnews.com` to ordinary cited blockquotes.
- Center newly inserted images and offer Standard, Small, Wide, and Full width choices; Standard is the smaller of 400 pixels and 77 percent of the viewport.
- Keep releases in the 0.9.x line. Blynger must not be labeled 1.0.0 without the owner's explicit approval.

## 0.9.2 — Recoverable fragment breaks

- Repair fragment breaks automatically when browser editing removes or merges the paragraph carrying their private anchor, retaining fragment identity whenever its writing remains.
- Discard harmless orphaned editor-only dividers during saving instead of trapping the draft behind an unexplained error; leave all authored prose unchanged.

## 0.9.1 — Visible subscription management

- Add a dedicated Manage subscriptions window to the Reader, listing every feed subscription with an explicit Show on blogroll checkbox.
- Explain in place that Saved and Liked posts are independent of the subscription-level blogroll and that blogroll changes affect future posts only.

## 0.9.0 — Faster Reader and fuller Blyg authoring

- Make unchanged Reader syncs stop after a conditional feed `304`, reconcile changed item versions with four bounded workers, heal the archive index daily, isolate subscription failures, prevent overlapping syncs, and expose useful timing/error diagnostics. Sync on Reader open and every 90 minutes while it remains open.
- Open arbitrary public URLs in the Reader. Genuine Blygs retain their protocol identity; ordinary feed entries and sanitized webpages retain only their real web URL. Reader links continue inside Blynger, with a separate Open original action.
- Retain ordinary Reader items for three years, clear unsaved cached media after one year, and add persistent local-only Saved and Liked views. Neither marker enters Blyg output.
- Align highlighted Blyg quotations with the living specification's still nonnormative partial-transclusion ruling: exact/prefix/suffix selectors, faithful source/version provenance, `blyg-partial`, and no invented ID. Allow repeated quotations from one source in the same response draft with one immutable `stub_of` target.
- Add pinned-version forks as independent editable drafts with immutable `forked_from` lineage and no automatic transclusion. Do not add Webmention machinery.
- Add semantic blockquotes with optional citations, direct-image-URL insertion with responsive size classes, normal paragraph semantics, easier-spaced HTML source, Command-F source search, and source opening near the Write cursor.
- Make Fragment additive, add a separate Remove fragment action, and make H2 begin a fragment without duplicating an existing boundary.
- Change publication feedback to disabled Posting, then enabled Close; preserve retry behavior after failure.
- Keep the existing version/pin view, retain pin media/provenance, add a right-aligned RSS link to public version lines, and remove leading zeroes from human-facing dates only.
- Add opt-in standard OPML blogroll output. Newly published posts freeze the current curated blogroll into a static responsive side rail; later subscription changes do not rewrite old posts. The heading is a private setting.
- Consult the living Blyg 0.3 specification and official repositories at spec commit `4fb29cfe600007a5cb9ac3996b0d4c4cf075f46d` and reference-studio commit `0f5714009e262fada9aff712a2f68b998cc92fbb`.

## 0.8.7 — Tolerant Openers saving

- Reconcile harmless browser-repaired Openers block layouts instead of blocking a valid draft with an inconsistent-layout warning.
- Preserve the established fragment identities and the author's complete page source while rebuilding only the private block map.

## 0.8.6 — Simpler fragment breaks

- Make Fragment act at the paragraph containing the cursor: that paragraph begins a new fragment and eligible text above it becomes the preceding fragment.
- Remove the fragment-versus-ordinary-prose distinction from the dialog and replace its controls with plain add/remove-break and remove-all-breaks actions.

## 0.8.5 — Fragment context

- Give newly generated in-post fragment pages a `FROM: Original post title` heading and a `Full thread` link back to the enclosing post above the version display.
- Include standalone fragment permalinks in the sitemap while keeping reusable in-post fragments out of RSS; the enclosing thread remains the single feed announcement.

## 0.8.4 — Private installation settings

- Move the website location and identity, navigation, Blyg/feed labels, runtime paths, and the configured Git host Git/SSH details out of application code into one private JSON settings file.
- Add a Settings screen that displays and edits those values while storing only the SSH key path, never the key contents.
- Ship placeholder example settings for future installations and make new metadata, Blyg objects, feeds, navigation, and signatures use the configured identity.
- Keep existing static pages forward-only for design and harmless historical metadata: changing settings affects newly generated or explicitly edited output, while necessary privacy, security, compatibility, and correctness repairs may still update older files with explicit authorization.

## 0.8.3 — Monochrome robot marker for TK passages

- Give newly styled TK passages a dashed grayscale enclosure with a small monochrome robot at the lower-left corner, visually distinct from quoted Blyg boxes without adding a written label.
- Preserve the embedded TK styling of previously generated pages instead of back-propagating the new treatment.

## 0.8.2 — Post-only TK assistant

- Enable TK only while editing posts; keep it unavailable on Openers, Home, Portfolio, Privacy Policy, and ordinary standalone pages.
- Enforce the same restriction in the local server so a direct request cannot generate text for a non-post page.

## 0.8.1 — Honest review of file removals

- Include explicitly removed website pages in publication review and Git publication instead of showing a misleading zero-file review.
- Label removals clearly in the review and generated Git update note.
- Return Review & publish to its inactive state after the removals are successfully published.

## 0.8.0 — Ordinary standalone pages and a strict Blyg boundary

- Add New page with an editable title, safe custom `.html` filename, automatic filename suggestion, and the existing local-first editor and site template.
- List newly created standalone pages separately in Blynger, include them in the sitemap, and leave homepage linking entirely manual.
- Keep ordinary pages out of RSS and all Blyg item, archive, fragment, identity, provenance, and version behavior.
- Correct the broader publication boundary: Home, Portfolio, Privacy Policy, and the aggregate Openers page are site furniture, not Blyg items. Individual Openers and post pages remain Blyg content.

## 0.7.11 — Focused archive cleanup and quotation summaries

- Prefer an author's own response when generating a description for a quoted post, rather than using the source attribution or quoted text.
- Remove obsolete Open Graph tags written with typographic quotation marks whenever Blynger refreshes a page's metadata.
- Stop classifying the archived, unfinished `graphicnovels.html` experiment as a main website page.

## 0.7.10 — Independent application repository

- Move Blynger application source out of the website tree into `/path/to/Blynger/` with its own Git repository.
- Keep website files in `/path/to/your/site/` and preserve the existing private drafts, settings, reader cache, IDs, and history by deriving private storage from that unchanged site root.
- Update the native Mac launcher to start Blynger from its new source folder.

## 0.7.9 — Durable reconciliations and publication readiness

- Adopt accepted external metadata and surrounding HTML into the private editing source, so those harmless changes survive the next edit while fragment-aware authored content remains intact.
- Refresh Review & publish readiness immediately after queuing a permanent version pin or copying a historical version into a revision draft.

## 0.7.8 — Honest publication button

- Gray out and disable Review & publish when there are no drafts, pins, or publishable website-file changes.
- Highlight the button immediately when writing changes or other publication work exists, and restore its settled state after publication.

## 0.7.7 — Publication-only RSS

- Keep Home, Portfolio, Privacy Policy, and the aggregate Openers page out of RSS.
- Announce only a post's first publication and each new Opener; later edits and reusable in-post fragments remain in Blyg JSON without becoming RSS entries.
- Retain required withdrawal announcements for previously published posts.

## 0.7.6 — Safe external-change reconciliation

- Name fragment pages whose public files no longer match their private safety records instead of showing an unactionable warning.
- When writing, links, and fragment boundaries are unchanged, offer to keep the current static files and continue publication while preserving private fragment identities.
- Rebuild Blyg mirrors from the archive without re-rendering untouched historical HTML pages; only authored pages and explicitly pinned pages receive page-level output.
- Continue to stop when authored content changed, rather than guessing how permanent fragment identities should move.

## 0.7.5 — Focused publication changes

- Preserve an existing page's generator metadata across Blynger upgrades so a release number alone does not rewrite every HTML page.
- Calculate tracked publication changes in one Git pass and inspect pending paths only when they are genuinely new files.
- Document the site's forward-only static-history rule: preserve old page design and harmless metadata unless an explicit edit or necessary repair requires a change.

## 0.7.4 — Faster publication review

- Skip the discarded first review when using Review & publish; retain the single hosted-baseline check before showing the publication dialog.
- Write and track only files whose bytes actually changed, so unchanged regenerated pages and Blyg files do not enter the review workload.

## 0.7.3 — Withdrawal feed correctness

- Emit exactly one RSS entry for a withdrawn item, using the withdrawal event and title, while omitting its earlier feed events as required by the Blygger specification.

## 0.7.2 — Post menus and stable regeneration

- Restore the five linked navigation images above and below new posts, outside RSS/article content. Repair missing footers on Blynger-template posts during the next publication.
- Stop metadata regeneration from accumulating blank lines on quoted posts.

## 0.7.1 — Homepage post-list detection

- Recognize the Posts heading at any heading level, including inline formatting, when adding new posts. Preserve heading styling and prevent duplicate links.

## 0.7.0 — Reader selections and frozen quotations

- Quote whole Blyg items, actual source fragments, or highlighted excerpts with truthful source attribution.
- Add ordinary RSS/Atom imports to the existing reader and quote workflow.
- Preserve selected source text and versions through refresh, draft reload, and publication.
- Keep subtle source-fragment dots in the reader and source metadata in published excerpts.
- Verify four quote modes with disposable publication tests. See QUOTING.md for protocol scope and details.

## 0.6.3 — Quoting and reversible deletion

- Resolve standalone quotation markers even after accidental heading formatting; keep inline/code examples literal.
- Insert new reader quotations directly into the draft body without inheriting editor heading formatting. Custom titles in the initial dialog remain supported.
- Add confirmed Delete post / Restore post controls. Keep a private recoverable copy, remove homepage listings on publication, and publish Blyg withdrawal endcaps while preserving IDs and pins.

## 0.6.2 — RSS feed identity

- Add the standard Atom self-link to RSS so readers can identify its canonical feed URL.

## 0.6.1 — Complete quotation boxes

- Enclose complete quoted source content in one gray box, including any opening prose before generated passages.
- Show an explicit source title as H4 when supplied, followed by the source author attribution inside the quote. Untitled sources remain untitled.
- Keep attribution within newly inserted quotations and preserve source identity/version metadata.

## 0.6.0 — Blyg reader and quotations

- Add Edit headline for response posts without changing quoted source content.
- Keep remote quotes outside automatic TK fragment ranges so quotation plus generated commentary publishes normally.
- Put future published Openers in RSS while excluding the historical import and aggregate Openers page.
- Add Blyg URL discovery dialog, subscriptions, manual RSS/index sync, offline reading, source filters and text/author search.
- Share Quote post selection across published local fragments/threads and cached remote items; preserve remote provenance using the demonstrated 0.3 quotation extension.
- Keep imported documents private and separate from authored publication objects.
- Expire downloaded remote image/video items after 365 days without touching authored writing or published media.
- Add the main Fragment button using the existing shortcut command; remove dead header menus.
- Show immediate preparation/publication feedback, prevent duplicate clicks and restore controls after success or failure.
- See READER.md for protocol limitations and verification.

## 0.5.0 — Openers and public fragments

- Share post fragment identities, versions, provenance, and permalinks with Openers. Migrate privately with a backup and preserve existing text, date labels, ordering, and anchors.
- Add New opener dialog with automatic local dates and same-day Roman numerals; save as a local draft.
- Publish quiet margin dots linking each fragment; keep protocol content free of presentation markers.
- Make post dividers create reusable sections directly. Preserve explicit ordinary-prose choices.
- Keep repeated publication preparation from falsely reporting an external file change.
- See OPENERS.md for migration, interoperability, and verification details.

## 0.4.0 — Intentional fragments

Added a Fragment toolbar button and Control+Shift+F dividers, private block anchors, reusable Blyg fragment publication, and automatic TK/body sections excluding titles and bylines. Fragment identities survive revisions; published fragments remain available after unmarking. See FRAGMENTS.md for behavior, interoperability, and tests.

# Blynger releases

## 0.3.1 — 2026-09-26

- Reduce the public Versions footer to a subdued 12px line; expand pinned history on demand. Posts show it immediately below their byline date.
- Serve stable Blyg thread and fragment permalinks through exact Apache aliases to existing public pages.
- Reject unknown IDs and wrong-kind routes; preserve pinned pages and JSON endpoints.
- Feed and archive links now use the stable human permalinks; legacy canonical page URLs remain valid.
- Preserve thread kind when edits shorten it, and preserve relative asset/link resolution at aliases.
- Add real Apache regression coverage for routing and subsequent versions.

## 0.3.0 — 2026-09-26

- Native Mac window replaces the default-browser launcher.
- Closing the window or choosing Quit stops the app-owned server.
- Unsaved edits prompt before quitting; saved drafts persist.
- Native Edit menu, file picker, and JavaScript dialogs retain editor functionality.

## 0.2.2 — 2026-09-26

- TK Markdown links and bare URLs render as clickable, sanitized HTML before insertion.
- Raw generated HTML remains escaped; the generated-text wrapper is preserved.
- Regression tests cover generation, saved test posts, Git publication, Blyg JSON, and RSS.

## 0.2.1 — 2026-09-26

- Git publication messages now name created/changed pages automatically.
- Optional publication note supports concise summaries of broader changes.
- Notes are retained locally until a successful publication.

## 0.2.0 — 2026-09-26

- Private published-version archive, revision notes, and restoration into a new draft.
- Explicit permanent Blyg pins and public version footers linking pinned snapshots.
- Same-origin fragment quotations resolved when publishing a revision.
- Sequential numbered filenames for future posts; existing URLs preserved.
- Automatic Open Graph, social cards, canonical links, descriptions, structured data, and Blyg discovery metadata.
- Publication sitemap and cleaned robots.txt with existing crawler policy preserved.
- Central app/protocol version constants and displayed release number.

## 0.1.0 — initial prototype, 2026-09-25

Retrospective label for the original editor, image library, TK assistant,
Blyg export, Git publishing, and Mac launcher. Changes before 0.2.0 were
not individually released or assigned formal version numbers.

App versions and Blyg protocol versions are independent. Metadata identifies
both. Development remains pre-1.0; no promise of a stable internal data format.
