# Plan: Promote `atomic-write` into genekit

## Phase Context
Phase 1 of 5. Establishes `genekit.atomic_write` (module + tests + docs + tag). Phases 2-5 each
migrate one of the 4 sighting repos onto it. Sized for one `/implement-plan` session; if
interrupted, re-run `/implement-plan <this file>` — it resumes from its checkpoint. See
`strategy-atomic-write.md` in this folder for the full picture.

## Context
`ledger/CANDIDATES.md`'s `atomic-write` entry is `ripe`: 4 independent write-tmp-then-`os.replace`
implementations across Starling, MeadowLark (×3 in-repo), evertold, and remove-the-bloat. Per
CHARTER.md, new library code lands only via this promotion, gated by `qa-boundary-tester` review,
0-finding lint, hypothesis property tests, and an annotated tag — never a direct edit.

## Critical Reference Files / Infrastructure to Reuse
| Capability | File or import path |
|---|---|
| Style/structure model for the new module | `C:\Users\etreq\dev\genekit\python\src\genekit\tz.py` |
| Style/structure model for the new test file | `C:\Users\etreq\dev\genekit\python\tests\test_tz.py` |
| Ledger entry to update | `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md` (`## atomic-write`, currently line 188) |
| Module inventory + consumers registry | `C:\Users\etreq\dev\genekit\python\README.md` |
| Version + deps | `C:\Users\etreq\dev\genekit\python\pyproject.toml` (currently `version = "0.3.1"`) |
| Changelog | `C:\Users\etreq\dev\genekit\python\CHANGELOG.md` |
| Widest existing cleanup precedent | `C:\Users\etreq\dev\remove-the-bloat\src\remove_the_bloat\cache.py:42-56` (`_atomic_write_text`, `except BaseException`) |
| Leak this fixes (no cleanup on failure) | `C:\Users\etreq\dev\evertold\backend\src\evertold\datadir_file.py:60-80` |

## Approach
Study of all 4 sightings (done during planning; behavioral matrix below) shows one clean
generalization: always-unique temp name via `tempfile.mkstemp` (fixes MeadowLark's fixed-suffix
race), best-effort cleanup on *any* exception (widens Starling/MeadowLark's `except OSError`-only
cleanup and evertold's no-cleanup-at-all to remove-the-bloat's `except BaseException` precedent),
and an explicit `on_error: Literal["raise", "ignore"]` parameter covering both propagate (evertold,
remove-the-bloat) and swallow (Starling, MeadowLark) callers. Rejected: a `serialize=` callback
parameter (every sighting does `json.dumps`/plain text itself outside the write — keeping
serialization caller-side avoids the module ever importing `json` and matches the charter's
"parameters over cleverness" bias). Rejected: defaulting `mkdir=True` (2 of 4 sightings rely on a
missing directory being a caller bug, not silently papered over).

**Sighting behavioral matrix** (the parameter space the API design answers):
| Sighting | Temp name | Cleanup scope | On failure | mkdir |
|---|---|---|---|---|
| Starling `update_check.py:150-165` | fixed (`{name}.{pid}.tmp`) | `except OSError` | swallow, no log | yes (inline) |
| MeadowLark `failed_downloads.py:76-90` (+2 more) | fixed (`.tmp` suffix) | `except OSError` | swallow, caller logs | yes (2 of 3) |
| evertold `datadir_file.py:60-80` | unique (`NamedTemporaryFile`) | none | propagate | yes (inline) |
| remove-the-bloat `cache.py:42-56` | unique (`mkstemp`) | `except BaseException` | propagate | no |

## Implementation Steps
**Model profile:** 1 opus · 3 sonnet · 2 haiku

### Step 1 — Author the module
**Model:** opus — cross-cutting API design generalizing 4 independent implementations; a
concurrency/atomicity invariant (silent data loss on a botched generalization is exactly the
charter's "known silent-failure invariant" case).

Create `C:\Users\etreq\dev\genekit\python\src\genekit\atomic_write.py`. Full spec:

```python
"""Write a file so a reader never sees a half-written result.

<Prose docstring, matching tz.py's depth: the decision encoded (temp-then-replace, always
unique temp name, cleanup on any failure, raise-vs-ignore as a parameter, not a hardcoded
choice), the stdlib parts reused (os.replace for the atomic rename, tempfile.mkstemp for the
safe sibling temp), and the policy this module adds that every sighting re-derived by hand.
Explicitly call out: a fixed-suffix temp name collides under concurrent writers and fails on
Windows if a reader holds the old temp open (MeadowLark's 3 sites did this); no cleanup on
failure leaks a .tmp file forever (evertold's site did this). Note: neither function
serializes — callers pass the already-encoded str/bytes.>
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

__all__ = ["atomic_write_bytes", "atomic_write_text"]


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mkdir: bool = False,
    on_error: Literal["raise", "ignore"] = "raise",
) -> bool:
    """<Args: path, text, encoding (default "utf-8"), mkdir (default False, creates
    path.parent with parents=True, exist_ok=True before writing), on_error ("raise"
    propagates OSError after cleanup; "ignore" swallows OSError, returns False, caller
    logs it themselves since this function does not). Returns: True on success, False only
    when on_error="ignore" swallowed a failure. Raises: OSError when on_error="raise".
    Include >= 1 runnable Example: (doctest style, see tz.py) writing to a
    tempfile.TemporaryDirectory() path and reading it back.>
    """
    return _atomic_write(
        path, lambda handle: handle.write(text), mode="w", encoding=encoding,
        mkdir=mkdir, on_error=on_error,
    )


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mkdir: bool = False,
    on_error: Literal["raise", "ignore"] = "raise",
) -> bool:
    """<Same contract as atomic_write_text, for bytes; docstring cross-references it via
    :func:`atomic_write_text` rather than repeating the full policy. >= 1 runnable Example.>
    """
    return _atomic_write(
        path, lambda handle: handle.write(data), mode="wb", encoding=None,
        mkdir=mkdir, on_error=on_error,
    )


def _atomic_write(
    path: Path,
    write: Callable[[Any], None],
    *,
    mode: str,
    encoding: str | None,
    mkdir: bool,
    on_error: Literal["raise", "ignore"],
) -> bool:
    """<Private helper, brief one-line docstring only (not public API, no doctest needed).>"""
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, mode, encoding=encoding) as handle:
            write(handle)
        tmp.replace(path)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        if on_error == "raise":
            raise
        return False
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
```

Fill every `<...>` placeholder with real prose/doctests to the charter bar (Args/Returns/Raises,
>= 1 runnable example per public function, no invented variables). `py.typed` already exists at
`python/src/genekit/py.typed` — nothing to add there.

### Step 2 — Author the tests
**Model:** sonnet — well-specified against the boundary matrix below and the `tz.py`/`test_tz.py`
precedent pattern; no open design questions left after Step 1.

Create `C:\Users\etreq\dev\genekit\python\tests\test_atomic_write.py`, structured like
`test_tz.py` (module docstring opens with a `Boundary Matrix` of tables). Cover:

| Dim | Case | Expected |
|---|---|---|
| A — happy path | `atomic_write_text` to a fresh path | file exists, content exact, returns `True` |
| A | `atomic_write_bytes` to a fresh path | file exists, content exact, returns `True` |
| A | write over an existing file | old content fully replaced, no partial overwrite |
| B — mkdir | `mkdir=False`, missing parent dir | raises `OSError` (`FileNotFoundError`) |
| B | `mkdir=True`, missing nested parent dir | parent created, write succeeds |
| C — on_error=raise (default) | forced failure (e.g. `path` is a directory, or monkeypatch `os.fdopen` to raise `OSError`) | raises `OSError`; no `*.tmp` file left in `path.parent` afterward |
| C | on_error="ignore", same forced failure | returns `False`; no `*.tmp` file left; original file (if any) unchanged |
| D — non-`OSError` exception mid-write (`write` callback raises e.g. `ValueError`) | with `on_error="raise"` and with `on_error="ignore"` | propagates in **both** cases (only `OSError` is ever swallowed); no `*.tmp` file left |
| E — concurrency | N threads calling `atomic_write_text` on the *same path* concurrently with distinct full-length payloads | final file content is exactly one of the written payloads in full, never a byte-level mix; no leftover temp files after all threads finish |
| F — temp uniqueness | 2 concurrent writers on the same path | no `FileExistsError`; `tempfile.mkstemp` handles uniqueness, assert via patched `tempfile.mkstemp` call count or distinct returned names |
| G — unicode/empty | empty string, surrogate-free unicode (`"Zürich/Ünïcode"`), very long string | round-trips exactly |
| H — bytes edge cases | empty bytes, arbitrary binary incl. `b"\x00"` | round-trips exactly |

Hypothesis property tests (pure round-trip logic, required by the charter): `atomic_write_text`
with `st.text()` then `path.read_text()` equals the input exactly; `atomic_write_bytes` with
`st.binary()` then `path.read_bytes()` equals the input exactly. Use `tmp_path` (pytest's built-in
fixture, already used throughout `test_tz.py`'s sibling suite) — no new fixture file needed;
`python/tests/conftest.py` needs no changes.

After writing: `uv run ruff check .` (0 findings) and `uv run ruff format --check .` from
`C:\Users\etreq\dev\genekit\python`, then `uv run pytest -q`.

### Step 3 — qa-boundary-tester review
**Model:** sonnet — delegates to the mandatory review agent; not a design step itself.

Launch the `qa-boundary-tester` agent on `python/src/genekit/atomic_write.py` and
`python/tests/test_atomic_write.py`. QA mode: `unit` (pure module, no external services, but a real
concurrency surface — flag that explicitly in the handoff so it weights thread-safety findings).
Apply every finding or record an explicit rebuttal with a reason; rebuttals go in the Step 6 commit
message, not silently dropped.

### Step 4 — Version, changelog, inventory
**Model:** haiku — mechanical, fully specified, multi-file, no judgment calls.

1. `C:\Users\etreq\dev\genekit\python\pyproject.toml` line 3: `version = "0.3.1"` →
   `version = "0.4.0"` (minor: new public module, purely additive, no breaking change).
2. `C:\Users\etreq\dev\genekit\python\CHANGELOG.md`: add a new `## py-v0.4.0 — 2026-09-19` section
   above `## py-v0.3.1 — 2026-09-17`, under an `### Added` heading, naming `genekit.atomic_write`,
   its two public functions with full signatures, and the recurring defect it prevents (temp-file
   leaks and torn writes from 4 independently hand-rolled implementations) — follow the prose
   density of the existing `py-v0.3.0` entry.
3. `C:\Users\etreq\dev\genekit\python\README.md`: add a row to the **Module inventory** table
   (after the `tz` row): `| \`atomic_write\` | write-then-replace so a reader never sees a
   half-written file; unique temp name always, cleanup on any failure, raise-or-ignore as a
   parameter | py-v0.4.0 |`.
4. From `C:\Users\etreq\dev\genekit\python`: `uv lock` (the version bump does not refresh
   `uv.lock` by itself).

### Step 5 — Commit, tag, push
**Model:** sonnet — touches real git/remote state; not pure mechanical file editing.

1. `git add python/src/genekit/atomic_write.py python/tests/test_atomic_write.py python/pyproject.toml python/CHANGELOG.md python/README.md python/uv.lock`
2. Commit (include any Step 3 rebuttal reasons in the body).
3. Annotated tag: `git tag -a py-v0.4.0 -m "atomic_write: write-then-replace, promoted from ledger"`.
4. `git push --follow-tags origin main` (remote confirmed `origin` via `git remote -v`; branch is
   `main` per this session's git status).
5. Confirm the tag resolved on the remote: `git ls-remote --tags origin py-v0.4.0` (prefer this
   over `gh api` per the genekit skill's note that the keyring token may belong to a retired
   account).

### Step 6 — Ledger update
**Model:** haiku — mechanical status/text edit within the 400-character ledger-hygiene cap.

In `C:\Users\etreq\dev\genekit\ledger\CANDIDATES.md`, `## atomic-write` entry:
- `- status: ripe` → `- status: promoted (genekit.atomic_write, py-v0.4.0)`
- Append 3 migration notes (Starling is handled in Phase 2, running immediately after this one —
  do not write a `migrate:` line for it here; the other 3 are `pending`), each ≤3 lines / 400
  chars, in genekit's vocabulary per `CHARTER.md § Ledger hygiene`:
  - `- migrate: MeadowLark pending — 3 call sites use tempfile.mkstemp cleanup already; needs atomic_write_text under /genekit adopt.`
  - `- migrate: evertold pending — first-time genekit consumer; needs atomic_write_bytes under /genekit adopt.`
  - `- migrate: remove-the-bloat pending — local helper to be deleted in favor of atomic_write_text under /genekit adopt.`

Run `uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q` from
`python/` to confirm the edited ledger and README stay within the hygiene/link-format gates. Commit
this file alone (small, reviewable diff separate from the release commit).

## Tests
| Test name | Setup | Expected |
|---|---|---|
| `test_atomic_write_text_happy_path` | `tmp_path / "f.txt"` | file written, content exact, returns `True` |
| `test_atomic_write_bytes_happy_path` | `tmp_path / "f.bin"` | file written, content exact, returns `True` |
| `test_mkdir_false_missing_parent_raises` | `tmp_path / "missing" / "f.txt"`, `mkdir=False` | raises `OSError` |
| `test_mkdir_true_creates_nested_parent` | `tmp_path / "a" / "b" / "f.txt"`, `mkdir=True` | parent created, write succeeds |
| `test_on_error_ignore_returns_false_no_temp_left` | monkeypatched `os.fdopen` raising `OSError` | returns `False`, no `*.tmp` glob match in `tmp_path` |
| `test_non_oserror_always_propagates` | `write` callback raising `ValueError`, both `on_error` values | raises `ValueError` in both cases, no `*.tmp` left |
| `test_concurrent_writers_no_torn_read` | `threading`, 8 threads, same path, distinct full-length payloads | final content is exactly one full payload |
| `test_hypothesis_text_round_trip` | `st.text()` | `read_text()` equals input |
| `test_hypothesis_bytes_round_trip` | `st.binary()` | `read_bytes()` equals input |

## Verification
From `C:\Users\etreq\dev\genekit\python`:
```
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```
All three must be clean/green before Step 5's commit. After Step 6, additionally:
```
uv run pytest tests/test_ledger_hygiene.py tests/test_public_docs.py -q
```
Manual: `git ls-remote --tags origin py-v0.4.0` returns the tag (Step 5.5) before starting Phase 2.
