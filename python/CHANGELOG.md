# Changelog (python package — tags py-vX.Y.Z)

## Unreleased

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

### Changed
- `description` no longer ends in the relative path `../CHARTER.md`, which was meaningless once
  embedded in wheel METADATA; the charter is linked from `[project.urls]` instead.
- `README.md` links to `CHARTER.md`, `ledger/CANDIDATES.md` and the repo README are now absolute
  GitHub URLs. This file is embedded as the METADATA `Description`, where relative links resolve
  to nothing.

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
