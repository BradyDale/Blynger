# Intentional reusable fragments — Blynger 0.5.0

A Post is published as one Blyg **thread**. Its headings and paragraphs remain ordinary parts of that thread unless the author deliberately chooses **Reusable fragment**. A fragment is useful when the same passage should have its own stable identity and be reused in multiple threads. It is not required merely so another author can quote or stub part of a Post; Blyg quotation selectors already support excerpts from threads.

Put the cursor in the desired section and choose **Reusable fragment**, or press **Control + Shift + F**. H2 headings provide natural section boundaries in the editor, but do not themselves create fragments or feed items. Choose **Make ordinary prose** to remove a draft designation. Removing a designation never withdraws an already-published fragment.

Openers remain fragments because each dated Opener is itself the published unit. A stub Opener remains a thread. Posts remain threads even when short. TK-generated prose stays inside its containing thread and does not automatically create fragments before or after itself.

This distinction prevents a single Post from producing a burst of child items in subscribers' feeds. The community has discussed a future `ignyr` changelog directive for backgrounding related items, but Blynger does not emit a proposed directive before it is part of the official protocol.

## Durable model

Fragment-aware article HTML carries stable authoring attributes on top-level blocks: `data-blynger-block` identifies a block, `data-blynger-fragment` identifies blocks inside a designated reusable range, and `data-blynger-break` records an intentional legacy boundary. These markers move with whole HTML blocks and make ordinary edits and reordering more robust.

The private `fragments` object is a cache and stores details that do not belong in public HTML, including Opener and Stub state. The editor's temporary attributes and controls never enter protocol content. Blynger's sanitizer excludes authoring markers from canonical Blyg JSON, Markdown, transclusions, and content hashes. Ambiguous or invalid identities stop publication and offer recovery rather than silently publishing the wrong prose.

`fragment_ids[page][range-key]` reserves identities during publication preparation. Saving a draft creates no public item or history. Only a successful push records publication history. Preserve the private private-data data directory in backups.

## Publication

Preparation resolves only explicitly designated ranges into Blyg fragment documents. The parent Post remains a thread and transcludes those reusable fragments. Fragment identities and versions remain stable across edits. The ordinary human article preserves the normal prose layout and provides a permalink for each designated fragment.

Existing published fragments and their history remain available. This change is prospective: merely opening an older Post does not withdraw or rewrite its published children. An unpublished draft can safely have its designations cleared before its first publication.

Openers continue to publish as individual feed entries. Ordinary Post headings, TK passages, and quoted selections do not produce child feed entries.

## Recovery

If a draft's marker map is damaged, Blynger offers **Rebuild fragment markers and save draft** and, as a last resort, **Remove all fragments and save draft**. Both retain authored prose and formatting. The removal option clears reusable boundaries from the current draft without deleting previously published fragment history.

## Interoperability

The publication contract follows [Blyg 0.2](https://blygger.org/spec/0.2/), especially its fragment, thread, transclusion, and quotation rules. The distinction between reusable fragments and quotable selections follows guidance from Blyg creator Venkatesh Rao. Blygger Studio and Burrow informed the interoperability review; their client-specific owner APIs and authoring policies are not public protocol requirements.
