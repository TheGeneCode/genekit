# Plan: Adopt `genekit.atomic_write` in remove-the-bloat

## Phase Context
Phase 5 of 5, last of the 4 sighting repos. Phase 1 tagged `genekit.atomic_write` as `py-v0.4.0`.
Sized for one `/implement-plan` session; if interrupted, re-run `/implement-plan <this file>` — it
resumes from its checkpoint. See `strategy-atomic-write.md` in this folder.

## Context
remove-the-bloat already pins `genekit[rich]` (currently `py-v0.3.1`, for `genekit.logging`) in
`C:\Users\etreq\dev\remove-the-bloat\pyproject.toml`. Its local `_atomic_write_text` helper in
`cache.py` is the **widest** of the 4 sightings — unique `mkstemp` name, `except BaseException`
cleanup, always re-raises — and is in fact the precedent Phase 1's module generalized its cleanup
scope from. That means this migration is closer to a straight delete-and-delegate than the others:
`on_error="raise"` (the library default) reproduces remove-the-bloat's current behavior exactly,
with no wrapping needed at any call site.

## Critical Reference Files / Infrastructure to Reuse
| Capability | File or import path |
|---|---|
| New library function | `genekit.atomic_write.atomic_write_text` (`py-v0.4.0`) |
| Helper to delete | `C:\Users\etreq\dev\remove-the-bloat\src\remove_the_bloat\cache.py:42-56` (`_atomic_write_text`) |
| Consumer pin | `C:\Users\etreq\dev\remove-the-bloat\pyproject.toml:11` (`dependencies`) and line 55 (`[tool.uv.sources]` tag) |
| Registry to update (in genekit) | `C:\Users\etreq\dev\genekit\python\README.md` |
| Ledger note to flip | `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` sightings |

## Approach
Delete `_atomic_write_text` outright (it becomes dead code the moment its call sites move to the
library function) rather than keeping it as a wrapper — its behavior maps 1:1 onto
`atomic_write_text(path, text, on_error="raise")` (the default, so `on_error` can be omitted
entirely at call sites), so a wrapper would encode zero decision of its own and the adopt
workflow's shim guidance ("a shim is for numerous call sites relying on app-specific names") does
not apply to a single private helper with call sites inside the same module.

## Implementation Steps
**Model profile:** 0 opus · 2 sonnet · 1 haiku

### Step 1 — Bump the pin
**Model:** sonnet — dependency/lockfile edit plus a sync.

`C:\Users\etreq\dev\remove-the-bloat\pyproject.toml` line 55: `tag = "py-v0.3.1"` →
`tag = "py-v0.4.0"`. From `C:\Users\etreq\dev\remove-the-bloat`: `uv sync`.

### Step 2 — Delete the local helper, update call sites
**Model:** sonnet — requires locating every call site of a private helper before deleting it
(mechanical once found, but "find every call site" is not zero-judgment given the file wasn't
fully read during planning).

In `C:\Users\etreq\dev\remove-the-bloat\src\remove_the_bloat\cache.py`:
1. `grep -n "_atomic_write_text(" src/remove_the_bloat/cache.py` to find every call site (the
   helper at lines 42-56 was read during planning; its callers were not enumerated — do that
   here).
2. Delete the `_atomic_write_text` function (lines 42-56).
3. At each call site found in step 1, replace `_atomic_write_text(path, text)` with
   `atomic_write_text(path, text)` (no `on_error=` — the default `"raise"` matches the deleted
   helper's always-re-raise behavior exactly; no `mkdir=` — the deleted helper never created the
   parent directory either).
4. Add `from genekit.atomic_write import atomic_write_text` to imports.
5. Run `uv run ruff check --fix .` from `C:\Users\etreq\dev\remove-the-bloat` — it will flag any of
   `tempfile`, `os`, `contextlib` that are now unused in `cache.py` **only if** nothing else in the
   file still needs them; check with
   `grep -n "tempfile\.\|os\.\|contextlib\." src/remove_the_bloat/cache.py` before assuming any of
   the three imports is dead, since `cache.py` may use them elsewhere (e.g. `hashlib`, `json`,
   general `os` path calls are visible elsewhere in the file's top section read during planning).

### Step 3 — Update genekit's registry and ledger
**Model:** haiku — mechanical, two small text edits in the genekit repo.

1. `C:\Users\etreq\dev\genekit\python\README.md`, Consumers registry table: add
   `| \`atomic_write\` | remove-the-bloat | py-v0.4.0 |`.
2. `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, flip the `migrate: remove-the-bloat pending`
   line from Phase 1's Step 6 to:
   `- migrate: remove-the-bloat done 2026-09-19 — atomic_write_text replaces the deleted local
   _atomic_write_text helper; call-site edits, no shim; on_error="raise" default reproduces the
   deleted helper's always-re-raise behaviour exactly.`
3. From `C:\Users\etreq\dev\genekit\python`: `uv run pytest tests/test_ledger_hygiene.py
   tests/test_public_docs.py -q`.
4. Commit in the genekit repo.

## Tests
| Test name | Setup | Expected |
|---|---|---|
| remove-the-bloat's existing cache tests exercising the probe-cache write path | run as-is | still green — `_atomic_write_text`'s callers see identical behavior through `atomic_write_text` |
| Any existing test that imports `_atomic_write_text` directly (check with `grep -rn "_atomic_write_text" tests/`) | if found, update the import/call to `genekit.atomic_write.atomic_write_text` | still green; this is a rename at the test's import site, not a new test |

No new remove-the-bloat test needed beyond fixing an import if one directly references the deleted
private helper — the generalized cleanup/re-raise contract is covered by `genekit.atomic_write`'s
own suite (Phase 1), which was in fact modeled on this repo's own `except BaseException` precedent.

## Verification
From `C:\Users\etreq\dev\remove-the-bloat`, this repo's suite is ffmpeg-subprocess-bound and
`tmp_path`-isolated — use its full-suite convention:
```
uv run pytest -n auto
uv run ruff check
```
From `C:\Users\etreq\dev\genekit\python` (Step 3's commit):
```
uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q
```
