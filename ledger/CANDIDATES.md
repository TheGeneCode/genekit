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
- status: ripe
- language: python
- sightings:
  - remove-the-bloat/src/remove_the_bloat/logging_setup.py — 2026-07-16 — rich console handler plus
    scoped file routing; the most developed of the three.
  - Plex/randomNextEpisode.py:15 — 2026-07-16 — `logging.basicConfig` one-liner.
  - TTS/articleReader.py:48-70,204-210 — 2026-07-16 — dedicated usage logger alongside a
    `basicConfig` call.
- notes: Promotion is planned as Phase 3 (`genekit-shared-library-phase-03.md`). rich must sit
  behind the `genekit[rich]` extra with a plain-stream fallback when absent. Migrating Plex and TTS
  onto the promoted module is deliberately deferred — the promotion is not blocked on it, but the
  consumers registry must record whoever actually pins the tag.

## tz-helpers — timezone-aware datetime construction and conversion
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/tz.py — 2026-07-16 — battle-tested in
    production use.
- notes: Extraction would leave a re-export shim in `agents_core` so its existing importers keep
  working. Needs 2 more independent sightings. Check `zoneinfo` coverage first — per the charter,
  anything stdlib already does well must not be reimplemented.

## url-helpers — URL normalization and comparison
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/urls.py — 2026-07-16 — normalization used
    across agent tooling.
- notes: Needs 2 more independent sightings. `urllib.parse` does the parsing; the admissible part is
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
  that prejudges that decision.

## config-loading — file + env-var config discovery and merge
- status: candidate
- language: python
- sightings:
  - remove-the-bloat — 2026-07-16 — `rtb.toml` plus `$RTB_CONFIG` override pattern.
  - personal-agents/packages/agents-core/src/agents_core/config.py — 2026-07-16 — config loading for
    agent apps.
- notes: 2 sightings across 2 repos — one short of ripe. The app-specific file name and env-var
  prefix must become parameters (`rtb.toml` / `$RTB_CONFIG` are exactly the kind of hardcoding the
  charter forbids). Compare against `tomllib` + `os.environ` before promoting.
