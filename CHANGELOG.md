## 0.12.0 — Safer publishing and recovery

- Prepare publication reviews in the background so large sites no longer leave the native window waiting on one long request or produce a misleading **Load failed** message.
- Keep the interface responsive while preparation and hosted-version checks run, and retain the existing guided recovery messages when preparation finds a fragment problem.
- Tolerate a window or browser disconnecting after background work has begun without turning it into another server error.
- Correct private-state validation: pending publication paths are filenames, not object records. Valid prepared work is no longer mistaken for damaged state after reopening Blynger.
- Bind confirmation to the exact drafts and pins rendered for review. If either changes, Blynger asks for a fresh review before creating a commit, and successful publication clears only work actually represented in that commit.
- Refuse another Review, Prepare, or hosted-version refresh while an approved publication is being sent, so another window cannot rewrite files beneath the exact commit in flight.
- Restore Studio and Reader recovery snapshots without replacing the verified backup with the state being abandoned, and repair Reader's main state after startup recovery while retaining that backup.
- Preserve a timestamped copy whenever a later save encounters an invalid Studio or Reader state file instead of silently replacing the rejected bytes.
- Keep an Opener Stub's source attached to its durable heading identity rather than its submitted list position, so reordered metadata cannot move or duplicate provenance.
- Treat a Reader media-write failure as an isolated warning and save synchronized items and watermarks in a final durability step even when later sync work fails.
- Add separate **Transclude** and **Respond / Stub** actions to the Post editor. Each accepts one Blyg item permalink, imports only that verified item without subscribing to or crawling its source, and inserts its protected snapshot; only **Respond / Stub** records a permanent response target.
- Add regression coverage for long-running review preparation and for reopening state that contains pending filenames.

Recovery note: diagnosis preserved the pre-finish snapshot as `state.preserved-backup-c43c718-20261017-132006.json`. It is for recovery inspection only and must not be restored wholesale because it contains an already-completed publication marker. All visible writing in its sixteen draft records has been confirmed present in the published pages.

## 0.11.3 — One fragment snapshot per save

- Move a new, never-published Post draft to an unused number so gaps can be filled without overwriting or renumbering anything already published.
- Release a discarded draft's number after confirming it never had a public file or published Blyg history; genuine withdrawals remain permanently reserved.
- Capture durable fragment markers and their private fragment map atomically. A final browser-side boundary reconciliation can no longer leave a new or edited Post with HTML from one layout and fragment metadata from another.
- Preserve a fragment boundary that begins on a Blynger-managed image when publication copies that exact immutable image from its private authoring address to its public Blyg media address.
- Keep the strict server check: malformed or genuinely damaged fragment layouts are still rejected rather than silently publishing the wrong ranges.

## 0.11.2 — Publish, then keep writing

- Close the publication review as soon as the exact approved commit, included drafts, and queued pins have been durably preserved. The slower network push now continues in the background while the editor remains available.
- Report success quietly in the status bar. Show an attention dialog only when the background publication fails or its remote result is uncertain.
- Preserve every draft, edit, and queued pin created after publication starts, and build published history from the approved commit rather than whatever files happen to exist when the push finishes.
- Refuse a second overlapping publication, retain interrupted work for exact-commit Recovery, and make Recovery retries use the same non-blocking flow.
- Add delayed-push regressions covering intervening drafts, intervening edits, concurrent publication refusal, exact artifact history, and restart recovery.

## 0.11.1 — New Openers complete durable migration

- Reconcile newly inserted Opener blocks against the exact editor block map submitted in the same save, then write their durable identities automatically. A partially migrated Openers page no longer mistakes a normal new entry for damaged fragment state.
- Report durable-marker failures as fragment-state errors tied to the affected page.
- Offer **Rebuild fragment markers and save draft** for both Posts and Openers. This non-destructive repair keeps the current writing and fragment identities; Posts retain the separate last-resort option to remove all fragment designations.
- Rebuild a malformed unsaved Opener identity from its durable heading while keeping every persisted published identity authoritative, so the recovery action completes instead of returning a second error.
- Reconcile the browser's temporary Opener identity map before strict validation, reserving every persisted identity first. A genuine Reader Stub can no longer fail before the Opener repair path runs.
- Preserve durable fragment placement when an exact Stub transclusion is refreshed from Reader or converted back to its private authoring directive. Fragmented Posts containing genuine transclusions can now be revised normally instead of losing the transclusion block's identity during save.
- Describe marker rebuilding accurately in the recovery dialog; it does not remove Opener fragments.
- When Backspace removes a protected Stub transclusion, keep the following paragraph and place the cursor beneath **Stubbing:** instead of collapsing it into the Stub label.
- Open Reader items by clicking their cards, remove the redundant **Read** button, expose separate **Opener Stub** and **Post Stub** actions, and group quotation, saving, liking, and private reactions across the card width.
- Keep **Fork** visible but disabled when an item has no pinned version, with **Requires a pinned post** on hover, instead of silently hiding the protocol requirement.

## 0.11.0 — Durable fragment identities

- Store stable block, fragment, and boundary identities directly on the top-level blocks of fragment-aware article HTML. Whole-block moves and ordinary text edits now carry their identities with them instead of depending solely on a separate positional map.
- Recover the fragment map from those durable HTML markers when its private cache is absent, while retaining existing private metadata for compatibility and extra Opener/Stub state.
- Migrate older fragment-aware drafts lazily on their next save. Existing pages are not rewritten merely by opening Blynger.
- Keep durable authoring markers on the human article only. Canonical Blyg `content_html`, `content_md`, transclusions, and hashes remain free of Blynger-private attributes.
- Make **Remove all fragments** clear both the cached map and the durable HTML markers without deleting previously published fragment identities or history.

## 0.10.23 — Reader links reach the browser

- Route Reader links through a native navigation handoff that WebKit cannot silently drop, while retaining strict scheme validation before opening the default browser.

## 0.10.22 — One headline while writing

- Hide the page's internal headline in Write mode because the document header already displays it. The real `<h1>` remains intact in HTML source, Preview, fragment bookkeeping, and the published page.
- Detect saved Series memberships whose generated furniture is missing during publication review, so a lost pending marker cannot leave a published member without its Series subtitle, canonical headline, index entry, or navigation. Unrelated Series are left alone.
- Preserve adjacent fragment identities when an older HTML normalization removed their shared boundary block, allowing generated Series navigation to be added without deleting reusable fragments.

## 0.10.21 — Reliable Reader links

- Hand ordinary Reader links directly from Blynger's trusted main window to macOS, so they reliably open in the configured default browser. Blyg item links continue to open inside Reader.
- Keep the native handoff restricted to the main application frame and to HTTP, HTTPS, email, and telephone links; imported writing remains isolated in its unprivileged frame.
- Create every new Series empty instead of guessing membership from matching headlines. Only Posts explicitly assigned by the author can join; member decoration and fragment validation wait for Review & publish.

## 0.10.20 — Series choices follow the draft workflow

- Remove the separate **Update series** action. A Post's Series and detail are now saved with its ordinary draft, while the generated Series index, subtitle, canonical headline, and next-installment navigation are created during **Review & publish**.
- Preserve reusable fragment identities when Blynger adds or removes its own Series furniture. Generated Series subtitles and navigation remain outside reusable fragment content.
- Avoid rewriting Series drafts when an ordinary save leaves the membership and detail unchanged.

## 0.10.19 — Whole-app state recovery

- Preserve a damaged private Studio state file and recover from the last verified backup instead of preventing Blynger from opening. If no verified backup exists, open in an explicit recovery state while retaining the damaged original.
- Skip malformed generated Blyg item files during startup without changing them, and report the skipped files through Recovery.
- Keep malformed or orphaned Reader records locally but isolate them from normal listings so one broken relationship cannot disable Reader.
- Extend **Help → Recovery…** with Studio status and verified Studio-backup restoration. Restoring preserves the state it replaces and asks for a restart before further work.

## 0.10.18 — Guided recovery

- Add **Help → Recovery…** as a local, non-destructive control center with explicit publication states: saved locally, prepared locally, status uncertain, or locally finalized.
- Retry only the exact approved commit after a failed or uncertain publication, using the existing snapshot-bound publication safety path.
- Pause and resume troublesome subscriptions without deleting their cache, Saved items, or private activity. Manage isolated malformed items and restore them to Reader when desired.
- Restore the last verified Reader backup while preserving the state it replaces, and copy redacted diagnostics containing counts and status only—never writing, addresses, credentials, keys, or local paths.

## 0.10.17 — Reader recovery and durable private activity

- Serialize all Reader state changes, including publication activity, through one shared re-entrant lock so overlapping actions cannot overwrite one another.
- Reject newly fetched Blyg items with malformed changelogs. If an older malformed cache entry already exists, Pace-layered view remains usable and offers a reversible **Skip this item** isolation action; Newest ordering remains available.
- Start safely when the private Reader state file is damaged: preserve the unreadable file, recover from the last verified backup when possible, and clearly report recovery instead of preventing Blynger from opening.
- Require the tested Pillow 12.3 security baseline for new installations and record the complete tested dependency set in `requirements.lock.txt` for reproducible installs.

## 0.10.16 — Pace-layered Reader

- Add an optional **Newest / Pace-layered** Reader order adapted from Blygger Studio's MIT-licensed reference algorithm at revision `e5ffc32`. New items enter at the top, revisions climb one place, and each pinned version halves an item's sinking speed.
- Explain resurfaced writing directly on its card with version, revision date, pin count, and upward movement. Revised Blyg cards deepen through a restrained green scale while ordinary Web/RSS cards remain unchanged.
- Keep ordinary links inside imported writing out of Blynger: they open in the Mac's default browser. Only recognizable Blyg item permalinks are resolved and opened within Reader.

## 0.10.15 — Truthful long-publication completion

- Use the already refreshed Git index for current-commit path discovery, avoiding needless traversal of a large cloud-synced packed history during review and finalization.
- If WebKit drops a long-running local publication response, check Blynger's durable publication state before reporting failure. A publication that committed, pushed, finalized, and cleared its included draft is now reported as completed rather than **Load failed**.

## 0.10.14 — Reliable Mac restart

- Retire an orphaned launcher-owned Blynger server on the current local port before starting a replacement, while retaining cleanup for the historical port. An older background server can no longer mask a failed new launch, serve a stale interface, or leave the app stuck on **Load failed** after restart.

## 0.10.13 — Publication and series lifecycle safety

- Bind a failed-publication retry to the exact approved commit and its draft and pin snapshots. A successful retry now records history from the bytes actually pushed, clears only the drafts and pins included unchanged in that publication, and preserves all writing or queued work created afterward.
- Preserve authored introductions and other edits on Series pages by replacing only Blynger's managed installment list when membership changes.
- Reconcile affected Series after deleting or restoring an installment so indexes and previous-post navigation cannot retain stale links.
- Bind asynchronous Markdown conversion to its originating document, revision, mode, and selection. If any changes while conversion is pending, Blynger keeps the Markdown in a recovery dialog instead of inserting it into the wrong page.
- Strip Finder and cloud-provider metadata from the installed Mac bundle before its final signature so synced Desktop or Applications folders cannot leave Launch Services reporting a missing executable.

## 0.10.12 — Responsive startup during Git scans

- Load Posts, Openers, Pages, and editing without waiting for the publication-status Git scan. Slow cloud-synced Git metadata can now delay only the Review & publish indicator, while local Git operations receive the same tolerant timeout as commit-tree reads.

## 0.10.11 — Reliable publication review on synced folders

- Give cold Git tree reads enough time for a cloud-synced website folder to wake up, cache immutable commit trees during the session, and avoid reading the same tree twice while building a publication review.

## 0.10.10 — Markdown paste

- Recognize Markdown pasted into Write mode and safely convert its headings, emphasis, links, lists, quotations, fenced code, tables, and rules into normal editable Blynger markup. Ordinary prose and specialized quotation/transclusion paste retain their existing behavior.

## 0.10.9 — TK model disclosure

- Select TK's Codex model explicitly in private Settings and record that exact model with each new generated passage, so its robot disclosure can name the model used. Historical passages without model metadata remain honestly labeled **not stated**.

## 0.10.8 — Series subtitle refinement

- Render series subtitles as right-aligned level-three headings on newly generated or otherwise republished series Posts. Existing published pages remain unchanged until Blynger legitimately touches them again.
- Normalize every assigned Post headline to **POST TITLE: SERIES TITLE**, removing duplicate managed suffixes and removing the suffix again when a Post leaves the Series.

## 0.10.7 — Static series

- Add **File → Create Series…** with a title, short navigation plug, and description. Blynger detects existing Posts whose headlines contain the series title and creates a normal static series Page using the site's current page template.
- Let each Post opt into a Series and record a free-form detail such as a chapter or passage range. Series pages list their installments chronologically with those details and enter the sitemap as ordinary Pages.
- Add a linked italic series title beneath each member Post headline. When a later installment is assigned, queue an idempotent **Next PLUG: TITLE** link on the preceding Post while leaving ordinary RSS eligibility unchanged.
- Keep Series records in private Blynger state while publishing only ordinary static HTML. Series pages remain site furniture rather than Blyg items.

## 0.10.6 — Reader images inside the security boundary

- Restore cached images and other media in opened Reader items after the opaque-frame security hardening prevented WebKit from loading local media routes.
- Embed only Blynger's already validated, content-addressed cache files into the isolated Reader document. Imported writing remains in its opaque sandbox and receives no access to Blynger's interface, API token, private state, or network.
- Add a regression that verifies cached media becomes an inert data resource for isolated display while normal quotation and publication paths retain their established managed-media URLs.

## 0.10.5 — Reliable local app replacement

- Keep the installed Mac application at its stable path when rebuilding, avoiding a Finder-managed rename that could leave a stale question-mark launcher behind.
- Verify the installed bundle after replacement and retain Blynger's stable signing identity and remembered Documents-folder permission.

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
