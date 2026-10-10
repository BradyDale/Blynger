# How Blynger Works

Blynger is a local application for writing, maintaining, reading from, and publishing a static personal website.

It grew out of the practical problem of maintaining [example.com](https://example.com/): a hand-built static site that had accumulated years of HTML, changing designs, peculiar conventions, and ordinary website pages alongside a blog.

The goal is to make a hand-built static website easier to operate **without requiring it to stop being itself**.

Blynger adds many conveniences normally associated with a CMS—drafts, editing, metadata, image management, feeds, publication review, version history, subscriptions and a Reader—but the published website remains a collection of ordinary static files. Git remains the publication mechanism. There is no database-backed public application that must remain running for the website to work.

Blynger also implements the **Blygger protocol**. That gives selected writing on an otherwise ordinary static website interoperable identities, versions, fragments, threads, transclusions, responses, forks, pins and provenance.

Those are two different layers of the application:

- **Blynger** is the static-site manager, editor, Reader and publication system.
- **Blygger** is the protocol Blynger implements when published material participates in the Blyg network.

This document tries to keep that distinction explicit.

---

# Part I: Blynger

## The static website is the primary artifact

Blynger does not treat the website as a disposable rendering of some authoritative database.

The HTML files are themselves durable published artifacts.

That leads to one of Blynger's more opinionated rules:

**Changing the current design of the site does not normally rewrite its past.**

If a post was published with an older navigation bar, an older layout or older harmless metadata, it can remain that way. A newer post can reflect the site's newer design.

Blynger applies current presentation to newly generated material and to pages the author deliberately edits. Necessary privacy, security, compatibility or correctness repairs can also change older output, but ordinary site evolution does not automatically propagate backward through the archive. This behavior is part of Blynger's forward-only static-history rule.

This is partly conservative engineering: rewriting hundreds of files merely because a template changed creates unnecessary risk.

But it is also a publishing philosophy.

A static website can preserve some evidence of its own history.

### The blogroll is historical too

Blynger's blogroll follows an even more explicit version of this rule.

The author chooses which Reader subscriptions appear publicly. When a new Post is published, that current curated blogroll is frozen into the Post as a static side rail.

Changing the subscription list later changes future Posts. It does not rewrite the blogroll shown beside older ones.

Thus an old Post can show, literally, what its author's little neighborhood of the web looked like when it was published.

Blynger could eventually offer an explicit command for people who prefer the opposite philosophy—apply the current design or site furniture to the whole archive—but that should be an intentional bulk operation rather than an incidental consequence of publishing something new.

## The six workspaces

Blynger's interface currently has six primary workspaces.

### Posts

Posts are standalone articles.

They have their own HTML pages, headlines, publication history and normal place in the site's Post sequence. The application currently reserves bare numbered filenames such as `74.html` for Posts.

Posts have the fullest authoring feature set.

### Openers

Openers are shorter pieces of writing that live together on a continuing aggregate page.

They do not need headlines and are intended to make small-scale publishing feel less ceremonious than creating a full Post.

Although readers can encounter them together on `openers.html`, individual Openers can also participate independently in Blygger. That distinction matters later.

### Pages

Pages are ordinary permanent website pages.

They use descriptive names such as `year-2018.html` and do not participate in numbered Post allocation. They do not become Blyg objects merely because Blynger can edit them.

This is an important architectural boundary: **Blynger manages a website, not merely a stream of Blyg posts.**

### Images

Images is the site's asset workspace.

It shows the site's images, their dimensions and which HTML pages currently use them. Images can also be uploaded directly into the library without first opening a draft.

### Reader

Reader consumes material from elsewhere on the web.

It understands genuine Blyg sources, ordinary RSS/Atom feeds and ordinary webpages.

Those sources are deliberately not presented as though they were equivalent. Current Blynger gives Blyg-native and ordinary Web/RSS material distinct Reader treatments and explicit source badges.

Reader content is also a separate trust domain. Remote markup is sanitized with `nh3` and displayed in an opaque sandboxed frame, never in the application document that holds Blynger's private API token and authoring controls. A small per-opening message bridge carries only quotation selections, genuine-fragment choices, and safe link clicks. Imported markup cannot call local APIs, style or replace the application UI, submit forms, or navigate its parent.

Remote fetching pins every connection to the public address Blynger actually
validated, hardens untrusted XML parsing, and places finite limits on feed,
archive, item, and media work. A canonical Blyg item with a false content hash,
wrong origin, or changed bytes under the same version is rejected rather than
quietly entering the cache; Reader displays the rejection while retaining any
last known-good copy.

### Saved

Saved is a local shelf of material retained from Reader.

Saved and Like state belong to the user, locally. Five additional emoji responses—mind blown, eye roll, thumbs down, laugh, and question—are local too. They are not public reactions and are not published as Blyg metadata.

Saved also contains a private activity history. It records changes to Saved,
Like, and emoji responses, plus remote quotations, Stubs, and forks once those
acts have actually been published. The mechanism is part of Blynger; the
owner's log remains exclusively in the configured private-data directory and
does not belong in either the website or the public source repository.

## Reader is part of the writing system

Blynger's Reader is not merely a separate feed reader bolted onto the editor.

It provides the transition from **reading something** to **doing something with it**.

A Reader item can become source material for a quotation, response or fork. Genuine Blyg material retains its protocol identity throughout those operations; ordinary web material retains only the provenance it actually possesses.

Reader is designed to keep substantial state locally. It caches remote content for offline use, performs network synchronization independently of ordinary writing operations, isolates failing subscriptions and keeps Saved material independently of the current subscription list.

That local reading history also creates an interesting future possibility: recommendation or discovery systems can operate on private local evidence of what the user reads, saves, likes, reacts to, quotes, forks or responds to without requiring a central service to own the resulting preference graph.

That is not yet the same thing as Blynger's current Reader, but it is a natural extension of its local-first architecture.

## Ordinary RSS remains ordinary RSS

Blynger generates a normal site feed at:

`/feed.xml`

Its policy is intentionally editorial rather than exhaustive.

A new Post or new Opener can enter the feed. Ordinary revisions, reusable fragments and permanent Pages do not become new RSS entries merely because something changed internally.

This keeps the site's public RSS feed relatively quiet.

Blygger has its own separate protocol notification feed, discussed later.

The existence of two feeds is deliberate. **A human subscribing to the website and a Blyg client synchronizing protocol events are doing different things.**

## Publication is an explicit operation

Saving a draft is not publishing.

Blynger has a **Queue** operation that saves work privately for a later publication and a separate **Review & publish** process for examining what would actually change on the website.

Publication is Git-based.

Blynger attempts to:

- include only files that actually changed;
- show removals explicitly;
- check the hosted branch before publishing;
- refuse to overwrite newer hosted versions of files from a stale local machine;
- record the exact approved commit;
- retry that exact publication safely if the network operation fails.

That caution follows from the earlier principle: the website repository is not a temporary build directory. It is the public site.

## Public files and private state are different things

Blynger keeps substantial information that should never become part of the website.

That can include:

- drafts;
- editing metadata;
- stable fragment mappings;
- Reader caches;
- source snapshots;
- Saved and Liked state;
- publication records;
- configuration;
- provenance information needed while composing;
- temporary editor markers.

The public website contains only what belongs in the published representation.

The website files, Blynger application code and private application data are intended to remain separate.

This division becomes especially important when Blynger implements Blygger, because the application's private machinery for preserving provenance can be much richer than the protocol representation ultimately published.

---

# Part II: Blynger as a Blygger client

Everything in this section needs an important qualification:

**The underlying publishing concepts here are Blygger concepts, not inventions of Blynger.**

Blygger defines an interoperable public model involving items, fragments, threads, versions, pins, transclusions, response relationships, forks, withdrawals, discovery and provenance.

Blynger is one implementation of that model.

Where this section describes an editor button, a protected block, a default setting or a particular workflow, **that is Blynger's interface for expressing the Blygger concept**. Other Blyg clients can implement the same protocol differently.

The objective is not for Blyg clients to share an application architecture. It is for them to understand one another's published output.

## Blyg items: fragments and threads

Blygger gives published pieces of writing stable identities.

Blynger can expose ordinary Posts and Openers through that model.

A larger Post can also contain intentionally reusable **fragments**. Blynger maintains private stable fragment identities while editing and produces the corresponding public Blyg objects when those fragments are published.

In Blynger's editor, H2 headings start fragments on fragment-enabled writing, and explicit fragment controls can add or remove boundaries. Considerable repair machinery exists because browser HTML editing can otherwise disturb the relationship between visible prose and a persistent fragment identity.

That repair machinery is **Blynger**.

The idea that a published fragment can have an independent stable Blyg identity is **Blygger**.

## Quotation and transclusion

A normal quotation means, approximately:

**These are someone else's words.**

A Blyg transclusion says something stronger:

**These displayed words are this particular Blyg item/version.**

Blynger therefore does not treat every blockquote as a transclusion.

Reader **Quote** is always a conventional editable blockquote headed **From:** with a linked page title. It makes no protocol transclusion claim. A genuine whole-item Blyg transclusion is reserved for **Stub**, where it preserves the item's actual identity and the exact source/version incorporated into the published response.

### Blynger's interface opinion

When a genuine Blyg transclusion appears in Blynger's Write mode, the source material is treated as a protected block.

The author can remove the entire block but cannot casually change its words while still claiming that it represents the referenced Blyg version.

Internally Blynger may need additional private source snapshots and editor markers to guarantee this. Those do not belong on the wire. Published Blyg `content_html` contains the protocol transclusion representation rather than Blynger-specific editing machinery.

## Stubs

A Blyg **Stub** represents a response to another object.

That response relationship is not the same thing as quoting the thing being answered.

Blynger consequently preserves two separate facts when responding to a genuine Blyg item:

1. `stub_of` says **this item responds to that Blyg item/version**.
2. A transclusion can say **these displayed source words are that exact Blyg item/version**.

Blynger's current Stub editor begins genuine Blyg responses with the whole source item as a protected transclusion. The entire transclusion can be deleted without deleting the response relationship itself.

A Stub can become either a full Blynger Post or a Quick Opener.

That is a **Blynger interface decision** built around the underlying Blygger response primitive.

### Plain-web responses are different

An ordinary webpage has no Blyg origin, ID or version.

Blynger therefore does not fabricate those things.

A response to ordinary web material can retain a URL and an ordinary editable quotation, but it does not masquerade as a Blyg transclusion.

This distinction is one reason Reader now makes Blyg-native and Web/RSS items visibly different.

## Forks

Blygger also defines lineage for a **Fork**.

A Fork is not merely a quotation. It starts from a particular pinned Blyg version and becomes a new editable work with its own identity while retaining `forked_from` provenance.

Blynger turns the selected source into editable draft material, sanitizes remote markup before it enters that draft and preserves the fork lineage independently of any transclusions that may appear in the source.

Again:

- the lineage model is Blygger;
- the way Blynger presents and sanitizes the editable Fork is Blynger.

## Versions and pins

Blyg objects are versioned.

Blynger exposes that through its own editing and publication interface.

A revision advances the current version while preserving stable identity and, where necessary, the first published permalink.

Blygger also permits a version to be **pinned**: an irrevocable public promise that the exact version will remain available.

Blynger therefore makes pinning an explicit publishing decision rather than silently doing it.

Its current interface defaults differ according to writing type: new Openers default toward pinning, while Posts do not; editable revisions continue to expose the choice for the next version.

Those defaults are Blynger policy.

The meaning and permanence of the resulting pin come from Blygger.

## Withdrawal

Deleting published Blyg writing cannot simply mean pretending its identity never existed.

Blynger therefore maps its recoverable local Delete/Restore workflow to the Blygger withdrawal model when publication occurs. The local writing can remain recoverable while the public Blyg object records that it was withdrawn, and permanent pinned material must remain available.

## Blyg discovery and the Blyg feed

Blynger advertises Blyg-enabled material using the protocol's discovery mechanisms, including `rel="blyg"` links into the site's Blyg surface.

Its Blyg protocol notifications live at:

`/blyg/feed.xml`

That is **not** the website's ordinary RSS feed.

Blynger intentionally keeps `/feed.xml` for ordinary human-facing site subscriptions while the Blyg manifest and protocol feed serve interoperable clients.

Blynger currently preserves the Blyg protocol feed's 50-event notification window while the ordinary site feed follows its own separate policy.

## Generated-text disclosure

Generated-text disclosure is slightly different from the fundamental Blyg primitives above.

Blynger has its own TK authoring feature and robot treatment for AI-generated passages.

Blygger Studio has also established an open convention for identifying generated passages in interoperable material.

As of Blynger 0.9.26, Reader understands that shared `blyg-tk-gen` convention and can display the source item's self-reported model, date and source-count disclosure. Blynger explicitly does **not** claim to independently verify those assertions. It credits and adapts the MIT-licensed Studio implementation rather than pretending the convention originated in Blynger.

This is a useful model for interoperability work:

**share conventions where useful, while allowing different applications to remain different applications.**

---

# Part III: Where Blynger has opinions about Blygger

The distinction can be summarized fairly simply.

### Blygger says:

A transclusion identifies exact source material.

### Blynger says:

Represent that transclusion as a protected editor block so the author cannot accidentally alter the words while retaining false provenance.

---

### Blygger says:

A Stub establishes a response relationship.

### Blynger says:

Let the author turn that response into either a full Post or a Quick Opener, and visually distinguish genuine Blyg responses from plain-web ones.

---

### Blygger says:

Items can contain stable fragments.

### Blynger says:

Let authors create those boundaries through normal document editing, including H2 headings, while maintaining a private identity map resilient to messy browser HTML.

---

### Blygger says:

Versions can be pinned.

### Blynger says:

Surface that irreversible decision prominently during publication, with different sensible defaults for Openers and Posts.

---

### Blygger says:

Independent implementations should be able to discover and consume Blyg objects.

### Blynger says:

Let a Reader consume Blyg **and** the ordinary web, but make the distinction visible rather than flattening everything into a proprietary object model.

---

### Blygger defines the network.

### Blynger embeds participation in that network inside a broader static personal-website workflow.

That is the division of responsibility.

Blynger does not need Studio's internal architecture, and Studio does not need Blynger's. The important test is interoperability: an item published by Blynger should be understandable to Studio, Burrow, another independent client or any future conforming implementation without knowing anything about Blynger's private editor state.

Conversely, Blynger should be able to consume those applications' conforming output without implementation-specific hacks.

The more independent implementations can do that, the more Blygger is functioning as a protocol rather than merely as the storage format of one application.

---

# What Blynger is not yet

Blynger remains pre-1.0.

It is currently Mac-oriented, does not yet provide a polished first-run setup for arbitrary sites, and retains architectural assumptions inherited from the particular static website it was originally built to manage.

Its private data structures should not yet be treated as a stable external API.

None of that prevents its public Blyg output from interoperating with other implementations. In fact, keeping the two contracts separate is important:

**Blynger can continue changing internally while the Blyg objects it publishes obey a shared external protocol.**

The longer-term challenge is therefore not to turn every personal website into a Blynger website.

It is to make Blynger increasingly usable by other people **while preserving the peculiarities that made their personal websites theirs in the first place.**

The goal remains the same:

> **Make a hand-built static website easier to operate without requiring it to stop being itself.**

---

## About this document

This document was written by **ChatGPT (OpenAI)** from Blynger's source documentation, changelog, public repository, and discussions with the project's author. It describes the current architecture rather than serving as the normative definition of the Blygger protocol.

For normative Blygger behavior, refer to the current Blygger specification.
