# Reader — current behavior in Blynger 0.9.34

The protocol source of truth for this release was the live [Blyg 0.3 specification](https://blygger.org/spec/0.3/), checked against official specification source commit `fde93b694a401d3c458b34dfac84fc833ba861dd`. Human Blyg pages advertise their origin base with `rel="blyg"`; readers resolve that link and probe the fixed `blyg.json` manifest. Older implementation reports below are retained as history, not as the current feature boundary.

## Imported-content security boundary

Imported Blyg, RSS/Atom, and ordinary-web HTML never enters Blynger's privileged document. It is sanitized with `nh3` and rendered in an opaque sandboxed frame. The frame cannot read Blynger's DOM or API token, submit forms, call local routes, navigate the parent, open nested frames, or run source-provided scripts. Its own deny-by-default Content Security Policy permits only locally cached Reader media and one exact local Blynger bridge script.

That bridge has a deliberately small vocabulary: selected text, selected genuine-fragment index, and a clicked safe link travel out; a requested fragment selection travels in. Every message is bound to both the exact frame window and a random per-opening channel. Quote, Stub, Fork, Open original, Saved, Like, and private-response controls remain in the trusted outer application.

The Reader sanitizer removes arbitrary source IDs and classes in addition to active HTML, event handlers, styles, forms, and dangerous URL schemes. It preserves only safe structural/media attributes and the specific shared `blyg-tk-gen`, `blyg-transclusion`, and `blyg-partial` conventions Blynger understands. The main application document separately uses a deny-by-default Content Security Policy.

Every remote request resolves its hostname once, rejects the request if any
result is local or private, and connects to the exact validated address rather
than allowing the networking layer to resolve it again. Redirect destinations
receive the same check. HTTPS certificate verification continues to use the
requested public hostname. Untrusted RSS, Atom, and discovery XML is parsed
with `defusedxml`, so declarations and entity expansion are rejected.

Blyg item documents are titleless. The Reader preserves unknown imported
fields verbatim but does not treat another client's `title` member as protocol
data. Its compact list label is presentation derived from the item text; that
label is never written back into item JSON. Ordinary RSS/Atom and web sources
retain their real source titles.

## Sync and diagnostics

Each subscription keeps conditional-response state (`ETag` and `Last-Modified`). An unchanged Blyg feed returning 304 ends the normal sync immediately. Blynger also recognizes an identical response body from servers without those cache headers. A changed feed conditionally checks the archive index, compares index versions with local watermarks, and downloads only changed/new canonical documents with at most four concurrent requests. Up to six independent subscriptions are checked concurrently, so one slow origin does not make every other origin wait behind it. Once daily, Blynger forces an archive-index and recent-item reconciliation so missed notifications and improper same-version edits are still detected. Ordinary RSS/Atom feeds retain only a response hash rather than a complete duplicate feed body. When channel metadata changes, per-entry hashes skip unchanged entries before sanitization and media inspection; a normalized-content comparison catches XML-only reformatting.

The Reader rejects overlapping syncs, retains good cached content on failure, continues after an individual subscription fails, labels network versus invalid-data errors, and records duration, checked-item, and downloaded-item diagnostics. A Blyg item whose declared origin or content hash fails verification, or whose bytes change without a version change, is rejected before storage; a previous good cached version remains readable and the Reader status names the rejection. Reader network work uses a dedicated lock rather than Blynger's general authoring lock, so opening pages and saving drafts remain available during a refresh. Reader-dependent actions wait for a consistent cache snapshot. Opening Reader starts a sync; a 90-minute in-app timer repeats it while Reader remains open. Nothing survives Blynger's process as a background daemon.

Remote work is intentionally bounded: 500 entries from one ordinary feed,
2,000 rows in one Blyg archive, and 100 changed canonical Blyg documents per
refresh. Remaining changed documents are queued for the next refresh. An item
may request at most 16 media files; each response is limited to 8 MB and one
subscription refresh may download at most 64 MB of media. Limit and integrity
messages use the same visible Reader diagnostics as network failures.

The reading desk shows one local **Last sync** date and time rather than per-subscription performance timings. Actual feed errors remain visible; detailed timing stays in private diagnostics for troubleshooting. The Saved shelf has its own local loading and item-count status rather than subscription-sync messages. Switching between Reader and Saved clears the prior list immediately, and delayed responses are discarded when they belong to a workspace the user has already left.

Blyg-native items and ordinary Web/RSS items have separate badges and quiet
background treatments in both the feed and opened-item view. Generated passages
using the interoperable `blyg-tk-gen` class display the robot convention used by
Blynger and Blygger Studio. When `generated[]` is present, Reader exposes the
imported version-level model, date, and source-count claim and labels it as
self-reported rather than verified.

The Saved shelf records and displays the local date and time when an item is saved. Items saved before that field was introduced remain labeled honestly rather than receiving an invented timestamp.

## Private signals and activity

Like remains a separate local `👍` action. Reader also offers five private
responses—`🤯`, `🙄`, `👎`, `😂`, and `❓`—with at most one of those responses
active on an item at a time. A response does not replace Like, so both may be
present. Setting, changing, and clearing these choices appends an event to the
private activity history.

**Saved → Private activity** lists Saved/unsaved, Like/unlike, emoji-response,
published-quote, Stub, and fork actions newest first. Publication actions are
recorded only after the website push succeeds, never when a draft button is
clicked. Each remote target is keyed by origin plus item ID, so its record
survives unsubscribing. The one-time migration reconstructs what it can from
current markers and publication history and labels those entries as earlier
records rather than inventing an original click time.

The implementation is isolated in `interactions.py`, adapting the interaction
log introduced by MIT-licensed Blygger Studio 0.28.1 at source revision
`f036594c70542a4853ccd3ae985ebb37b85fae9d`. Blynger stores the actual records
only inside `remote-reader/reader.json` beneath the configured private support
directory. The source repository contains the mechanism, never the operator's
log. Activity is excluded from HTML, Blyg objects, both RSS feeds, OPML, the
website Git repository, and the sanitized public-source export.

## URLs and local reading state

**Open URL** uses the same resolver/cache as subscriptions. Genuine Blyg URLs retain origin, ID, kind, version, page, and provenance. Feed-linked pages reuse a matching L0 item when possible. A plain webpage receives a sanitized local Reader representation with its real URL and no invented Blyg identity. HTTP(S) links in an opened article follow this path inside Reader. **Open original** deliberately opens the item's specific public `page` permalink in the normal browser, falling back to its canonical URL or conventional `/f/` or `/t/` route. Reader order uses original `created` time, clamped to first observation for implausible future dates, so a later revision does not repeatedly bump old writing to the top.

Reader navigation and feed subscription are separate. Following an article link
does not silently subscribe to an RSS document it happens to reach. WordPress
`wfw:commentRss`, `<comments>`, and `slash:comments` metadata never create
subscriptions or Reader posts. **Add subscription** can still deliberately add
a comments-feed URL. A one-time cleanup disables unmistakable legacy
comments-feed subscriptions created by the former navigation behavior, deletes
only their unmarked cache entries, and retains every Saved or Liked item.

An opened genuine Blyg item presents **Quote** and **Stub** as peer actions.
Quote imports material but does not declare a response. Stub creates a thread
whose immutable `stub_of` records the exact origin, ID, and version seen, plus
a nonnormative local citation aid allowed by the protocol. For both a full post
and a quick Opener, Blynger places a linked **Stubbing:** line and the complete
source item directly into the editor before the response. This copy is normal
editable material rather than a transclusion: it can be shortened or deleted,
but doing so does not remove or change the response identity.

Unsaved Reader items expire three years after immutable `first_downloaded_at`. Unsaved cached media may be cleared after one year while the text remains readable. **Saved** items and all their cached media are exempt indefinitely. **Liked** is a separate filter. Saved, Like, and emoji responses are local fields only: the current specification defines no reaction/thumb wire format, and Blynger emits none of them in JSON, RSS, OPML, nor public HTML.

## Forks, pins, and blogroll

Fork is offered only for a pinned genuine Blyg version. It copies authored content into an editable local draft and stores immutable `{origin, id, version}` `forked_from` lineage. Before the copy leaves Reader, its sanitized relative links and media addresses are resolved against the source Blyg origin, and declared media absent from the markup is retained. Historical forks use only the exact selected pinned document, never current-version content or media. It is not a transclusion and does not add a reference merely because it was forked. An unavailable older remote pin cannot be copied safely; the action fails clearly. Blynger did not add a Webmention system.

Current Blyg 0.3 requires a fork of a composed thread to flatten inherited
transclusions rather than reasserting another publisher's verification. Blynger
therefore converts inherited baked transclusions into ordinary editable
blockquotes with visible source links, removes their protocol verification
classes and attributes, and carries inherited generated-text disclosure with
empty local sources. The fork itself retains only its one-hop `forked_from`
custody claim.

When an imported thread is a Stub, its card shows **Stub of:** and its opened
reading view places a left-aligned **← Backward** control above the writing.
The label prefers the Stub's frozen `cited.excerpt`, then its cited source or
cached target text. Cached targets stay inside Reader; uncached Blyg or
plain-web targets open at their public address. Direct responses already known
to the local Reader appear below the writing as right-aligned **Forward →**
controls. More than one response remains visible as branches. This is an
explicitly incomplete local conversation lens, not a claim that Blynger has
discovered every response and not a new protocol field.

Links clicked inside imported writing open in the normal browser. Blynger's
own Backward and Forward conversation controls keep cached targets inside the
Reader, so following the known response path does not unnecessarily leave the
application.

Subscriptions are private by default and separately opt into **Show on blogroll**. When at least one is selected, Blynger emits standard OPML 2.0 at `blyg/blogroll.opml` and advertises it from the manifest. No custom OPML attributes are used. Each newly published normal post freezes that day's selected entries into static HTML in a responsive side rail. Revisions preserve the original snapshot; older posts are not backfilled. The heading is the single `blogroll_heading` setting.

Use **Manage subscriptions…** in the Reader to see every feed in one place, choose **Show on blogroll**, or remove a subscription. Removal stops future syncs and clears its ordinary cached entries; Saved and Liked entries remain available locally. Saved and Liked apply to individual Reader posts and do not add a subscription to the blogroll. Blogroll names link to the root website rather than the machine feed URL.

When a thread contains protocol transclusions, its reading window lists those fragments explicitly. Selecting one highlights it in the article and makes Quote insert that fragment's words as an ordinary editable blockquote with a backlink rather than quoting the entire thread.

Reader **Quote** never becomes a protocol transclusion: whole items, source
fragments, and selected passages are all ordinary editable citations headed
**From:** with a linked page title. **Stub** is the strict path. For a genuine
Blyg target its protected opening source block is resolved from the local cache
and published as a bare `blyg-transclusion` with direct origin/version
provenance. See [QUOTING.md](QUOTING.md).

# Earlier reader additions

See [QUOTING.md](QUOTING.md) for the current quotation boundary. The original 0.6.0 implementation report below describes the earlier directive-only behavior and should not be read as current feature documentation.

# Blyg reader — Blynger 0.6.0

Open **Blyg reader → Add Blyg…**, paste a website, Blyg origin, Blyg-aware RSS feed, or item URL, and choose Subscribe. The real subscription list starts empty. Refresh / Sync updates all subscriptions or the selected one. Reading and searching use local copies. Quote post starts a normal saved response draft from the reader, or inserts a quotation into the current editor.

## Implementation and storage

`reader.py` owns private subscription discovery, import/reconciliation, cached reading, managed assets, and retention. It stores `remote-reader/reader.json` and content-addressed media beneath the existing private support-data directory, outside the website. It never stores imported objects among authored item identities. `core.py` exposes local and remote objects through the shared quote selection/resolution path. No dependency was added.

Connection remains the existing website/SSH publishing configuration; it did not represent subscriptions and has not been repurposed. Subscriptions are keyed by normalized fetched Blyg origin. Cached items are keyed by origin plus stable item ID and retain the original document, kind, version, creation/update dates, author, provenance, immutable `first_downloaded_at`, observation timestamp, asset map, and last-sync diagnostics. Opaque author data and unknown document fields are preserved. Remote HTML is sanitized for display in a restricted iframe, with media served only from the local cache.

Discovery has a six-request budget, follows at most five redirects per request, supports rel=blyg and RSS manifest discovery, and tries conventional Blyg locations. Public HTTP(S) URLs only; no credentials or local/private network addresses. The fetched manifest URL determines identity, not its self-asserted site field. Full item documents are authoritative. RSS supplies signals and the archive index provides complete reconciliation; conditional feed/index requests avoid unnecessary downloads. Item documents are checked even when the index is unchanged so same-version edits can be detected.

Refresh deduplicates origin/ID, advances versions monotonically, warns on hash mismatches and same-version edits, and retains cached content on network failure. Withdrawals remove current readable copies while preserving watermarks. Missing archive indexes can use the feed window with a visible warning. Sorting clamps future timestamps to local observation time. Filtering by subscription and searching text/author do not require a network connection.

## Quotations and protocol scope

The published specification at https://blygger.org/spec/0.2/ supplies the base reader and publication rules. The standalone specification index still lists 0.2. The official repository's locked 0.3 plan and implemented server, and the independent desktop client, demonstrate cross-origin and thread quotation:

- https://github.com/blygger/blygger-spec/blob/main/docs/v0.3-plan.md
- https://github.com/blygger/blygger-spec/blob/main/worker/src/transclusion.ts
- https://github.com/aneeshsathe/blygger-desktop — inspected commit `6151e4dbccc7d72c20d2511860088c1b29c82acf`, including transclusion rendering, model, resolver, and reader code.

Blynger now labels newly generated output 0.3 because it supports that demonstrated quotation extension. This is not a claim that the entire planned 0.3 feature set is implemented. It does not change existing published documents merely by opening the app.

Quote selection includes published local fragments and threads, and cached remote fragments and threads. The existing `![[id]]` directive resolves against published local objects first, then an unambiguous cached remote object. Remote references serialize `{id, version, origin}` in `transclusions`; local references omit origin. Rendered wrappers retain `data-blyg-id`, `data-blyg-version`, and, for remote sources, `data-blyg-origin`. Nested rendered content is already baked; only direct references are emitted. Local self/transitive cycles are rejected. A duplicate ID across remote origins is reported rather than silently choosing the wrong author.

Publication uses the latest locally cached version, with no remote request. Already-published unchanged parents keep their baked quotation when another page is published. A new revision resolves the then-current cached source. Media used by a new quotation is copied into immutable publication media, so later reader-cache eviction cannot break published writing. Imported documents never receive their own item endpoint, archive row, or feed entry in the author's Blyg. Remote source attribution links use the shared `/f/{id}/` or `/t/{id}/` permalink forms.

At 0.6.0, response stubs, Webmentions, forks, L0 imports, and automatic sync were deferred. Later sections at the top of this document supersede those limits. Current request limits are documented in **Sync and diagnostics** above; SVG is not cached.

## Retention

At startup and sync, remotely cached items with downloaded meaningful image/video content older than 365 days are evicted. Ordinary refresh preserves the original download date. Text-only items remain indefinitely; tiny icons, avatars, and page chrome do not alone trigger expiration. Declared item media and embedded content media are both considered. Subscriptions and version watermarks survive eviction, which is not a protocol withdrawal. A later explicit resync can download the item anew and starts a fresh cache clock.

Assets are content-addressed and deleted only if no retained item references them. Paths must be validated managed filenames under the remote cache; symlinks and outside paths are refused, and missing files are harmless. Cleanup never touches authored posts, drafts, Openers, local fragments, version archives, or website media. It sends no deletion request anywhere.

## UI changes

- Compact Blyg reader navigation, URL dialog, source selector, search, full-item view, and Quote post actions preserve the existing square/muted desktop styling.
- The main Fragment button calls exactly the existing keyboard divider command; the inline fragment menu remains.
- Dead File/Website/Help/Edit header labels are removed. The functional native Mac Edit menu remains.
- Review immediately shows Preparing…; final publication shows Publishing…. Duplicate clicks are guarded, useful errors remain visible, drafts are preserved, and controls recover on success/failure.

## Files changed

- New: `reader.py`, `test_reader.py`, `test_reader_browser.html`, `serve_reader_tests.py`, `READER.md`.
- Updated: `core.py`, `app.py`, `static/index.html`, `static/app.js`, `static/fragments.js`, `fragments.py`, `static/style.css`, `version.py`, `test_metadata.py`, `test_openers.py`, `OPENERS.md`, `README.txt`, `CHANGELOG.md`.
- Existing authored page contents and deployment configuration were not changed by this task.

## Verification — September 26, 2026

Python regression suite: 78 tests passed, including 37 reader/quote/retention checks. Coverage includes discovery (site, RSS, item, human permalink), protocol rejection, zero/multiple subscriptions, stable identity, persistence, updates, offline reading/quoting, failed sync, malformed feeds, archive fallback, withdrawals, rollback/stealth edits, media-only declaration, expiration boundaries, fresh reimport, shared/missing assets, symlink/outside-path safety, authored-content preservation, local thread quotations and cycle prevention, and durable quoted media after cache eviction.

The browser harness passed all 18 assertions: empty reader, URL dialog, Aneesh import/refresh without duplicates, complete reading, normal quote authoring, local/remote choices, identical button/keyboard fragment metadata, immediate publish feedback/duplicate prevention, failure/draft preservation, and successful retry. Publication ran only against a disposable site and local bare Git remote.

Live inbound interoperability checks imported Aneesh's 10 items and Venkat's 17 items (both fragments and threads). Venkat's origin was https://venkateshrao.com/blyg/; it produced no sync warnings and cached full-item rendering succeeded. These checks used disposable cache data. The test workflow added no real subscriptions and pushed nothing to example.com. The user subsequently added subscriptions in the app.

The installed native app was opened and visibly verified as v0.6.0, with its empty reader and functioning Add Blyg dialog.

Openers RSS follow-up: future published entries are syndicated individually. A durable private baseline suppresses historical entries and the aggregate Openers page while preserving the complete protocol archive. Two additional tests cover publication, reload, upgrade, historical edits, and preservation of endpoints.

Quote/TK follow-up: quoted blocks remain parent-thread transclusions while surrounding designated commentary and generated text remain fragments. Existing saved ranges are normalized without altering text. Edit headline saves a response title independently of its quotation.

The user’s saved 44.html quotation/TK draft was separately prepared successfully in a disposable site, retaining the remote reference plus two commentary fragments. Its original draft content was not altered. The app was reopened to activate the fixes.
