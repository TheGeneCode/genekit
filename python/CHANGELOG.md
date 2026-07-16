# Changelog (python package — tags py-vX.Y.Z)

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
