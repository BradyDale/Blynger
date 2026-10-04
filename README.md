# Blynger

**Blynger is a static personal website manager with Blygger interoperability built in.**

Blynger is a local Mac application for writing, maintaining, reading from, and
publishing a hand-built static website. It preserves ordinary HTML files and Git
publication while adding Blyg 0.3 items, fragments, threads, transclusions,
stubs, forks, pins, a local Reader, and separate ordinary/Blyg RSS feeds.

### History

Blynger started as an app to automate updating a handcoded website built to run on the no-frills webhosting service, NearlyFreeSpeech.net. When Blygger was released, scope expanded to make the site partly static and partly a Blygger compliant blog.
Blynger was originally built to manage bradydale.com, which remains its primary real-world test site. It would be very interesting to see if others find Blynger useful.

## Current status

Blynger is pre-1.0 software. It was built around one established static site and
is being generalized for other installations. Back up a site before trying it,
review every proposed publication, and expect setup work. The application never
needs a private key's contents; settings store only the path to a key chosen by
the operator.

## Requirements

- macOS
- Python 3
- Git
- A static HTML website in its own Git repository

Install the Python dependencies from `requirements.txt`, copy
`settings.example.json` to
`~/Library/Application Support/Blynger/settings.json`, and replace every example
value. The website, private Blynger data, and application source should be three
separate directories.

Run the local browser version with:

```sh
python3 app.py
```

The native wrapper source is in `native/Main.swift`. A packaged public Mac build
and guided first-run setup are not yet provided.

## Safety model

- Drafts, Reader state, settings, IDs, and history stay in the configured private
  data directory.
- Publishing presents an explicit file review before committing or pushing.
- Tests use disposable sites and local bare Git repositories.
- The server binds to `127.0.0.1` and uses a per-launch request token.
- `settings.json`, private data, credentials, and website content do not belong
  in this repository.

## Blygger

Blynger targets the living Blyg 0.3 Level 2 specification. See
<https://blygger.org/spec/0.3/> and the local interoperability notes in
`QUOTING.md`, `FRAGMENTS.md`, `OPENERS.md`, and `READER.md`.

## Tests

```sh
python3 -m unittest discover -v
```

## License

MIT. See `LICENSE`.
