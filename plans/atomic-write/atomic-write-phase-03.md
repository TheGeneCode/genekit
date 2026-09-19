# Plan: Adopt `genekit.atomic_write` in MeadowLark

## Phase Context
Phase 3 of 5. Phase 1 tagged `genekit.atomic_write` as `py-v0.4.0`. This phase migrates all 3
in-repo copies of the pattern. Sized for one `/implement-plan` session; if interrupted, re-run
`/implement-plan <this file>` — it resumes from its checkpoint. See `strategy-atomic-write.md` in
this folder.

## Context
MeadowLark already pins `genekit` (currently `py-v0.3.1`, for `genekit.logging`/`genekit.tz`) in
`C:\Users\etreq\dev\MeadowLark\pyproject.toml`. Unlike Starling, all 3 MeadowLark sites *log* the
specific exception on failure (`log_exception(exc, ...)`) rather than swallowing silently — so
these sites keep `on_error="raise"` (the library default) and wrap the call in their own
`try/except OSError`, preserving the exact exception object for logging. This is a deliberate
divergence from Starling's `on_error="ignore"`: MeadowLark's call sites need the exception, genekit
doesn't expose one through `"ignore"`.

## Critical Reference Files / Infrastructure to Reuse
| Capability | File or import path |
|---|---|
| New library function | `genekit.atomic_write.atomic_write_text` (`py-v0.4.0`) |
| Call site 1 | `C:\Users\etreq\dev\MeadowLark\src\failed_downloads.py:76-90` (`save_failed_downloads`) |
| Call site 2 | `C:\Users\etreq\dev\MeadowLark\src\pending_queue.py:60-72` (`save_pending_queue`) |
| Call site 3 | `C:\Users\etreq\dev\MeadowLark\src\history_dialog.py:216-228` (`_delete_from_archive`, inline) |
| Consumer pin | `C:\Users\etreq\dev\MeadowLark\pyproject.toml:18` (`dependencies`) and line 82 (`[tool.uv.sources]` tag) |
| Registry to update (in genekit) | `C:\Users\etreq\dev\genekit\python\README.md` |
| Ledger note to flip | `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` sightings |

## Approach
Same recipe as Phase 2, applied to 3 call sites instead of 1. Each site keeps its own function
signature/docstring/logging; only the temp-write-replace body is replaced with one
`atomic_write_text(..., mkdir=<matches current behavior>)` call wrapped in the site's existing
`try/except OSError as exc: log_exception(...)`. No shim module — 3 different files with
app-specific names is exactly the "call-site edits, not a shim" case in the adopt workflow (a shim
is for numerous call sites sharing *one* name; these three don't).

## Implementation Steps
**Model profile:** 0 opus · 2 sonnet · 1 haiku

### Step 1 — Bump the pin
**Model:** sonnet — dependency/lockfile edit plus a sync.

`C:\Users\etreq\dev\MeadowLark\pyproject.toml` line 82: `tag = "py-v0.3.1"` → `tag = "py-v0.4.0"`.
From `C:\Users\etreq\dev\MeadowLark`: `uv sync`.

### Step 2 — Replace all 3 call sites
**Model:** sonnet — 3 well-specified, structurally similar edits in one coherent unit (all 3 are
the same generalization, done together so `ruff check` catches any cross-file inconsistency in one
pass).

**`failed_downloads.py`**, `save_failed_downloads` (lines 76-90). Before:
```python
def save_failed_downloads(path: Path, records: list[FailedRecord]) -> None:
    """Write failed-download records atomically; never raises on write failure."""
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError as exc:
        log_exception(exc, f"save_failed_downloads: could not write {path}")
        tmp_path.unlink(missing_ok=True)
```
After:
```python
def save_failed_downloads(path: Path, records: list[FailedRecord]) -> None:
    """Write failed-download records atomically; never raises on write failure."""
    try:
        atomic_write_text(
            path, json.dumps(records, ensure_ascii=False, indent=1), mkdir=True
        )
    except OSError as exc:
        log_exception(exc, f"save_failed_downloads: could not write {path}")
```
Add `from genekit.atomic_write import atomic_write_text` to imports.

**`pending_queue.py`**, `save_pending_queue` (lines 60-72). Same transformation:
```python
def save_pending_queue(path: Path, records: list[PendingRecord]) -> None:
    """Write pending records atomically; never raises on write failure."""
    try:
        atomic_write_text(
            path, json.dumps(records, ensure_ascii=False, indent=1), mkdir=True
        )
    except OSError as exc:
        log_exception(exc, f"save_pending_queue: could not write {path}")
```
Add the same import.

**`history_dialog.py`**, `_delete_from_archive` (lines 216-228), inline (no dedicated write
function). Before:
```python
        tmp_path = ARCHIVE_PATH.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
            tmp_path.replace(ARCHIVE_PATH)
        except OSError as exc:
            log_exception(exc, "HistoryDialog: write archive")
            QMessageBox.warning(self, "Archive Error", f"Could not update archive:\n{exc}")
            tmp_path.unlink(missing_ok=True)
            return
```
After:
```python
        try:
            atomic_write_text(ARCHIVE_PATH, "".join(new_lines))
        except OSError as exc:
            log_exception(exc, "HistoryDialog: write archive")
            QMessageBox.warning(self, "Archive Error", f"Could not update archive:\n{exc}")
            return
```
No `mkdir=True` here — the original never created the parent, so the file's directory is assumed
to already exist. Add `from genekit.atomic_write import atomic_write_text` to imports.

After all 3 edits: `uv run ruff check --fix .` from `C:\Users\etreq\dev\MeadowLark` (MeadowLark's
`select = ["ALL"]` profile will flag any now-unused import).

### Step 3 — Update genekit's registry and ledger
**Model:** haiku — mechanical, two small text edits in the genekit repo.

1. `C:\Users\etreq\dev\genekit\python\README.md`, Consumers registry table: add
   `| \`atomic_write\` | MeadowLark | py-v0.4.0 |`.
2. `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, flip the `migrate: MeadowLark pending` line
   from Phase 1's Step 6 to:
   `- migrate: MeadowLark done 2026-09-19 — atomic_write_text replaces 3 in-repo call sites
   (failed_downloads/pending_queue/history_dialog); call-site edits, no shim; on_error="raise"
   kept so each site's existing log_exception(exc, ...) still gets the real exception.`
3. From `C:\Users\etreq\dev\genekit\python`: `uv run pytest tests/test_ledger_hygiene.py
   tests/test_public_docs.py -q`.
4. Commit in the genekit repo.

## Tests
| Test name | Setup | Expected |
|---|---|---|
| MeadowLark's existing tests covering `save_failed_downloads`/`save_pending_queue`/history archive delete, if present | run as-is | still green — observable contract (write-or-log-and-continue) unchanged |

No new MeadowLark test needed for the same reason as Phase 2: the failure/cleanup contract is now
covered generically by `genekit.atomic_write`'s own suite (Phase 1), and each call site's
`try/except OSError` wrapper is unchanged in shape, only its body's mechanism moved.

## Verification
From `C:\Users\etreq\dev\MeadowLark`:
```
uv run pytest -q
uv run ruff check
```
From `C:\Users\etreq\dev\genekit\python` (Step 3's commit):
```
uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q
```
