# the configured Git host inbound Webmention deployment

These are the fixed host entry points rehearsed during Stage 8D. They are not
an activation mechanism by themselves.

- `webmention.cgi` is the public Python CGI wrapper. Keep it absent until the
  independent Stage 9 audit passes and activation is separately approved.
- `install-target-registry` is the fixed SSH command used by Blynger's durable
  exact-commit registry refresh. Install it owner-only at
  `/home/private/blynger-webmentions/bin/install-target-registry`.
- `run-inbound-verifier` is the owner-only scheduled command. Install it at
  `/home/private/blynger-webmentions/run-inbound-verifier`; after Stage 9, the
  NFS control panel may run it every ten minutes with overlap prevented by the
  worker's own nonblocking lock. Successful runs are silent so routine checks
  do not generate scheduled-task email; failures still write to standard error.

Both runtime copies require the complete `webmentions/` package and the
top-level `reader_network.py` module. Hash-check every installed file against
the approved local commit before activation.

The receiver configuration stays in policy `off` while the public wrapper is
absent. `/home/protected` must be owner-owned, web-group writable, and sticky
(`1770`), so the web identity cannot rename or replace owner-owned children.
The target-registry directory is owner-written, group-readable, mode `2750`,
so atomic replacements inherit the web group. The shared inbox is `2770` so
files created by either the web receiver or owner verifier inherit the web
group; its data remains non-executable. Verified data is owner-only `0700`. All owner-executed code and
helpers live below the owner-only `/home/private/blynger-webmentions` tree. No
executable may be stored below the web-writable inbox.
