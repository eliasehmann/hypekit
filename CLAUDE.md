# hypekit: standalone Hype data toolkit (core library + CLI, later HTTP API + app)

Repo `<workspace>\hypekit` (6th nested repo, workspace = `Documents\hype-installer`). Plan + status: README.md table.

## Rules
- **Core = standard library only, read-only, cross-platform** (Windows/macOS/Linux). No Windows-only calls without a
  fallback; case-insensitive file lookup via `game.ci_path`.
- Records are JSON-ready dicts with stable ids; change their shape only together with `schema.py` VERSION.
- Decoders were ported from `modding/tools` (sound/, text/lngdump, cnt_tool read side, cheats/sna). The originals
  stay; fix bugs in both until modding/tools becomes thin wrappers. Texture *writing* stays in cnt_tool (Pillow).
- Never bundle game files. The app reads the user's install. vendor/ (vgmstream binaries) is not committed.
- Dev: run with `python -s -m hypekit ...` from this folder (`-I` drops the cwd). The cache goes to `<workspace>\work\hypekit`.
  Microsoft Store Python virtualizes AppData writes, so vgmstream can't see them. That's why work/ is used in dev.
- Token budget: CLI output is short by default (`--limit 50`); use `--json` + `sql` for exact queries.
- **Don't commit or push without asking.** git: `-c http.sslBackend=schannel`.
