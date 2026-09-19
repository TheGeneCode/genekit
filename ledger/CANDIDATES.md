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
- status: promoted (genekit.tz, py-v0.3.0)
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/tz.py — 2026-07-16 — battle-tested in
    production use.
  - remove-the-bloat/src/remove_the_bloat/activity.py:31-45 — 2026-07-17 — hand-rolled
    Denver-local timestamp helper (`_DENVER = ZoneInfo(...)` + `_timestamp()` construction/format).
  - MeadowLark/src/podcast_filtering.py:119-137 — 2026-09-16 — epoch-to-local-calendar-day display
    formatter. Independent variation: input is a POSIX float rather than a datetime, and a missing
    value renders as a sentinel string instead of raising. Converts via `astimezone()` before
    `strftime`, and threads an injectable tzinfo (default `None` = system local) so the
    UTC-vs-local conversion is testable without depending on the host machine's zone.
- notes: Promoted 2026-09-17 as `genekit.tz` (py-v0.3.0). `zoneinfo` and `astimezone` keep the tz
  database, the DST arithmetic and the conversion; what was admissible is the policy around them,
  which all three sightings hand-rolled — an unresolvable zone name degrades instead of raising, a
  naive datetime means UTC rather than system local, and a missing instant renders as a placeholder.
  Shipped as `local_tz`, `resolve_tz`, `to_tz`, `format_timestamp`. A `now_in(tz)` helper was
  designed and dropped: `datetime.now(resolve_tz(name))` is already correct and a wrapper for it
  would only save typing. MeadowLark's `src/logging_utils.py:get_local_timestamp` stayed adjacent
  and uncounted. The IANA database is absent on Windows, so zone lookup sits behind a `tzdata`
  extra with the documented fallback.
  - migrate: MeadowLark done 2026-09-17 at py-v0.3.0 — `format_timestamp` behind a thin shim that
    keeps the app's own name and placeholder, so no call site changed. Accepted: an unrepresentable
    timestamp no longer routes through the app's own exception log.
  - migrate: personal-agents done 2026-09-17 at py-v0.3.1 — `resolve_tz` behind a re-export shim;
    `to_tz` and `format_timestamp` replace hand-rolled display conversions at call sites. Accepted:
    an unknown zone in the web layer falls back instead of raising; the warning text changed.
  - migrate: remove-the-bloat pending — a fixed-zone "now" formatter; `to_tz` plus an explicit zone
    covers it. Do it under `/genekit adopt`.

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
    to avoid a new wheel.
- notes: platformdirs covers this; the open question is whether a dozen lines of stdlib
  beats a dependency for apps that need only one of its directories. Revisit at a second
  sighting.

## capped-backoff — capped exponential backoff delay for a poll loop
- status: candidate
- language: python
- sightings:
  - quicknote/backend/src/quicknote/tagger/worker.py:39-41 — 2026-09-16 — pure function
    base*2**n capped; paired with warn-once/debug-while-failing/info-on-recovery log
    transitions in an asyncio poll loop.
- notes: 1 of 3 sightings.

## atomic-write — write a small file so a reader never sees a half-written result
- status: promoted (genekit.atomic_write, py-v0.4.0)
- language: python
- sightings:
  - Starling/src/starling/update_check.py:150-165 — 2026-09-18 — sibling temp file named with
    the writer's pid, `write_text` then `os.replace`; every `OSError` swallowed and the temp
    unlinked, because the caller is a best-effort throttle cache.
  - MeadowLark/src/failed_downloads.py:76-90 — 2026-09-18 — fixed `.tmp` suffix sibling,
    `Path.replace`; failure is logged through the app's exception logger and the temp removed,
    never raised.
  - evertold/backend/src/evertold/datadir_file.py:60-80 — 2026-09-18 — `NamedTemporaryFile`
    in the target's directory with a unique name, then `Path.replace`, under a mint lock; unique
    name chosen because Windows refuses to replace a file another thread still holds open.
    Errors propagate.
  - remove-the-bloat/src/remove_the_bloat/cache.py:42-56 — 2026-09-18 — `tempfile.mkstemp` in
    the target's directory, `os.fdopen` write, `Path.replace`; on any `BaseException` the temp
    is unlinked and the error re-raised. Written for concurrent readers.
- notes: 4 sightings across 4 repos. The stdlib gives `os.replace` (atomic rename on POSIX and
  Windows) and `tempfile`; what every sighting hand-rolls is the policy around it — same-directory
  temp so the rename never crosses a filesystem, a unique-vs-fixed temp name (fixed collides under
  concurrency and fails on Windows if a reader holds the file), cleanup of the temp on failure, and
  whether failure raises or is swallowed. API sketch: `atomic_write_text(path, text, *,
  encoding="utf-8", on_error="raise" | "ignore")` plus an `atomic_write_bytes` twin; unique temp
  name always (pid + counter or `mkstemp`); `mkdir(parents=True)` of the parent as an option since
  two sightings do it inline. JSON serialisation stays caller-side. The "swallow and log" variants
  become `on_error="ignore"` plus the caller's own log line.
- migrate: MeadowLark done 2026-09-19 — atomic_write_text replaces the app's local atomic-write helper at its call sites;
  call-site edits, no shim; on_error="raise" kept so the existing exception logging
  still gets the real exception.
- migrate: evertold done 2026-09-19 — atomic_write_bytes replaces DataDirFile.read's inline
  NamedTemporaryFile write; call-site edit, no shim; on_error="raise" kept, matching the
  original's propagate-on-failure behaviour, now with cleanup it previously lacked.
- migrate: remove-the-bloat pending — local helper to be deleted in favor of atomic_write_text
  under /genekit adopt.
- migrate: Starling done 2026-09-19 — atomic_write_text replaces write_state's inline
  temp-write; call-site edit, no shim; on_error="ignore" preserves the original swallow-silently
  behaviour.

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
