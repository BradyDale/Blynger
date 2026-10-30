# Blynger

**A local-first personal website manager with Blygger interoperability.**

Blynger is a Mac application for writing, maintaining, reading from, and publishing a hand-built static website. The public website remains ordinary HTML and other static files, deployed with Git. Blynger adds a private editor and Reader, Blyg items, fragments, threads, transclusions, Stubs, forks, pins, Webmention sending and receiving, a private Webmention activity view called Thicket, and separate ordinary and Blyg feeds.

Blynger was built to manage [bradydale.com](https://bradydale.com/), a site that is both a blog and a personal website. It is open source but still oriented toward that original installation; using it on another site requires setup and care.

For the design and architecture, see [How Blynger Works](HOW_BLYNGER_WORKS.md). For a code map, start with [DEVELOPMENT.md](DEVELOPMENT.md). Developers building Webmention support for other Blygger clients should also consult [the Webmentions agent guide](docs/WEBMENTIONS_AGENT_GUIDE.md).

## What it does

- **Posts and Openers.** Publish full, titled Posts as numbered HTML pages or shorter, untitled Openers on a continuing page. Both can have independent Blyg identities; either can be a response to another Blyg item.
- **Pages and Series.** Maintain permanent pages outside the blog, and organize related Posts with a static Series page and installment navigation.
- **Private drafting.** **Save** retains writing privately; **Stage** explicitly includes it in the next publication. Publication also generates required dependent files, such as feeds, home-page entries, and Series navigation.
- **Static publication.** Publish through Git, with hosted-version checks, exact-commit recovery, and background preparation and sending. Ordinary **PUBLISH…** offers a compact confirmation. **Right-click PUBLISH…** for the optional detailed changed-file review before approval.
- **Reader and Saved.** Read Blyg, RSS/Atom, and supported ordinary-web material; retain private Saves, Likes, reactions, and activity history. Reader content is treated as untrusted material, isolated from authoring controls.
- **Blygger interoperability.** Publish Blyg **0.4** items with versions, fragments, threads, exact-source transclusions, Stubs, forks, pins, withdrawals, and discovery metadata.
- **Thicket and Webmentions.** Send eligible outbound Webmentions after successful publication. Receive and verify incoming claims on a separately configured host component, synchronize verified records to the Mac, and display incoming and outgoing activity privately in Thicket. Incoming Webmentions do not become public comments.
- **AI authorship disclosures.** Support generated passages and structured ChatGPT-dialogue imports with explicit attribution and model disclosure, without treating remote claims about models as independently verified facts.

The site has two different feeds: `/feed.xml` for ordinary site subscribers and `/blyg/feed.xml` for Blyg protocol activity.

## Current status

**Blynger 0.15.7** is pre-1.0 software and publishes **Blyg 0.4**. Recent releases have included the Webmention system (0.13), the index-card-inspired interface and Reader changes (0.14), and Blyg 0.4 publishing plus reliability and preservation fixes (0.15). Refer to [CHANGELOG.md](CHANGELOG.md) and [`version.py`](version.py) for the exact checked-out version; this summary may lag subsequent development.

The project is not yet a turnkey installer or a general-purpose CMS. It assumes a separately maintained static-site Git repository and requires configuration for the specific site. A public packaged Mac build and guided first-run setup are not currently supplied.

**Before using Blynger on a site:** back up the site and its private state, inspect configuration, and verify publication behavior against a disposable or test site. Hosting inbound Webmentions requires a separate, security-sensitive deployment. Do not assume the included NearlyFreeSpeech deployment scripts work unchanged on another host.

## Requirements and local setup

- macOS
- Python 3 and dependencies from `requirements.txt`
- Git
- An existing static HTML website in its own Git repository

Install Python dependencies, then copy `settings.example.json` to:

```text
~/Library/Application Support/Blynger/settings.json
```

Replace the example values for your site. Keep **application source**, **website repository**, and **private Blynger data** in separate directories. Settings refer to a chosen SSH private-key **path**; Blynger does not need the key's contents stored in its configuration.

Run the local browser-facing application with:

```bash
python3 app.py
```

The macOS native wrapper source is in `native/Main.swift`.

## Publication and security boundaries

- Saved writing is private until deliberately **staged**. An ordinary publication uses a brief confirmation; the more detailed changed-file inspection is available by right-clicking **PUBLISH…**.
- Publication prepares and pushes a recorded Git commit. Interrupted or uncertain pushes can be reconciled against that exact commit, without sweeping later drafts into the publication.
- Reader material and Webmention metadata remain untrusted. Reader's rendered remote content is sandboxed, and received Webmentions must be verified before appearing as activity.
- Incoming claims cannot create drafts, subscriptions, public comments, or publications. The public receiver does not have access to the Mac's authoring state.
- The local app listens on `127.0.0.1` and uses a per-launch request token.
- Private state, credentials, the local `settings.json`, and site-specific content do **not** belong in the Blynger source repository.

For the receiving trust boundary and host-specific deployment, see [receiver contract](docs/WEBMENTIONS_RECEIVER_CONTRACT.md), [security review](docs/WEBMENTIONS_SECURITY_REVIEW.md), and [security gate](docs/WEBMENTIONS_SECURITY_GATE.md).

## Blygger

Blynger is one implementation of the living [Blygger 0.4 specification](https://blygger.org/spec/0.4/) at its supported level. Blygger defines the public objects and interoperation; Blynger makes particular interface and static-publishing choices. Consult `QUOTING.md`, `FRAGMENTS.md`, `OPENERS.md`, and `READER.md` for additional implementation notes.

## Tests

```bash
python3 -m unittest discover -v
```

Additional browser/JavaScript checks may be documented in [DEVELOPMENT.md](DEVELOPMENT.md) and the changelog.

## Credits

Blynger was conceived and directed by Brady Dale. Its code was written with AI coding systems, primarily ChatGPT/Codex, with additional review and fixes from Grok. The independent open-source Blygger Studio project is an important reference implementation; adapted approaches are credited in the changelog and remain subject to their applicable licenses.

## License

MIT. See [LICENSE](LICENSE).
