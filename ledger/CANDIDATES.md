# Promotion Ledger

One `##` section per capability. Statuses: `candidate` (<3 sightings) → `ripe` (3+ sightings,
awaiting /genekit promote) → `promoted` (module + first tag) or `rejected` (with reason).
Agents append sightings during normal app work; only /genekit promote changes status to promoted.

```markdown
## <slug> — <one-line capability description>
- status: candidate | ripe | promoted (genekit.<module>, py-vX.Y.Z) | rejected (<reason>)
- language: python
- sightings:
  - <repo>/<path>:<lines> — <YYYY-MM-DD> — <one-line note>
- notes: <generalization concerns, API sketch, migration leftovers>
```

A sighting is an *independent* solution to the same problem — not a second call site of the same
function. Admission rules and the quality gate live in [../CHARTER.md](../CHARTER.md).

---

## logging-setup — one-call logger configuration (console + file routing) for a CLI app
- status: promoted (genekit.logging, py-v0.1.0)
- language: python
- sightings:
  - remove-the-bloat/src/remove_the_bloat/logging_setup.py — 2026-07-16 — rich console handler plus
    scoped file routing; the most developed of the three.
  - Plex/randomNextEpisode.py:15 — 2026-07-16 — `logging.basicConfig` one-liner.
  - TTS/articleReader.py:48-70,204-210 — 2026-07-16 — dedicated usage logger alongside a
    `basicConfig` call.
- notes: Promoted 2026-07-16 as `genekit.logging` (py-v0.1.0). `season` → `scope` throughout; rich
  sits behind the `genekit[rich]` extra with a silent plain-stream fallback when absent; TTS's
  dedicated usage logger folded in as `dedicated_file_logger`.
  - migrate: remove-the-bloat done — `logging_setup.py` is now a re-export shim keeping the
    `season_*` names, so its call sites were untouched.
  - migrate: Plex done — `randomNextEpisode.py` now calls `configure_logging(console="plain")` in
    `main()`. No shim: the app-local implementation was a single `basicConfig` line, so call sites
    moved to `get_logger` directly. Required bumping Plex from Python 3.10 to 3.13 to satisfy
    genekit's `requires-python >=3.12`. Its old `format="%(message)s - %(ex)s"` + `extra={"ex": e}`
    idiom was dropped (genekit owns the format); exceptions now interpolate into the message. That
    format was latently broken anyway — any record not passing `ex` would raise at format time.
  - migrate: TTS done
  - migrate: MeadowLark done 2026-07-17 — both setup sites now call
    `configure_logging("ERROR", log_file=ERROR_LOG_PATH, console="none")`; no shim, since the app's
    `log_exception`/`get_local_timestamp` helpers are app decisions genekit does not cover, so
    `src/logging_utils.py` stays app code and its ~40 call sites were untouched. Required bumping
    `requires-python` 3.11 → 3.12 to satisfy genekit (same as Plex; interpreter was already 3.14).
    Two behavior changes accepted: genekit owns the format, so records gained `levelname`/`name`
    columns over the old `"%(asctime)s %(message)s"`; and the `log_exception` fallback now writes to
    `ERROR_LOG_PATH` (env-overridable via `$VID_DL_ERROR_LOG`) instead of a hardcoded relative
    `error_log.txt`, matching what the module-level setup already did.
  - migrate: personal-agents (price-tracker) done 2026-07-17 at py-v0.2.0 — adopting its daemon
    logging drove adding optional size-based rotation to `genekit.logging` (`rotate_bytes` /
    `backup_count` on `configure_logging` + `add_file_handler`; both-or-neither, and `backup_count=0`
    with a positive `rotate_bytes` is rejected because the stdlib handler reopens the file in append
    mode on rollover and never bounds it). `run.py` now calls
    `configure_logging(console="plain", rotate_bytes=5 MB, backup_count=3)` and keeps its app-local
    `apscheduler`→WARNING cap. No shim — the `_configure_logging` wrapper stayed but its body is a
    genekit call; the redundant `converter=time.localtime` loop was dropped (stdlib default already
    is localtime). This was a *change* to the existing module, not a new promotion, so the rule of
    three did not restart; the full quality gate (hypothesis property tests, qa-boundary-tester
    review, changelog, annotated tag) still applied.
  - adopt-pending (hand-rolled implementations found 2026-07-17, candidates for `/genekit adopt`):
    - whatToWatch — `logging_config.py` module-level file-only `basicConfig` at import time.
    - d4lf excluded — external fork (d4lfteam/d4lf), not our code.

## tz-helpers — timezone-aware datetime construction and conversion
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/tz.py — 2026-07-16 — battle-tested in
    production use.
  - remove-the-bloat/src/remove_the_bloat/activity.py:31-45 — 2026-07-17 — hand-rolled
    Denver-local timestamp helper (`_DENVER = ZoneInfo(...)` + `_timestamp()` construction/format).
- notes: Extraction would leave a re-export shim in `agents_core` so its existing importers keep
  working. 2 sightings across 2 repos — 1 more needed. MeadowLark's
  `src/logging_utils.py:get_local_timestamp` (one-line `datetime.now().astimezone().strftime`) is
  adjacent but too thin to count as an independent solution; revisit if it grows. Check `zoneinfo`
  coverage first — per the charter, anything stdlib already does well must not be reimplemented.

## url-helpers — URL normalization and comparison
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/urls.py — 2026-07-16 — normalization used
    across agent tooling.
  - personal-agents/apps/price-tracker/src/price_tracker/utils.py:8-18 — 2026-07-17 —
    `site_label` (hostname extraction + www-strip for display) and `href_safe` (bracket
    percent-encoding). Same repo as the first sighting — repo count stays 1 of 2.
- notes: 2 sightings, 1 repo — needs a sighting in a second repo. Surveyed 2026-07-17: MeadowLark
  `src/url_utils.py` (YouTube video/playlist ID extraction) and job-hunter's
  `scraper/url_filter.py` (job-board aggregation-path filtering) are app-specific decisions, not
  generic normalization — not counted. `urllib.parse` does the parsing; the admissible part is
  whatever *decisions* sit on top (which components to strip, how to compare). Name the stdlib gap
  explicitly at promotion time.

## structured-logging — structured/JSON log records with consistent app fields
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/structured_logger.py — 2026-07-16 —
    structured record emission.
  - personal-agents/packages/agents-core/src/agents_core/base_app_log.py — 2026-07-16 — shared app
    log base.
- notes: Both sightings are in one repo, so this is 0 repos short of the 2-repo requirement only if
  a second repo appears — it needs an independent sighting elsewhere, not a third file in
  `agents-core`. **The relationship to `logging-setup` must be resolved at promotion time**: one
  module with a structured mode, or two modules with a shared core. Do not promote either in a way
  that prejudges that decision. `genekit.logging` (py-v0.1.0) shipped without a structured mode and
  without a formatter-injection seam, so the decision remains open — but it is now a *change* to
  `genekit.logging`, not a greenfield choice.

## config-loading — file + env-var config discovery and merge
- status: candidate
- language: python
- sightings:
  - remove-the-bloat — 2026-07-16 — `rtb.toml` plus `$RTB_CONFIG` override pattern.
  - personal-agents/packages/agents-core/src/agents_core/config.py — 2026-07-16 — config loading for
    agent apps.
- notes: 2 sightings across 2 repos — one short of ripe. The app-specific file name and env-var
  prefix must become parameters (`rtb.toml` / `$RTB_CONFIG` are exactly the kind of hardcoding the
  charter forbids). Compare against `tomllib` + `os.environ` before promoting. Partial match
  surveyed 2026-07-17: MeadowLark `src/config.py:_resolve_path` is env-var override with hardcoded
  defaults but no config-file layer — a subset of this capability, not counted as a sighting; if
  promotion scopes the API to make the file layer optional, recount it.
