# Notes for future plans

Carried forward from the genekit phase plans (phases 1–3 complete as of 2026-07-16). One bullet per
decision that later work must respect. The authorities remain [CHARTER.md](../CHARTER.md) (what may
enter and the bar) and the `/genekit` skill (how it enters).

## Facts that outlived the phase plans

- **Remote is `origin`**, `https://github.com/TheGeneCode/genekit.git`. Phase 3's own notes claimed
  the remote was named `genekit` — it is not. Read `git remote -v`; do not assume either way.
- **`gh` CLI is unusable here**: its keyring token is for the retired `Geneocide` account and
  `gh auth status` errors. Verify remote tags with `git ls-remote --tags <url>` instead. `Geneocide`
  is dead — never reintroduce that name.
- **`uv lock` does not follow a version bump automatically.** Bumping `pyproject.toml` leaves
  `uv.lock` naming the old version, which then ships under the new tag. The `/genekit` skill's
  promote step 6 now says this; phase 3 hit it.
- **rtb's pytest config already sets `addopts = "-q"`.** Passing `-q` again makes it `-qq`, which
  silently suppresses the pass/fail summary line. Run `uv run pytest -n auto --tb=short` to see
  counts.

## Decisions `genekit.logging` (py-v0.1.0) locked in

- **rtb consumes it through a shim, not call-site edits.** `remove_the_bloat/logging_setup.py`
  re-exports `genekit.logging` with rtb's `season_*` names aliased onto the library's `scope_*`
  names. Its ~30 importers were untouched, and rtb's full suite (3127 passed) is the parity net for
  any future change. The shim also re-exports the private `_ScopeFilter` as `_SeasonFilter` because
  rtb's tests assert on the filter class directly — that alias is deliberate, not an oversight.
- **The `season`/`scope` split is permanent and intentional.** The app keeps saying *season*; the
  library says *scope* because it belongs to every consumer. Do not "harmonize" them.
- **`current_scope_label` must stay one object.** The shim aliases it, so it is the *same*
  `ContextVar` — that identity is what carries the label into `copy_context()` workers. Never
  replace the alias with a wrapper or a second contextvar.
- **rich stays optional and silent.** `console="rich"` falls back to plain when rich is absent, by
  design (charter: importing genekit must never raise for a missing extra). Do not make it warn.
- **Changing logging behaviour now requires a genekit release + a pin bump** (`/genekit bump`).
  Edits to rtb's `logging_setup.py` no longer change behaviour — it has no implementation left.

## Open ledger work

- **Plex and TTS remain pending migrations** for `logging-setup` (recorded in the ledger entry).
  Neither is blocked; TTS's `initialize_usage_logger` maps onto
  `dedicated_file_logger("tts_usage", ..., fmt="%(asctime)s | %(message)s")`, and Plex's one-liner
  onto `configure_logging(console="plain")`.
- **`structured-logging` is still undecided by design.** `genekit.logging` shipped without a
  structured mode and without a formatter-injection seam, so "one module with a structured mode vs.
  two with a shared core" stays open — but it is now a *change to a released module* with a
  consumer, not a greenfield choice. Sequence it accordingly.
- `tz-helpers`, `url-helpers`, `config-loading` are all short of the rule of three. Do not promote
  on prediction; let the third sighting land.
