# Plan: Adopt `genekit.atomic_write` in evertold

## Phase Context
Phase 4 of 5. Phase 1 tagged `genekit.atomic_write` as `py-v0.4.0`. evertold is **not** a current
genekit consumer (absent from `python/README.md`'s registry) — this phase adds the dependency for
the first time. Sized for one `/implement-plan` session; if interrupted, re-run `/implement-plan
<this file>` — it resumes from its checkpoint. See `strategy-atomic-write.md` in this folder.

## Context
`DataDirFile.read()` in `datadir_file.py` mints a value under a double-checked lock and writes it
with `NamedTemporaryFile` + `Path.replace` — **with no cleanup on failure at all**: an interrupted
write leaks a `.tmp` file in the data directory forever. Migrating to `genekit.atomic_write` is a
strict fix, not just a dedup, because the module cleans up on any exception (Phase 1's design
decision, generalized from remove-the-bloat's `except BaseException` precedent). `requires-python`
is `>=3.13` in `evertold/backend/pyproject.toml`, comfortably above genekit's `>=3.10` floor.

## Critical Reference Files / Infrastructure to Reuse
| Capability | File or import path |
|---|---|
| New library function | `genekit.atomic_write.atomic_write_bytes` (`py-v0.4.0`) |
| Call site | `C:\Users\etreq\dev\evertold\backend\src\evertold\datadir_file.py:60-80` (`DataDirFile.read`) |
| Dependency recipe | `~/.claude/skills/genekit/SKILL.md` "Consumption recipe" — `uv add "genekit @ git+https://github.com/TheGeneCode/genekit#subdirectory=python" --tag py-v0.4.0` from `C:\Users\etreq\dev\evertold\backend` |
| Registry to update (in genekit) | `C:\Users\etreq\dev\genekit\python\README.md` |
| Ledger note to flip | `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` sightings |

## Approach
First-time adoption: add the pinned dependency (not a bump — `genekit` is entirely new to
`evertold/backend/pyproject.toml`'s `dependencies`), then replace the write body. The existing
`self._mint_lock` (a `threading.Lock` guarding the whole mint-and-write critical section) stays
exactly as-is — it is caller-level concurrency control unrelated to the module's own
temp-name-uniqueness guarantee, and both are needed together (the lock prevents two *mints*
racing; the unique temp name is what makes a single mint's write safe against, e.g., a concurrent
reader of a stale file elsewhere).

## Implementation Steps
**Model profile:** 0 opus · 2 sonnet · 1 haiku

### Step 1 — Add the dependency
**Model:** sonnet — first-time dependency addition (not a mechanical pin bump), touches
`pyproject.toml` and the lockfile.

From `C:\Users\etreq\dev\evertold\backend`:
```
uv add "genekit @ git+https://github.com/TheGeneCode/genekit#subdirectory=python" --tag py-v0.4.0
```
Confirm this produces, in `evertold/backend/pyproject.toml`:
```toml
[project]
dependencies = [..., "genekit"]

[tool.uv.sources]
genekit = { git = "https://github.com/TheGeneCode/genekit", subdirectory = "python", tag = "py-v0.4.0" }
```
alongside evertold's existing dependencies (fastapi, uvicorn, sqlalchemy, etc.) — do not remove or
reorder them.

### Step 2 — Replace the call site
**Model:** sonnet — well-specified single-site edit; the surrounding double-checked-lock logic is
untouched, only the write mechanism inside it changes.

In `C:\Users\etreq\dev\evertold\backend\src\evertold\datadir_file.py`, `DataDirFile.read` (lines
60-80). Before (the tail of the method, inside `with self._mint_lock:`):
```python
            minted = mint()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-replace so a crash mid-write cannot leave a half-written value
            # behind. A unique-per-call tmp name (not a fixed `.tmp` suffix) so a concurrent
            # first-caller elsewhere never races this one on the same file: Windows denies
            # replace() over a file another thread still has open, unlike POSIX's
            # unconditionally-atomic rename.
            with NamedTemporaryFile(
                dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False
            ) as f:
                tmp = Path(f.name)
                f.write(minted.encode("utf-8"))
            tmp.replace(path)
            return minted
```
After:
```python
            minted = mint()
            # Delegates to genekit.atomic_write: same write-then-replace, unique-per-call
            # temp name, plus cleanup on failure this hand-rolled version didn't have.
            atomic_write_bytes(path, minted.encode("utf-8"), mkdir=True)
            return minted
```
Update imports: remove `from tempfile import NamedTemporaryFile` (no longer used — confirm with
`grep -n "NamedTemporaryFile" src/evertold/datadir_file.py` that nothing else in the file
references it before deleting the import), add
`from genekit.atomic_write import atomic_write_bytes`. `on_error` stays default `"raise"` —
matches the original's propagate-on-failure behavior exactly (the original never caught anything).

### Step 3 — Update genekit's registry and ledger
**Model:** haiku — mechanical, two small text edits in the genekit repo, one of them a *new*
registry row (evertold's first appearance).

1. `C:\Users\etreq\dev\genekit\python\README.md`, Consumers registry table: add
   `| \`atomic_write\` | evertold | py-v0.4.0 |`.
2. `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, flip the `migrate: evertold pending` line
   from Phase 1's Step 6 to:
   `- migrate: evertold done 2026-09-19 — atomic_write_bytes replaces DataDirFile.read's inline
   NamedTemporaryFile write; call-site edit, no shim; on_error="raise" kept, matching the
   original's propagate-on-failure behaviour, now with cleanup it previously lacked.`
3. From `C:\Users\etreq\dev\genekit\python`: `uv run pytest tests/test_ledger_hygiene.py
   tests/test_public_docs.py -q`.
4. Commit in the genekit repo.

## Tests
| Test name | Setup | Expected |
|---|---|---|
| evertold's existing `DataDirFile` tests (mint-once, concurrent-first-caller) | run as-is | still green — the double-checked-lock contract is unchanged; only the write mechanism inside the lock changed |
| `test_datadir_file_write_failure_cleans_up_temp` (new, if evertold's suite has no equivalent) | force `atomic_write_bytes` to fail (e.g. monkeypatch `path.parent` to a read-only or nonexistent-without-mkdir path) | no leftover `*.tmp` file in `data_dir` afterward — this is the leak fix; worth one targeted regression test since it's new coverage the old code never had |

## Verification
From `C:\Users\etreq\dev\evertold\backend`, follow this repo's own tiering rather than a hand-rolled
invocation: `just check-fast` (lint + unit tests, both stacks, no browser). This is a backend-only
change (no `scripts/`, `ops/`, `docker-compose*`, shared layout, or Tailwind config touched), so
`just test-api-ops` / `just test-matrix-fast` are not required.

From `C:\Users\etreq\dev\genekit\python` (Step 3's commit):
```
uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q
```
