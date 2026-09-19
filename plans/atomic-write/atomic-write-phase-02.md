# Plan: Adopt `genekit.atomic_write` in Starling

## Phase Context
Phase 2 of 5. Phase 1 tagged `genekit.atomic_write` as `py-v0.4.0` and pushed it. This phase runs
the `/genekit adopt` recipe against Starling's single sighting site, and — combined with Phase 1 —
satisfies the charter's "migrate at least one consumer" rule for this promotion. Run immediately
after Phase 1. Sized for one `/implement-plan` session; if interrupted, re-run `/implement-plan
<this file>` — it resumes from its checkpoint. See `strategy-atomic-write.md` in this folder.

## Context
Starling already pins `genekit` (currently `py-v0.3.1`, for `genekit.logging`) in
`C:\Users\etreq\dev\Starling\pyproject.toml`. `write_state()` in `update_check.py` truly swallows
write failures (best-effort throttle cache, no logging) — the simplest of the 4 sightings, and the
only one that needs no caller-side try/except after migration.

## Critical Reference Files / Infrastructure to Reuse
| Capability | File or import path |
|---|---|
| New library function | `genekit.atomic_write.atomic_write_text` (`py-v0.4.0`) |
| Call site to replace | `C:\Users\etreq\dev\Starling\src\starling\update_check.py:157` (`write_state`, lines 148-165) |
| Consumer pin | `C:\Users\etreq\dev\Starling\pyproject.toml:44` (`[tool.uv.sources]` block, and the `dependencies` entry at line 44) |
| Registry to update (in genekit, not Starling) | `C:\Users\etreq\dev\genekit\python\README.md` consumers registry table |
| Ledger note to flip | `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` sightings |

## Approach
Follow the `/genekit adopt` recipe: bump the existing pin, replace the write-tmp-replace body with
one `atomic_write_text` call, keep `write_state`'s own signature and docstring (only its body
changes — no shim needed, this is a single, low-traffic call site), then update genekit's registry
and ledger in the same session (committed in the genekit repo, per the adopt workflow's step 4).

## Implementation Steps
**Model profile:** 0 opus · 2 sonnet · 1 haiku

### Step 1 — Bump the pin
**Model:** sonnet — dependency/lockfile edit plus a sync, not pure mechanical text substitution.

In `C:\Users\etreq\dev\Starling\pyproject.toml` line 44, change
`"genekit @ git+https://github.com/TheGeneCode/genekit@py-v0.3.1#subdirectory=python",` to
`@py-v0.4.0`. From `C:\Users\etreq\dev\Starling`: `uv sync`.

### Step 2 — Replace the call site
**Model:** sonnet — well-specified single-site edit, but touches error-handling semantics worth a
careful pass (dropping the manual pid-tmp-name and mkdir logic in favor of the library call).

In `C:\Users\etreq\dev\Starling\src\starling\update_check.py`, function `write_state` (currently
lines 148-165):

Before:
```python
def write_state(path: Path, state: dict[str, str]) -> None:
    """
    Write the state file atomically. Any failure is swallowed.
    ...
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)  # noqa: PTH105
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
```

After:
```python
def write_state(path: Path, state: dict[str, str]) -> None:
    """
    Write the state file atomically. Any failure is swallowed.

    Delegates to ``genekit.atomic_write.atomic_write_text``: a unique-per-call temp file in
    the same directory, replaced atomically, cleaned up and swallowed on any OSError.
    """
    atomic_write_text(path, json.dumps(state), mkdir=True, on_error="ignore")
```

Add `from genekit.atomic_write import atomic_write_text` to the imports. Run
`uv run ruff check --fix .` from `C:\Users\etreq\dev\Starling` afterward — it will flag and can
remove the now-unused `os`/`contextlib` imports **only if** nothing else in the file still uses
them; check first with `grep -n "os\.\|contextlib\." src/starling/update_check.py` before assuming
either import is dead, since both may be used elsewhere in this file.

### Step 3 — Update genekit's registry and ledger
**Model:** haiku — mechanical, two small text edits, committed in a different repo (genekit) than
Steps 1-2.

1. `C:\Users\etreq\dev\genekit\python\README.md`, Consumers registry table: add
   `| \`atomic_write\` | Starling | py-v0.4.0 |`.
2. `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` entry: append
   `- migrate: Starling done 2026-09-19 — atomic_write_text replaces write_state's inline
   temp-write; call-site edit, no shim; on_error="ignore" preserves the original swallow-silently
   behaviour.` (within the 3-line/400-char migration-note cap).
3. From `C:\Users\etreq\dev\genekit\python`: `uv run pytest tests/test_ledger_hygiene.py
   tests/test_public_docs.py -q`.
4. Commit both files together in the genekit repo.

## Tests
| Test name | Setup | Expected |
|---|---|---|
| Starling's existing `update_check` test suite | run as-is, no new test needed — behavior is unchanged (same swallow-on-failure contract) | still green after the call-site edit |

No new Starling test is required: `write_state`'s observable contract (best-effort, silent) is
unchanged, and `genekit.atomic_write`'s own test suite (Phase 1) already covers the swallow/cleanup
behavior generically. If Starling's existing suite has no test exercising `write_state`'s failure
path at all, that is a pre-existing gap outside this phase's scope — do not add one here.

## Verification
From `C:\Users\etreq\dev\Starling`:
```
uv run pytest -q
uv run ruff check
```
From `C:\Users\etreq\dev\genekit\python` (Step 3's commit):
```
uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q
```
