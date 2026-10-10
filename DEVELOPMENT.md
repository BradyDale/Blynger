# Developing Blynger

Blynger is small enough to understand, and it should stay that way. Optimize
for a future reader who did not participate in the conversation that produced
the code.

## Code map

- `app.py` is the localhost HTTP boundary and native-app entry point.
- `core.py` coordinates drafts, versions, static publication, and Git.
- `page_templates.py` owns small generated-page templates and forward-only
  presentation styles.
- `reader.py` owns private Reader state, feed interpretation, quotations,
  Stubs, forks, and conversation relationships.
- `reader_network.py` is the bounded, DNS-pinned public network transport.
- `conformance.py` validates final public Blyg artifacts independently of the
  editor's intent.
- `fragments.py`, `metadata.py`, `interactions.py`, and
  `generation_disclosure.py` each own the subsystem named by the file.
- `static/app.js` coordinates the browser interface and application state.
- `static/reader-ui.js` owns Reader cards, private-activity rows, timestamps,
  and opened-item presentation. Reader fetching and authoring transitions stay
  in `app.js`; protocol and private-data behavior stay in `reader.py`.

## Readability rules

1. Prefer one statement per line. Do not add new semicolon-packed Python or
   JavaScript.
2. Give a subsystem its own module when it has an independent safety boundary,
   state model, or vocabulary.
3. Keep public-file generation separate from private editor state and network
   fetching.
4. Add a short module docstring explaining ownership and non-responsibilities.
5. Preserve behavior during structural refactors; add features in a separate
   commit whenever practical.
6. Re-export an established public helper when moving it so existing scripts
   and tests do not break merely because the code became better organized.
7. Run the full Python suite, JavaScript syntax check, and editor-safety checks
   before committing.

## Browser formatting

Browser source uses the checked-in `.prettierrc.json`. Format it with the
pinned formatter version before review:

```sh
pnpm dlx prettier@3.6.2 --write 'static/*.{js,css,html}' \
  test_editor_safety.js test_reader_ui.js 'test_*browser.cjs'
```

Formatting must remain a mechanical change. Move code into focused modules in
separate, tested rounds so reviewers can distinguish reorganization from new
behavior.

The remaining large modules should be reduced incrementally, along tested
seams, rather than rewritten wholesale. `core.py` in particular contains the
oldest behavior and protects a hand-built public site; clarity matters, but a
large risky rearrangement would defeat the purpose.
