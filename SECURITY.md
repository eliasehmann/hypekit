# Security

hypekit only reads local game files and serves them on `127.0.0.1`. Still, it parses binary formats and runs a local
HTTP server, so reports are welcome, for example: a crafted game or save file that makes the toolkit write or execute
something, or a way to reach files outside the game and cache folders through the HTTP API.

**Please don't open a public issue for a vulnerability.** Use
[Report a vulnerability](https://github.com/eliasehmann/hypekit/security/advisories/new) (private) instead. You can
expect a first answer within a week.

Only the latest release is supported.
