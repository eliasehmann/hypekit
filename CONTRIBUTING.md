# Contributing

Thanks for your interest in hypekit. Bug reports, fixes and new readers are welcome.

## Ground rules

- **Never add game files.** No sounds, textures, models, text dumps or saves from the game, not in code, tests,
  issues or pull requests. Tests that need real data use the contributor's own install and are skipped without one.
- **The core stays standard library only, read-only and cross-platform.** No Windows-only calls without a fallback;
  look files up with `game.ci_path` (installs differ in letter case).
- **Records are a public interface.** They are JSON-ready dicts with stable ids. If you change their shape, update
  `hypekit/schema.py` and bump its `VERSION`.
- Keep `hypekit/web/` plain HTML/CSS/JS with no build step.

## Setup

```
git clone https://github.com/eliasehmann/hypekit
cd hypekit
python -m hypekit info          # runs straight from the checkout, nothing to install
python -m unittest discover -s tests -v
```

Point the toolkit at your game with `--game DIR` or `$HYPEKIT_GAME` if it isn't found automatically. Use
`$HYPEKIT_CACHE` to keep a development cache apart from your normal one.

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Branch from `main`, keep the change focused, and add a test (`tests/test_offline.py` if it can run without the
   game).
3. Run the tests, add a line to `CHANGELOG.md` under *Unreleased*, and open the pull request.

Code style: follow the file you are in (PEP 8, lines up to 120 characters, short docstrings that say what the data
looks like).

By contributing you agree that your contribution is released under the [MIT License](LICENSE).
