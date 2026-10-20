# Promotion Ledger

One `##` section per capability. Statuses: `candidate` (<3 sightings) → `ripe` (passes the
ripeness check in [CHARTER.md § Admission](../CHARTER.md#admission-rule-of-three), awaiting /genekit promote) → `promoted` (module + first tag) or `rejected` (with reason).
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
  - migrate: quicknote done 2026-09-16 — adopted directly by a new worker entry point with no prior
    app-local setup: `configure_logging` with size rotation, no shim. On py-v0.3.1 since 2026-09-17.
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
  - migrate: remove-the-bloat done 2026-09-25 at py-v0.4.0 — `resolve_tz` (strict) for the fixed
    zone plus `format_timestamp` on an aware UTC "now", no shim; the hand-rolled formatter is gone.

## url-helpers — URL normalization and comparison
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/urls.py — 2026-07-16 — normalization used
    across agent tooling.
  - personal-agents/apps/price-tracker/src/price_tracker/utils.py:8-18 — 2026-07-17 —
    `site_label` (hostname extraction + www-strip for display) and `href_safe` (bracket
    percent-encoding). Same repo as the first sighting — repo count stays 1 of 2.
  - personal-agents/packages/agents-core/src/agents_core/urls.py:61-76 — 2026-09-25 —
    `host_matches`: dot-bounded host-equals-or-subdomain test, case-insensitive, root dot
    stripped, empty domain never matches; consolidates hand-rolled `endswith("." + d)` checks
    behind domain allowlists. Same repo — repo count stays 1 of 2.
- notes: 3 sightings, 1 repo — needs a sighting in a second repo. Surveyed 2026-07-17: MeadowLark
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
- notes: platformdirs covers this; the open question is whether a small stdlib helper
  beats a dependency for apps that need only one of its directories. Revisit at a second
  sighting.

## capped-backoff — capped exponential backoff delay for a poll loop
- status: candidate
- language: python
- sightings:
  - quicknote/backend/src/quicknote/tagger/worker.py:39-41 — 2026-09-16 — pure function
    base*2**n capped; paired with warn-once/debug-while-failing/info-on-recovery log
    transitions in an asyncio poll loop.
  - potd/backend/src/potd/backoff.py:6-21 — 2026-10-17 — pure base*2**n capped, base and cap
    both parameters; used for a short in-request retry ladder that skips non-idempotent calls
    and for a per-item worker delay with a different cap per state.
- notes: 2 sightings across 2 repos.

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
- notes: Promoted 2026-09-19 as `genekit.atomic_write` (py-v0.4.0). `os.replace` (atomic rename
  on POSIX and Windows) and `tempfile` do the mechanics; what was admissible is the policy all four
  sightings hand-rolled around them — a same-directory temp so the rename never crosses a
  filesystem, a unique temp name always (a fixed suffix collides under concurrent writers and fails
  on Windows while a reader holds the file), cleanup of the temp on any exception, and raise-or-
  swallow as a parameter. Shipped as `atomic_write_text` and an `atomic_write_bytes` twin, each
  with an opt-in parent `mkdir` and `on_error="raise" | "ignore"`, returning `False` only when an
  ignored `OSError` left the target untouched. JSON serialisation stays caller-side; the
  swallow-and-log variants become `on_error="ignore"` or the caller logging the raised error.
  - migrate: Starling done 2026-09-19 at py-v0.4.0 — `atomic_write_text` replaces the throttle
    cache's inline temp-write; call-site edit, no shim; `on_error="ignore"` keeps the original
    swallow-silently behaviour.
  - migrate: MeadowLark done 2026-09-19 at py-v0.4.0 — `atomic_write_text` replaces the app's local
    helper at its call sites, no shim; `on_error="raise"` so the app's exception logging still gets
    the real error.
  - migrate: evertold done 2026-09-19 at py-v0.4.0 — `atomic_write_bytes` replaces an inline
    named-temp-file write; call-site edit, no shim; still propagates on failure, now with the temp
    cleanup it lacked. First genekit dependency for this repo.
  - migrate: remove-the-bloat done 2026-09-19 at py-v0.4.0 — `atomic_write_text` replaces the
    deleted local helper; call-site edits, no shim; the default `on_error="raise"` reproduces its
    always-re-raise behaviour.

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

## sqlite-wal-enable — switch a SQLite file shared across processes to WAL without racing
- status: candidate
- language: python
- sightings:
  - personal-agents/packages/agents-core/src/agents_core/sqlite_wal.py:6-44 — 2026-09-24 —
    `enable_wal` over stdlib sqlite3: read the journal mode first; try the switch; on
    a busy error (the switch's read-to-write lock upgrade bypasses the busy handler) wait out
    the holder with BEGIN IMMEDIATE, roll back, re-read, switch again only if still not WAL.
    Refuses an open transaction, where the switch is silently ignored.
- notes: returns the resulting mode rather than raising for in-memory databases.

## sql-like-literal-escape — escape user text for a literal "contains" SQL LIKE match
- status: candidate
- language: php
- sightings:
  - diet/searchParser.php:28-59 — 2026-09-25 — static helper pair:
    single-pass strtr map escapes the escape char, percent and underscore, then wraps in
    percent signs; companion emits the predicate with an explicit ESCAPE clause using a
    non-backslash char so behaviour is independent of the server's backslash-escape SQL mode.
- notes: a Python port would take the escape char as a parameter; driver-agnostic.

## http-json-get — GET-only JSON fetch over stdlib urllib with header-borne auth
- status: candidate
- language: python
- sightings:
  - remove-the-bloat/src/remove_the_bloat/pipeline/plex.py:49-64,99-128 — 2026-09-25 — opener with proxies disabled and redirects refused; credential sent in a request header and scrubbed from every error message; transport, HTTP-status and decode errors normalised into one app exception raised without chaining; injectable fetch callable for tests.
- notes: single sighting so far.

## mapped-drive-unc — spell a Windows mapped-drive path by its UNC share root
- status: candidate
- language: python
- sightings:
  - remove-the-bloat/src/remove_the_bloat/pipeline/plex.py:299-321 — 2026-09-29 — resolves only the drive root with os.path.realpath (per-drive functools.cache, root kept on OSError) and re-attaches the unresolved remainder, so symlinks below the root are never followed; returns ordered, de-duplicated lookup keys, the as-typed spelling first.
- notes: 1 of 3 sightings. Alternative mechanism: ctypes WNetGetConnectionW.

## ip-network-key — normalize a client IP to a stable trust identity
- status: candidate
- language: php
- sightings:
  - diet/authPolicy.php:10-37 — 2026-10-10 — pure function; validates with the stdlib IP filter (rejects zone ids and padding), folds IPv4-mapped IPv6 to the IPv4 key, truncates other IPv6 to its /64 prefix via inet_pton/inet_ntop canonical text; invalid input yields null.
- notes: single sighting so far. Python port would use the stdlib ipaddress module.

## split-token-persistent-login — remember-me cookie as selector + hashed validator with rotation grace
- status: candidate
- language: php
- sightings:
  - diet/authPolicy.php:39-115 — 2026-10-10 — cookie is a lookup selector plus a random validator stored only as a SHA-256; pure decision function (expired / mismatch / rotate / ok) kept apart from the DB I/O; validator rotates at most daily with a short grace for the previous one; a wrong validator deletes the row as theft; idle and absolute lifetimes.
- notes: single sighting so far; its cookie and DB I/O half sits in diet/auth.php:124-215. The
  decision/I-O split is the reusable part; storage and cookie plumbing stay app-side.

## oauth-loopback-receiver — installed-app OAuth redirect receiver on a loopback socket
- status: candidate
- language: php
- sightings:
  - personal-dashboard/app/Dashboard/Sources/GoogleHealth/SocketCallbackListener.php:32-101 — 2026-10-12 — stream socket bound to an ephemeral loopback port; accepts until a request carries the expected state (constant-time compare) plus a code or error, answers strays 404/400 and keeps waiting; every read capped by one overall deadline. PKCE S256 pair from random bytes sits in a separate helper.
- notes: 1 of 3 sightings. The listener sits behind a start/await/stop interface so flows test with a fake.

## civil-date-windows — split an inclusive civil-date span into bounded half-open windows on zone-local midnights
- status: candidate
- language: php
- sightings:
  - personal-dashboard/app/Dashboard/Sources/GoogleHealth/CivilWindows.php:25-48 — 2026-10-12 — splits an inclusive civil-date span into windows of at most N days, end exclusive, stepping with calendar addDays on zone-local midnights so a DST change never moves a boundary off midnight. First after last gives none; N below 1 raises.
  - personal-dashboard/app/Dashboard/Sources/GitHubSource.php:87-113 — 2026-10-12 — same walk with a calendar-year step: windows chosen so an API's per-request span cap is never exceeded, the last one clamped to today in the owner's zone; a UTC instant is converted to that zone before its date is taken.
  - potd/android/app/src/main/java/com/thegenecode/potd/media/DayWindow.kt:24-32 — 2026-10-20 — one civil day to half-open instant bounds via the zone-aware start of day for the day and for day+1 (calendar arithmetic, so a DST day is 23 or 25 hours and a skipped midnight resolves forward); a second, wider pair pads the span by a fixed duration. Kotlin, java.time.
- notes: Re-examined 2026-10-20, not ripe. The two span-splitting sightings share one repo; the
  third bounds a single day, which java.time's zone-aware start of day already does in one call, so
  it is a different problem. No sighting is in a language genekit ships, so a promotion would have
  no consumer to migrate. Needs a span-splitting sighting in a second repo.

## locale-number-parse — displayed numeric string (grouping, percent, chosen decimal mark) to a float
- status: candidate
- language: php
- sightings:
  - personal-dashboard/app/Dashboard/Sources/Sheets/LocaleNumber.php:12-47 — 2026-10-13 — static parse of a spreadsheet's displayed number: strips space-like and apostrophe grouping, one leading or trailing percent sign and the Unicode minus; caller names the decimal mark and the other mark is accepted only as strict three-digit grouping, so ambiguous input returns null instead of a guess. Regex-validated before the float cast.
- notes: 1 of 3 sightings. Returns null rather than guessing; callers log the rejected cell.

## oauth-refresh-token-store — persist a rotating OAuth refresh token under a lock before using the access token
- status: candidate
- language: php
- sightings:
  - personal-dashboard/app/Dashboard/Sources/GoogleHealth/GoogleTokenStore.php:53-180 — 2026-10-13 — fresh-token check outside a cache lock; inside it re-reads the stored row so a token rotated by another process is never resent; a terminal grant error flags the row so later runs fail fast with zero requests; the new payload is written in one upsert before the access token is returned; bound to a single provider's client.
- notes: 1 of 3 sightings.

## json-redact — replace secret-bearing keys anywhere in a decoded JSON tree before it is logged or saved
- status: candidate
- language: python
- sightings:
  - potd/backend/scripts/spikes/synospike.py:61-79 — 2026-10-16 — recursive walk over dicts and lists replacing values under a fixed key-name set with a marker, applied before a response is written to disk; paired with a stable-placeholder anonymiser (per-kind alias tables, extension kept on file names, path segments aliased unless structural) for turning captures into test fixtures.
- notes: single sighting so far. Spike script, not app code. A library version would take the key set and marker as parameters.


## spa-static-fallback — serve a built single-page app from a web framework, falling back to the shell for client routes
- status: candidate
- language: python
- sightings:
  - quicknote/backend/src/quicknote/app.py:39-66 — 2026-10-18 — catch-all path route registered after the API router; API-prefixed paths stay 404; resolve-then-is_relative_to containment before FileResponse; the shell is served with no-cache so a stale index never points at vanished hashed assets.
  - evertold/backend/src/evertold/main.py:248-290 — 2026-10-18 — standalone helper rather than a nested route; also catches ValueError/OSError from resolve and is_file (NUL bytes, over-long segments, revoked permissions) and answers 503 when the static root itself stops resolving.
- notes: remake/backend/src/remake/app.py is a copy of the first sighting with the second's resolve guard folded in, so it is a consumer, not an independent sighting. API sketch: a function taking the app, the static root and the reserved API prefix.
