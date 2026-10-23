# Changelog (python package — tags py-vX.Y.Z)

## Unreleased

- Nothing yet.

## py-v0.5.0 — 2026-10-23

### Added
- **`genekit.sqlite_snapshot`** — a consistent copy of a live (WAL) SQLite database, trusted only
  after the *copy* passes `PRAGMA integrity_check`. Promoted from the `sqlite-verified-snapshot`
  ledger candidate (4 independent sightings across potd, quicknote, remake and evertold: three
  `VACUUM INTO` implementations and one online-backup variant, each verifying the copy). Five
  public symbols:
  - `verified_snapshot(source, destination, *, method="vacuum", check_foreign_keys=False,
    keep_failed=False, mkdir=False) -> Path` — opens the source read-only, reserves `destination`
    exclusively (never overwrites), copies with `VACUUM INTO ?` (`method="vacuum"`, compacted) or
    `sqlite3.Connection.backup` (`method="backup"`, page-exact, works before SQLite 3.27), leaves
    the copy in rollback-journal mode as one self-contained file, verifies it, and removes it — or
    with `keep_failed=True` sets it aside as `<name>.failed` — if verification fails.
  - `stamped_snapshot(source, out_dir, *, prefix=None, suffix=None, now=None, method="vacuum",
    check_foreign_keys=False, keep_failed=False) -> Path` — the same, into
    `out_dir/<prefix>-<UTC stamp><suffix>`; the stamp is fixed-width, so names sort
    chronologically.
  - `verify_sqlite(path, *, check_foreign_keys=False) -> None` — `integrity_check` (optionally
    `foreign_key_check`) on a read-only open; raises on anything but `ok`.
  - `SqliteVerificationError(RuntimeError)` — carries `.path`, `.detail` and `.kept`.
  - `STAMP_FORMAT` — the `strptime` format of the stamp.

  Fixes the recurring defects found across the sightings: a missing source silently created by
  `sqlite3.connect` and then "verified" as an empty database; a failed copy left under its good
  name where stamp-based retention would keep it; a destination path hand-quoted into
  `VACUUM INTO`; and a `backup()` that overwrites an existing target and carries the source's WAL
  header, so the copy grows `-wal`/`-shm` sidecars once opened.

### Fixed
- **An invalid `level` no longer leaks an open log file.** `add_file_handler` and
  `add_scoped_file_handler` opened the file before applying the level, so a bad level name raised
  with the stream still open — closed only by GC, and the file stayed locked on Windows until
  then. The level is now resolved before the directory is created or the file opened; a bad name
  leaves nothing behind.
- **`configure_logging` with an invalid `level` no longer half-reconfigures root.**
  `basicConfig(force=True)` closed the existing handlers and attached the new ones before applying
  the level, so a bad name raised with the previous configuration already gone. The level is now
  validated before any handler is built or touched.

Both raise the same `ValueError` as before; only the side effects on failure changed. The test
suite now runs with `filterwarnings = ["error"]`.

## py-v0.4.0 — 2026-09-19

### Added
- **`genekit.atomic_write`** — write a file so a reader never sees a half-written result,
  promoted from the `atomic-write` ledger candidate (4 independent sightings across Starling,
  MeadowLark, evertold, and remove-the-bloat, each hand-rolling write-tmp-then-`os.replace`). Two
  public symbols:
  - `atomic_write_text(path, text, *, encoding="utf-8", mkdir=False, on_error="raise") -> bool` —
    writes `text` to a uniquely named sibling temp file (`tempfile.mkstemp`) and replaces `path`
    in one atomic rename, so a reader always sees the whole previous version or the whole new one,
    never a truncated or half-written file.
  - `atomic_write_bytes(path, data, *, mkdir=False, on_error="raise") -> bool` — the same
    guarantee for a `bytes` payload, with no encoding or newline translation.

  Both fix the recurring defects found across the 4 sightings: a fixed-suffix temp name (e.g.
  `{name}.tmp`) collides under concurrent writers and interleaves payloads, and cleaning up only
  on `OSError` (or not at all) leaks a `.tmp` file on any other failure. The temp name is always
  unique, cleanup runs on *any* exception, and whether a failed write raises or is swallowed is
  the explicit `on_error` parameter rather than a hardcoded choice.

## py-v0.3.1 — 2026-09-17

Supersedes py-v0.3.0, whose tag CI run failed: `format_timestamp` handed `fmt` straight to the
platform `strftime`, whose behaviour differs by OS. Pin this tag, not py-v0.3.0.

### Fixed
- **`format_timestamp` raises `ValueError` for a malformed `fmt` on every OS.** glibc copies an
  unknown directive such as `%Q` (or a trailing lone `%`) into the output verbatim; only the
  Windows UCRT raised, so the documented contract held on Windows alone.
- **Non-ASCII literal text in `fmt` renders on Windows under Python 3.10 and 3.11.** Those
  interpreters encode the whole format with the locale codec before calling the C runtime, so any
  character outside e.g. cp1252 (`年`, `→`) raised `UnicodeEncodeError`. Literal text is now
  copied through without reaching C.

### Changed
- `fmt` accepts exactly the directives that render identically on glibc and the Windows UCRT: the
  C89/C99 set plus Python's `%f`, `%z` and `%Z`. Platform-only extensions — glibc's `%-d`, `%P`,
  `%k`, `%s`, Windows' `%#d`, and 3.12's `%:z` — now raise everywhere instead of working on one OS
  and breaking on another.

## py-v0.3.0 — 2026-09-17

### Added
- **`genekit.tz`** — timezone-aware conversion and display, promoted from the `tz-helpers` ledger
  candidate (3 sightings across 3 repos). Four public symbols:
  - `local_tz()` — the system local zone as a real `tzinfo`, never `None`, for the cases where a
    zone has to be *passed* somewhere rather than inferred. Documents loudly that it is a
    fixed-offset snapshot, not a DST-aware zone.
  - `resolve_tz(name, *, fallback=None, strict=False)` — an IANA name, an existing `tzinfo`, or
    blank, to a `tzinfo`. A zone name is user input, so an unresolvable one warns and falls back
    rather than crashing; `strict=True` opts into raising, normalised to `ZoneInfoNotFoundError`.
  - `to_tz(value, tz=None, *, assume=timezone.utc)` — conversion with an explicit decision about
    naive input. The stdlib treats naive as *system local*; the common real source of naive
    datetimes is naive-UTC storage, so the interpretation is a parameter instead of a host detail.
  - `format_timestamp(value, tz=None, *, fmt=DEFAULT_FORMAT, assume=timezone.utc, default="")` —
    epoch, datetime or `None` to a display string, always via an explicit zone conversion. A
    missing or unrepresentable instant renders as `default`; a wrong *type* still raises.
  - `DEFAULT_FORMAT` — `"%Y-%m-%d %H:%M:%S"`, matching `genekit.logging.VERBOSE_DATEFMT` so a log
    line and a rendered field do not disagree.

  The recurring defect the module exists to prevent, seen across the sightings: code correct about
  the *instant* but wrong about the *calendar day* shown to a person, because the conversion to a
  local zone was skipped or frozen at the wrong moment.
- **`genekit[tzdata]` extra.** CPython ships no IANA tz database on Windows; without one *every*
  `zoneinfo` lookup fails, including `"UTC"`. The extra supplies one. Without it `resolve_tz`
  warns and degrades to the system local zone — the same graceful-fallback shape as `genekit[rich]`.
  `tzdata` is also a dev dependency so the real-IANA tests run everywhere instead of skipping on
  Windows; the database-absent path is covered by monkeypatch.

### Notes
- `requires-python` is unchanged at `>=3.10`: the module uses `timezone.utc`, not the 3.11+
  `datetime.UTC` alias.

## py-v0.2.2 — 2026-09-03

Re-tagged from py-v0.2.1: that tag was cut before the version-bump commit merged, so it
pointed at a tree still declaring `0.2.0` and failed the tag-matches-version CI check.
Tag protection on this repo forbids retargeting an existing tag, so the release moved to
the next version instead. No package changes beyond the version bump.

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
