# How Blynger Works

**Application release covered:** 0.15.7 · **Published Blyg version:** 0.4

Blynger is a local application for maintaining, writing on, reading from, and publishing a static personal website. It grew out of the practical problem of maintaining [bradydale.com](https://bradydale.com/): a hand-built site with years of HTML, changing designs, ordinary permanent pages, and a blog.

Its aim remains straightforward:

> Make a hand-built static website easier to operate without requiring it to stop being itself.

Blynger provides conveniences familiar from content-management systems—editing, drafts, images, publication history, feeds, subscriptions, and a Reader—but its public site remains ordinary static files. Git remains the publication mechanism. A database-backed public application is not needed to serve the site's writing.

Blynger also implements **Blygger**, a separate publishing protocol defining stable items, fragments, versions, pins, transclusions, responses, forks, and discovery. **Blynger is a particular application; Blygger is the interoperable public model.** This distinction runs throughout the design.

---

# Part I: The Blynger application

## Static files are the primary artifact

Blynger doesn't consider the public website a disposable rendering of a private database. Published HTML is itself a durable artifact.

That produces a distinctive rule: **a change in today's design does not automatically rewrite yesterday's pages**. Historical posts can retain older navigation, presentation, or harmless metadata. New pages use the current design, while necessary privacy, security, protocol, functional, and correctness updates can legitimately affect earlier pages. Sitewide operational changes, including Webmention discovery links, can be deliberate rather than accidental consequences of an ordinary design revision.

The curated blogroll follows this historical principle. The author chooses which Reader subscriptions to show publicly; new Posts can incorporate that day's selection as a static side rail. Changing the subscriptions later need not rewrite the older side rails. A post can preserve evidence of what its author's neighborhood of the web looked like when it appeared.

## Workspaces

The current interface organizes its primary tab row into six workspaces: **Posts, Openers, Pages, Reader, Saved, and Thicket**. Drafts and Images remain accessible from native Mac menus rather than permanently consuming space in the tab row.

### Posts

Posts are standalone articles with titles and their own HTML pages. They participate in the site's numbered sequence—filenames such as `74.html`—and can carry a Blyg identity, version history, fragments, and links from the homepage.

### Openers

Openers are short, usually untitled entries on a continuing aggregate page, `openers.html`. Each can also have its own independent Blyg identity and permalink. An Opener can become a Stub response without ceasing to belong to the aggregate page.

The distinction is editorial: Openers make quick publication less ceremonious, while Posts support more developed pieces.

### Pages and Series

Pages are permanent site pages, often with descriptive names such as `year-2018.html`. They are not part of the numbered Post sequence and do not become Blyg items merely because Blynger edits them.

A **Series** is coordinated in private Blynger state. It joins an ordinary static Series Page with a set of explicitly selected Posts, whose installment details and navigation are prepared for publication. Series membership is not inferred from headline matching. The Series Page is site furniture, not another public Blyg object or ordinary RSS item. Author-written Series prose is preserved while Blynger updates the managed installment list.

### Drafts and Images

The Drafts shelf holds writing saved locally but not staged for publication. **Save** and **Stage** are different actions: Save retains a private draft, including returning staged work to private Drafts; Stage also saves and explicitly marks that work for the next publication.

Images is the site's local asset-management workspace. It can show image dimensions and usage and supports direct uploading without first opening a draft.

### Reader

Reader consumes genuine Blyg material, RSS/Atom feeds, and supported ordinary webpages. Blyg-native items are visibly distinguished from ordinary Web/RSS material, because they make different interoperability and provenance claims.

Remote writing is hostile input, even when it looks like an ordinary article. Blynger sanitizes it using `nh3` and renders it in an opaque sandbox rather than in its privileged application page. A narrow message bridge handles permitted actions such as excerpt selection, genuine Blyg fragment selection, and safe link opening. Imported HTML cannot acquire Blynger's local API token, drive the editor, or publish anything.

Networking validates destinations and pins connections to checked public addresses. Parsing and retrieval are bounded; suspect content hashes, changed bytes at an unchanged Blyg version, or origin mismatches are rejected rather than silently replacing a last-known-good Reader item.

Reader supports background refresh and one-at-a-time expansion of items; the user does not need to leave a list view for each article.

### Saved

Saved retains Reader material and private reactions. Blynger distinguishes Saves, Likes, and additional emoji responses—including Mute, Quieter, and Louder—without publishing them as social signals. Private activity history can also include recorded reactions and published quotations, Stubs, and forks. These records live in the owner's private data, not in the public site or this source repository.

### Thicket

Thicket is the private view of Webmention activity. It displays outgoing notices and verified incoming relationships, with the person and relevant writing both visible. A Webmention does **not** become a public comment simply by being received. Meaningful changes can create new activity; duplicate receipts and routine reverification should not fabricate new interactions.

## Ordinary RSS and Blyg protocol feeds

Blynger deliberately maintains separate feeds:

- `/feed.xml` serves ordinary site subscribers. New Posts and Openers can enter it; routine revisions, reusable fragments, and Pages are not automatically treated as new reading events.
- `/blyg/feed.xml` carries Blyg protocol notifications for interoperable clients. Its current event window and history rules differ from the ordinary feed.

A person subscribing to the blog and a Blyg client synchronizing protocol objects have different needs. They should not be forced into a single feed.

## Publication: Save, Stage, confirm, publish

An ordinary publication is an explicit operation, but **a detailed changed-file review is optional**, not mandatory.

- **Save** stores private writing.
- **Stage** includes selected writing in the next publication.
- An ordinary click on **PUBLISH…** opens a compact confirmation, then runs preparation, validation, hosted-version checks, commit creation, and sending in the background.
- **Right-click PUBLISH…** to take the more deliberate inspection path: calculate and display the complete changed-file list and hosted comparisons before approval.

Both publishing paths use the same underlying staging and safety controls. Generated homepage, feed, Blyg, and Series changes can follow from approved staged writing; unrelated unstaged drafts cannot.

Git is the publication boundary. Blynger records the exact commit it intends to push, checks the hosted branch, refuses stale-file overwrites, and supports recovery when a push fails or its outcome is uncertain. It does not derive the final published state from whatever happens to be in the editor after publication begins.

Preparation and network sending run without monopolizing the interface. A publication in flight prevents conflicting review or preparation jobs, but the author can continue writing; subsequent work is neither silently included nor discarded. The shared background start-and-poll mechanism also recovers from dropped browser requests instead of automatically mistaking them for a failed publication.

Recovery tools distinguish private saved work, prepared work, uncertain hosted state, and finished publication. Damaged private-state files are preserved or isolated rather than replaced casually.

## Webmentions: a narrow dynamic edge around a static website

Blynger can notify other Blyg sites when a successfully hosted publication contains an eligible relationship. The event comes from the **exact hosted Git commit**, not from a draft or the later working tree. The outbound queue is durable and asynchronous; an unavailable remote endpoint does not turn successful publication into failure.

Inbound receiving is deliberately more cautious. A configured public Python CGI endpoint accepts a bounded claim and queues it without fetching the remote source during the HTTP request. An owner-side worker verifies the claimed relationship against the live source and an exact target registry; small validated results are exported from protected storage and pulled into the local Mac application over SSH.

Its core boundaries are:

1. A submission is a claim, not proof of a relationship.
2. Network fetching is bounded and constrained against private-network access and unsafe redirects.
3. Remote metadata cannot become commands, local paths, authoring material, or executable Thicket markup.
4. Receiving cannot create drafts, subscriptions, or publications.
5. Intake, verifier, synchronization, and endpoint advertisement can be disabled without disabling the static site or its Git publication.

Blyg 0.4 includes structured `links[]` notices, distinct from stronger response relationships. Blynger does not invent these by inspecting arbitrary article HTML. The same incoming surface must support duplicates, updates, withdrawals, and temporary failures without silently destroying valid previous observations.

The NearlyFreeSpeech reference deployment is a specific operational implementation, not a general hosting recipe. See `deployment/nfs/`, `docs/WEBMENTIONS_RECEIVER_CONTRACT.md`, `docs/WEBMENTIONS_SECURITY_GATE.md`, `docs/WEBMENTIONS_SECURITY_REVIEW.md`, and `docs/WEBMENTIONS_AGENT_GUIDE.md`. Host filesystem privileges and scheduled verification require separate review on every installation.

## Modules and implementation boundaries

Blynger remains one local application, but responsibility is separated across local routing, site publication, Reader state, Reader networking, metadata, fragment handling, generated-page presentation, Webmentions, browser UI, and the native Mac wrapper. `DEVELOPMENT.md` is the current source-level map; this document explains the architecture and its reasons rather than committing to one internal module layout forever.

---

# Part II: Blynger as a Blygger client

## The protocol is not the application

Blygger defines interoperable public objects and their relationships. It does not prescribe Blynger's editor, private data structures, Mac wrapper, or static-site deployment. Other clients can choose different designs while publishing compatible items.

Blynger currently publishes **Blyg 0.4**. The normative source is the [living Blygger specification](https://blygger.org/spec/0.4/), not this document.

## Items, threads, and fragments

Blyg items have stable identities. Blynger can represent Posts and Openers as Blyg threads or fragments, and individual parts of a larger Post can receive durable reusable identities.

In fragment-aware writing, H2 headings and explicit controls create boundaries. The editor attaches private durable markers to authored HTML blocks and maintains compatibility state for older drafts. Those marks are an authoring implementation detail; they do not leak into canonical Blyg items.

## Quotes, transclusions, and Stubs

An ordinary quotation says, in effect, *these are someone else's words*. A Blyg **transclusion** makes a stronger claim: *these are the words of a particular Blyg item/version*.

That difference determines Blynger's interface:

- **Quote** produces an editable quotation with attribution; it does not claim protocol transclusion.
- **Transclude** imports an identified Blyg item/version as a protected source block without necessarily creating a response relationship.
- **Respond / Stub** establishes `stub_of` and may display the exact referenced version as a protected transclusion.

A protected transclusion may be removed whole, but its words should not be silently edited while retaining false provenance. Removing a transclusion does not by itself erase a separately recorded Stub relationship.

A response to a normal webpage can record a URL and an editable quotation without inventing a Blyg identity or version that the ordinary page does not have.

## Forks

A Blyg Fork starts from a pinned version, becomes independently editable writing, and retains `forked_from` lineage. Blynger sanitizes any imported source representation before opening the editable draft. Forked writing is distinct from a protected exact-source transclusion.

## Versions, pins, and withdrawals

Revision advances the version of a stable item. **Pinning** promises the continued public availability of an exact version and is a deliberate publishing decision, not a background convenience. Blynger's defaults can differ between new Openers and Posts; the public meaning of a pin comes from Blygger, not from the UI choice.

Withdrawal does not mean pretending a previously published identity never existed. Blynger supports local deletion/restoration while representing public withdrawal through the protocol and retaining material that must remain available because it was pinned.

## Discovery and identity

Blyg manifests, public pages, item documents, and protocol feeds provide discovery and version information for other clients. The public Blyg objects are not the same as Blynger's private authoring files.

Link and Webmention semantics are version-sensitive. A `links[]` notice in Blyg 0.4 is not interchangeable with a `stub_of` response, a transclusion, or a fork. The receiver's verification work respects these distinctions rather than reducing the network to arbitrary hyperlinks.

## AI-generated passages and disclosure

Blynger can generate or structurally import model-written passages while retaining the author's ordinary writing as the durable draft. Its TK workflow reconstructs visible context for a fresh generation rather than relying on a hidden long-lived chat. ChatGPT dialogue import can preserve actual speaker turns; the author checks their attribution.

Generated passages carry disclosures using supported `blyg-tk-gen` conventions. Model identities and dates are self-reported metadata, not independently verified provenance. When the model is unknown, Blynger should say *not stated*, not guess. Blynger credits reference work adapted from the independently developed Blygger Studio client.

## Where Blynger has opinions

The distinction is visible in several recurring choices:

| Blygger establishes | Blynger chooses |
| --- | --- |
| Transclusions identify exact source material | Show protected source blocks in the editor |
| Stubs declare response relationships | Let authors make them full Posts or Quick Openers |
| Fragments have persistent identities | Create boundaries through H2s and ordinary editing, with private identity safeguards |
| Pins preserve exact versions | Make the decision visible during publication |
| Independent clients exchange Blyg objects | Read Blyg alongside ordinary RSS/Web material without hiding the distinction |
| Webmentions communicate relationships | Verify remotely, store private activity, never turn claims into public comments |

The goal is not for Blygger Studio, Blynger, Burrow, or future clients to share internal architectures. It is for them to understand each other's conforming published objects without private implementation-specific knowledge.

---

# What Blynger is not yet

Blynger is pre-1.0 and Mac-oriented. It does not yet provide a polished, general-purpose first-run installer for arbitrary static sites. Some assumptions come from the particular website it was originally created to manage. Its private records and internal APIs should not be considered stable interfaces for third-party integrations.

This is compatible with publishing conforming Blyg 0.4 objects: the application may continue evolving while the public protocol imposes a shared external contract.

The longer-term challenge is not to turn every website into a Blynger website. It is to make more personal websites manageable while preserving the peculiarities that make them personal.

> Make a hand-built static website easier to operate without requiring it to stop being itself.

---

## About this document

This is descriptive project documentation, not the normative definition of Blygger. It describes the application and architecture reflected in Blynger's public repository through release **0.15.7**. Check [`version.py`](version.py), [CHANGELOG.md](CHANGELOG.md), and the current [Blygger specification](https://blygger.org/spec/0.4/) for subsequent changes and protocol requirements.
