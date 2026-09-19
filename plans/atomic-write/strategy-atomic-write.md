# Strategy: Promote and deploy `atomic-write`

## Overview
Backlog item #13 (`backlog.txt`): `atomic-write` is `ripe` in `ledger/CANDIDATES.md` with 4
independent sightings across 4 repos (Starling, MeadowLark ×3, evertold, remove-the-bloat), each a
write-tmp-then-`os.replace` implementation. This strategy promotes it into `genekit.atomic_write`
under the full CHARTER.md gate, then migrates all 4 sighting repos off their hand-rolled versions.
End state: one audited module in genekit, zero duplicate atomic-write implementations across the
four repos, and the consumers registry naming all four.

Phased by **repo boundary, not size** — each phase after Phase 1 is a separate git repository with
its own commit history, its own `pyproject.toml`/lockfile, and its own test suite, so each is
necessarily its own `/implement-plan` session regardless of line count. Every phase here is far
under the session cap (≤6 steps, 0 `opus` in phases 2-5) — the split is structural, not
size-driven.

CHARTER.md's Hard Rule "at minimum migrate ONE consumer" as part of a promotion is satisfied across
Phase 1 (sets ledger status to `promoted`, records the other 3 as `migrate: pending`) + Phase 2
(Starling, run immediately after) — run Phase 1 and Phase 2 back to back.

## Stack Decisions
| Concern | Choice | Why |
|---|---|---|
| Temp file naming | Always unique (`tempfile.mkstemp`, never a fixed `.tmp` suffix) | Ledger note flags fixed suffixes as a real race: 2 of 4 sightings (MeadowLark ×3) use a fixed suffix, which collides under concurrent writers and fails outright on Windows if a reader still holds the old temp open. This is the one behavior all 4 sightings get generalized to, not just the majority. |
| Cleanup scope | Best-effort temp unlink on **any** exception (`except BaseException`), not just `OSError` | remove-the-bloat's sighting already does this (catches `BaseException` so a `KeyboardInterrupt` mid-write still cleans up); evertold's sighting does *no* cleanup on failure at all — a real leak this promotion fixes. Generalizing to the widest sighting's behavior is strictly safer for all 4. |
| Error policy | `on_error: Literal["raise", "ignore"] = "raise"` | 2 sightings (evertold, remove-the-bloat) propagate; 2 (Starling, MeadowLark ×3) swallow. Both are legitimate caller decisions — see the per-repo call-site mapping in each phase for which mode each site takes and why `"raise"` (not `"ignore"`) is what MeadowLark's 3 sites actually need, despite superficially reading as a "swallow" pattern. |
| Directory creation | `mkdir: bool = False`, opt-in | 2 of 4 sightings mkdir the parent inline, 2 don't (assume it exists). Not defaulting it on preserves the "missing dir is a bug" signal for the sightings that rely on it. |
| Return value | `bool` (`True`/`False` on swallowed failure) | New, not present in any sighting — the current `on_error="ignore"` callers (Starling) have no way to know a write failed; a bare swallow-and-forget is what genekit is meant to replace, not re-encode with no observability at all. |
| Serialization | Caller-side always | Every sighting does `json.dumps`/plain text itself; the module takes `str`/`bytes`, never a serializer. |

## Architecture Overview
```
genekit/python/src/genekit/
  atomic_write.py          # new module: atomic_write_text, atomic_write_bytes
genekit/python/tests/
  test_atomic_write.py     # new: boundary matrix + hypothesis round-trip properties
genekit/python/
  README.md                # + module inventory row, + 4 consumer registry rows (added per-phase)
  CHANGELOG.md              # + py-v0.4.0 section
  pyproject.toml           # version 0.3.1 -> 0.4.0
genekit/ledger/CANDIDATES.md # atomic-write: ripe -> promoted (genekit.atomic_write, py-v0.4.0)

Starling/src/starling/update_check.py        # write_state() call site
MeadowLark/src/failed_downloads.py           # save_failed_downloads() call site
MeadowLark/src/pending_queue.py              # save_pending_queue() call site
MeadowLark/src/history_dialog.py             # _delete_from_archive() call site
evertold/backend/src/evertold/datadir_file.py # DataDirFile.read() call site
remove-the-bloat/src/remove_the_bloat/cache.py # _atomic_write_text() deleted, call sites updated
```

## Infrastructure to Reuse
| Source | What to reuse |
|---|---|
| `genekit/python/src/genekit/tz.py` | Docstring depth/style, `__all__` pattern, module-level constant docs, doctest-style `Example:` blocks — the pattern for the new module. |
| `genekit/python/tests/test_tz.py` | Boundary-matrix-as-a-table-in-the-docstring test file structure. |
| `remove_the_bloat/src/remove_the_bloat/cache.py:_atomic_write_text` | Widest existing cleanup scope (`except BaseException`) — generalized into the module rather than rewritten. |
| `.githooks/pre-commit` (genekit) | Already runs `ruff check` + `ruff format --check`; no new hook needed. |
| `python/tests/test_ledger_hygiene.py`, `test_public_docs.py` | Already gate ledger-note length/content and doc links; run as part of Phase 1's existing full-suite pass, not written new. |

## Phase Breakdown
| Phase | Plan file | Name | Deliverable | Depends on |
|---|---|---|---|---|
| 1 | `atomic-write-phase-01.md` | Promote into genekit | `genekit.atomic_write` tagged `py-v0.4.0` | — |
| 2 | `atomic-write-phase-02.md` | Adopt in Starling | `write_state()` delegates to genekit; registry updated | Phase 1 |
| 3 | `atomic-write-phase-03.md` | Adopt in MeadowLark | 3 call sites delegate to genekit; registry updated | Phase 1 |
| 4 | `atomic-write-phase-04.md` | Adopt in evertold | First-time genekit dependency; `DataDirFile.read()` delegates; registry updated | Phase 1 |
| 5 | `atomic-write-phase-05.md` | Adopt in remove-the-bloat | `_atomic_write_text` deleted, call sites delegate; registry updated | Phase 1 |

Phases 2-5 have no dependency on each other and can run in any order once Phase 1's tag is pushed
(run Phase 2 right after Phase 1 to satisfy the charter's "migrate at least one consumer" rule
promptly, but 3/4/5 can follow in any sequence, including in parallel sessions).

## Deferred / Out of Scope for v1
- **MeadowLark `history_dialog.py`'s archive write** is a 4th call site in a repo already counted
  as one sighting — folded into Phase 3, not a separate phase.
- **A `normalize_version` promotion** (backlog #13's second half, `release-update-check` ledger
  entry) is a separate ledger candidate at 2/3 sightings, not ripe. Out of scope here; revisit once
  a third repo sighting lands.
- **quicknote / personal-agents / Plex** are not sighting repos for this candidate and are not
  touched by this strategy. If they have hand-rolled atomic-write code, that is a future `/genekit
  adopt` pass, not part of this promotion.

## End-to-End Verification
After all 5 phases: in `genekit/ledger/CANDIDATES.md`, `atomic-write` reads
`status: promoted (genekit.atomic_write, py-v0.4.0)` with all 4 sightings' migration notes marked
`done`; `genekit/python/README.md` consumers registry lists `atomic_write` for all 4 repos; each of
the 4 repos has zero remaining hand-rolled write-tmp-then-replace helpers (verify with
`grep -rn "tempfile.mkstemp\|NamedTemporaryFile\|\.tmp\"" <repo>/src` returning nothing atomic-write-shaped) and its own full test suite green on its bumped `genekit` pin.
