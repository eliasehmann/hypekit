# Changelog

All notable changes to hypekit are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and the project uses [Semantic Versioning](https://semver.org/). Record shapes are versioned separately
(`hypekit.schema.VERSION`).

## [Unreleased]

### Fixed
- Polish release: dialogue text, speaker names and item names are read as Windows-1250. ą ć ę ł ń ż showed as
  `¹ æ ê ³ ñ ¿`, and text with ś or ź was dropped. The code page is detected from the install, shown as `encoding`
  in `hypekit info`, and can be forced with `$HYPEKIT_ENCODING` (for example `cp1250`). Catalogs are rebuilt once.
  (#1)

## [1.0.0] - 2026-11-18

First public release.

### Added
- Core library (standard library only, read-only): sounds with readable names, dialogue lines linked to their voice
  clips, textures, 3D characters with animations (glTF export), and save games.
- SQLite catalog in the per-user cache, rebuilt when the install changes.
- CLI (`hypekit ...`) with `--json`, `sql` and `schema`.
- Local HTTP API (`hypekit serve`) and the app (`hypekit app`): search, filters with facets, stars, ZIP export,
  play queue, texture lightbox, model viewer, save compare.
- Standalone Windows build (`HypeToolkit.exe`).
- MIT licence, CI on Windows/macOS/Linux, tests that run without a game install, contributor docs.

[Unreleased]: https://github.com/eliasehmann/hypekit/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/eliasehmann/hypekit/releases/tag/v1.0.0
