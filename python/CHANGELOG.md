# Changelog (python package — tags py-vX.Y.Z)

## Unreleased

## py-v0.2.1 — 2026-9-03

### Added
- **MIT license.** `LICENSE` at the repo root (for GitHub detection) and an identical
  `python/LICENSE` at the build root, declared in PEP 639 form — `license = "MIT"` plus
  `license-files = ["LICENSE"]` — so the license text ships inside the wheel at
  `dist-info/licenses/LICENSE`. A root-only LICENSE would not have: hatchling's build root is
  `python/`, and `license-files = ["../LICENSE"]` builds a wheel that `twine check` rejects.
- Package metadata for public consumption: `authors` (name only), and `[project.urls]` with
  Homepage, Repository, Changelog and Charter links.
- `tests/test_packaging_metadata.py` — asserts the license expression, the recorded license file,
  attribution, and that the two LICENSE files stay byte-identical.
- **CI.** `.github/workflows/ci.yml` mechanizes the machine-checkable half of the charter's quality
  gate — `uv run ruff check .` at zero findings, and pytest across Python 3.10/3.12/3.14 in two
  dependency profiles (no extras, and `--extra rich`) across 5 Ubuntu legs, plus two Windows legs
  at the floor and ceiling (7 legs total). A tag-triggered job asserts a pushed `py-vX.Y.Z` tag
  matches `[project] version`.
  Docstring examples, the qa-boundary-tester review and ledger-note judgement stay human.
- Two tests covering the rich console branch that no test reached before: the `RichHandler` path
  (skipped when rich is absent) and the genuinely-absent fallback (skipped when rich is present).
  `test_rich_missing_falls_back_to_plain` fakes the ImportError and so passed in both environments.
- `SECURITY.md` at the repo root, naming GitHub private vulnerability reporting as the only channel,
  and `.github/dependabot.yml` to keep the workflow's SHA-pinned actions current.

### Changed
- **Lowered `requires-python` from `>=3.12` to `>=3.10`.** No library source changed — 3.10 is a
  hard floor set by the PEP 604 `X | None` module-level annotation on
  `current_scope_label: contextvars.ContextVar[str | None]` in `genekit/logging.py`. The test
  suite gained a `tomli` dev-only fallback (`tomli>=2; python_version < '3.11'`) because `tomllib`
  itself is 3.11+ and `tests/test_packaging_metadata.py` needs it below that. The CI matrix moved
  from 8 legs to 7, now exercising both the 3.10 floor and the 3.14 ceiling on Ubuntu and Windows,
  with 3.12 kept as a bare mid-anchor leg.
- `description` no longer ends in the relative path `../CHARTER.md`, which was meaningless once
  embedded in wheel METADATA; the charter is linked from `[project.urls]` instead.
- `README.md` links to `CHARTER.md`, `ledger/CANDIDATES.md` and the repo README are now absolute
  GitHub URLs. This file is embedded as the METADATA `Description`, where relative links resolve
  to nothing.
- `[project.urls]` Changelog and Charter links pointed at `blob/master/`; the default branch is
  `main`, so both 404'd — including from every wheel's METADATA. Fixed, along with the same three
  broken links in `README.md`. `python/tests/test_public_docs.py` now fails on any `/blob/master/`
  URL in a tracked document.
- `README.md` (this file, embedded as the wheel METADATA `Description`) opens with a framing line
  saying genekit is a personal library and that the `py-vX.Y.Z` tags are the only contract, and the
  consumers registry now says in the file what it is for — the five repo names stay, because
  `ledger/CANDIDATES.md` names the same repos with paths and the charter's breaking-change clause
  depends on them.

### Note
- Consumers pinned to `py-v0.1.0` / `py-v0.2.0` are pinned to commits that predate the license.
  They pick it up only on the next tag bump.

## py-v0.2.0 — 2026-07-17

### Added
- `genekit.logging` — optional size-based file rotation. `configure_logging` and `add_file_handler`
  gained keyword-only `rotate_bytes` / `backup_count`: when both are positive the file handler is a
  `logging.handlers.RotatingFileHandler` (rolls over at `rotate_bytes`, keeps `backup_count`
  backups); the defaults (`0`, `0`) preserve the prior unbounded `FileHandler` exactly, so this is a
  backwards-compatible minor release — no consumer action required.
  - Rotation is all-or-nothing: exactly one of `rotate_bytes` / `backup_count` being positive is
    rejected with `ValueError`. `backup_count=0` with a positive `rotate_bytes` cannot bound the
    file (the stdlib handler reopens it in append mode on rollover), so it is refused rather than
    silently growing without limit.
  - Rotation is single-process only; the docstring warns against pointing two processes at one
    rotating file (their rollover renames race — `PermissionError` on Windows).
  - Motivated by adopting the personal-agents price-tracker daemon, whose hand-rolled
    `RotatingFileHandler(maxBytes=5MB, backupCount=3)` had no library home.

## py-v0.1.0 — 2026-07-16

### Added
- `genekit.logging` — promoted from the `logging-setup` ledger candidate (3 sightings across
  remove-the-bloat, Plex and TTS). Public API: `configure_logging`, `add_file_handler`,
  `add_scoped_file_handler`, `scoped_logging`, `dedicated_file_logger`, `get_logger`,
  `current_scope_label`, plus the `VERBOSE_FMT` / `VERBOSE_DATEFMT` format constants.
  - Console records go to **stderr**, leaving stdout clean for machine-readable output.
  - `add_scoped_file_handler` + `scoped_logging` route records to per-scope log files by
    contextvar label, so concurrent units of work never contaminate each other's file. The label
    is carried into workers started from a captured `contextvars.copy_context()`.
  - `dedicated_file_logger` builds a non-propagating named logger for side-channel logs
    (usage/audit trails); re-initializing replaces its handler rather than duplicating it.
  - The rich console requires the **`genekit[rich]` extra**. Without it, `console="rich"` degrades
    silently to `console="plain"` (a stdlib stderr handler) — importing genekit never raises for a
    missing extra.
