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

> **This file is public. Repos it cites are primarily private. Read this before you append.**
>
> The **coordinates always stay** — `<repo>/<path>:<lines>` and the date are the evidence the rule
> of three runs on. The **note** is what is disciplined: describe the *shape of the solution* in
> words a reader who will never see that repo can use. Name the mechanism, the data structure, the
> stdlib or third-party API being wrapped, the symbol being sighted, and the behavioural variation
> that makes this sighting independent of the others.
>
> A note must not carry: verbatim code (a fence, a snippet, a pasted signature with defaults);
> env-var names, config keys, config filenames, or any secret material; hostnames, URLs, endpoints,
> database or table names, account ids, absolute paths; business logic — thresholds, pricing, vendor
> or site names, customer data; counts of tests, lines, modules, files, importers or call sites in a
> private codebase; an unfixed defect; or a private repo name beyond this entry's own coordinates.
> Write *an env-var override naming the config location*, not the name.
>
> **Sighting notes: 400 characters. Migration and `adopt-pending` notes: three lines, 400
> characters.** Consumer, done-or-pending + date, the genekit symbols now called, shim vs. call-site
> edits, behaviour changes accepted — in genekit's vocabulary. Longer reasoning goes in that
> consumer's own repo.
>
> Before saving, ask: *would this note still be useful to someone who has never seen that repo, and
> does it disclose anything they could not infer from the path?* Full rule:
> [../CHARTER.md § Ledger hygiene](../CHARTER.md#ledger-hygiene).
> `python/tests/test_ledger_hygiene.py` catches the mechanical half only, and passing it is not
> evidence a note is clean.

---

## logging-setup — one-call logger configuration (console + file routing) for a CLI app
- status: promoted (genekit.logging, py-v0.1.0)
- language: python
- sightings:
  - remove-the-bloat/src/remove_the_bloat/logging_setup.py — 2026-07-16 — rich console handler plus
    scoped file routing; the most developed of the three.
  - Plex/randomNextEpisode.py:15 — 2026-07-16 — `logging.basicConfig` one-liner.
  - Starling/articleReader.py:48-70,204-210 — 2026-07-16 — dedicated usage logger alongside a
    `basicConfig` call.
- notes: Promoted 2026-07-16 as `genekit.logging` (py-v0.1.0). The originating app's domain
  vocabulary was stripped for the library API; rich sits behind the `genekit[rich]` extra with a
  silent plain-stream fallback when absent; a dedicated usage logger seen in one sighting was folded
  in as `dedicated_file_logger`.
  - migrate: remove-the-bloat done 2026-07-16 — consumed through a re-export shim keeping the app's
    original names, so no call site changed.
  - migrate: Plex pending — a previously recorded migration is not present in the repo; the app still
    configures logging locally and its interpreter floor is below the library's. Re-do under
    `/genekit adopt`.
  - migrate: Starling done 2026-07-16 — `dedicated_file_logger` replaces the app's usage logger, no shim.
  - migrate: MeadowLark done 2026-07-17 — `configure_logging` at both setup sites, no shim: the
    app's own exception and timestamp helpers are app decisions genekit does not cover. Required
    raising `requires-python`; records gained the library's level and logger columns.
  - migrate: personal-agents (price-tracker) done 2026-07-17 at py-v0.2.0 — adopting its daemon
    logging drove adding optional size-based rotation (`rotate_bytes` / `backup_count`,
    both-or-neither) to the released module.
  - adopt-pending: one further repo has a hand-rolled implementation, found 2026-07-17 —
    candidate for `/genekit adopt`. An external fork was surveyed and excluded as not our code.

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
  `src/logging_utils.py:get_local_timestamp` (a one-line stdlib local-timestamp format)
  is adjacent but too thin to count as an independent solution; revisit if it grows. Check `zoneinfo`
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
  `src/url_utils.py` (per-service id extraction) and a second app's URL filter both encode
  app-specific inclusion decisions, not generic normalization — not counted. `urllib.parse` does
  the parsing; the admissible part is
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

## rate-smoother — time-windowed rolling average of a transfer rate, window growing with elapsed time
- status: candidate
- language: python
- sightings:
  - MeadowLark/src/progress_smoothing.py — 2026-08-26 — `ProgressSmoother`: deque of
    (timestamp, cumulative bytes) samples pruned to a window of
    `clamp(elapsed * 0.25, 3s, 30s)`; derives speed and ETA, EMA-smooths a noisy total
    estimate, and throttles UI repaints. Cumulative series spans file boundaries so the
    rate survives yt-dlp's video-stream → audio-stream switch.
- notes: 1 of 3 sightings. Generalisation concerns: the byte-count/ETA vocabulary is
  transfer-specific — a library version would want a neutral `observe(value, now)` /
  `rate()` API with the ETA and total-estimate smoothing layered on top as optional
  helpers. The repaint throttle is a separate concern and should not be promoted with it.

## config-loading — file + env-var config discovery and merge
- status: candidate
- language: python
- sightings:
  - remove-the-bloat — 2026-07-16 — app config file plus an env-var override naming its location.
  - personal-agents/packages/agents-core/src/agents_core/config.py — 2026-07-16 — config loading for
    agent apps.
- notes: 2 sightings across 2 repos — one short of ripe. The app-specific file name and env-var
  prefix must become parameters — hardcoding either is exactly the kind of thing the charter
  forbids. Compare against `tomllib` + `os.environ` before promoting. Partial match
  surveyed 2026-07-17: MeadowLark `src/config.py:_resolve_path` is env-var override with hardcoded
  defaults but no config-file layer — a subset of this capability, not counted as a sighting; if
  promotion scopes the API to make the file layer optional, recount it.

## user-state-dir — platform-appropriate directory for an app's machine-local state
- status: candidate
- language: python
- sightings:
  - Starling/src/starling/update_check.py — 2026-09-02 — sys.platform branch returning a
    pathlib.Path under the Windows local-appdata variable, the macOS Application Support
    folder, or the XDG state dir, each suffixed with an app name; deliberately separate
    from the app's user-facing data root, which may live in a synced folder. Hand-rolled
    to avoid a new wheel for a dozen lines.
- notes: platformdirs covers this; the open question is whether a dozen lines of stdlib
  beats a dependency for apps that need only one of its directories. Revisit at a second
  sighting.

## release-update-check — throttled check of a project's published releases from a running app
- status: candidate
- language: python
- sightings:
  - MeadowLark/src/version_utils.py — 2026-09-02 — regex-digit version tuple compared
    against the first entry of a forge's releases listing; requests with a timeout, every
    transport error folded to None; a GUI thread surfaces the result in a dialog.
  - Starling/src/starling/update_check.py — 2026-09-02 — same comparison, but for a
    short-lived CLI: an on-disk JSON throttle stamped before a daemon thread refreshes it,
    so the notice comes from cache and the process start path never blocks on the network.
- notes: the version-tuple comparison and the "any failure is None" fetch are the shared
  core; presentation and throttling differ per app shape and should stay caller-side.
