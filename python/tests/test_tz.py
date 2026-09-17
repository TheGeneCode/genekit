"""Tests for genekit.tz.

Boundary Matrix
===============

Dimension A — resolve_tz: ``name`` value
------------------------------------------------------------------
| Cell | Input                          | Expected                              |
|------|--------------------------------|---------------------------------------|
| A1   | "" (empty)                     | fallback                              |
| A2   | "   " (whitespace-only)        | fallback                              |
| A3   | "\\t\\n"                         | fallback                              |
| A4   | None                           | fallback                              |
| A5   | "UTC"                          | ZoneInfo("UTC")        (needs tzdb)   |
| A6   | "America/Denver"               | ZoneInfo(...)          (needs tzdb)   |
| A7   | " America/Denver "  (padded)   | ZoneInfo(...)          (needs tzdb)   |
| A8   | "america/chicago" (bad case)   | fallback + warning                    |
| A9   | "Not/AZone"                    | fallback + warning                    |
| A10  | "../etc/passwd"  (ValueError)  | fallback + warning, never raises      |
| A11  | "Zürich/Ünïcode" (unicode)     | fallback + warning                    |
| A12  | "\\x00bad" (NUL)                | fallback + warning                    |
| A13  | "a" * 300 (long, OSError)      | fallback + warning, never raises      |
| A14  | 42 (wrong type, TypeError)     | fallback + warning, never raises      |
| A15  | timezone.utc (tzinfo)          | passed through, identity preserved    |
| A16  | ZoneInfo instance              | passed through, identity preserved    |

Dimension B — resolve_tz: ``strict``
------------------------------------------------------------------
| Cell | name / strict            | Expected                                     |
|------|--------------------------|----------------------------------------------|
| B1   | "Not/AZone", strict=True | raises ZoneInfoNotFoundError                 |
| B2   | "../x", strict=True      | raises ZoneInfoNotFoundError (not ValueError)|
| B3   | 42, strict=True          | raises ZoneInfoNotFoundError (not TypeError) |
| B4   | "", strict=True          | fallback — empty is a request, not a failure |
| B5   | None, strict=True        | fallback                                     |
| B6   | tzinfo, strict=True      | passed through                               |

Dimension C — resolve_tz: ``fallback``
------------------------------------------------------------------
| Cell | fallback     | Expected                        |
|------|--------------|---------------------------------|
| C1   | None         | local_tz()                      |
| C2   | timezone.utc | timezone.utc                    |
| C3   | any          | return value is never None      |

Dimension D — to_tz: awareness of ``value``
------------------------------------------------------------------
| Cell | value                  | assume        | Expected                          |
|------|------------------------|---------------|-----------------------------------|
| D1   | naive                  | utc (default) | stamped UTC, then converted       |
| D2   | naive                  | None          | stdlib behaviour (system local)   |
| D2b  | naive, tz=None         | None          | equals naive.astimezone() exactly |
| D3   | aware UTC              | any           | assume ignored, instant preserved |
| D4   | aware non-UTC          | any           | instant preserved                 |
| D5   | datetime.min (naive)   | utc           | OverflowError on westward convert |
| D6   | datetime.max (naive)   | utc           | OverflowError on eastward convert |
| D7   | datetime.min/max       | tz=None       | OverflowError, not the OSError degrade |
| D8   | naive pre-1970         | assume=None   | tz=None degrades, warning emitted once |

Dimension E — to_tz: ``tz`` target
------------------------------------------------------------------
| Cell | tz             | Expected                                                 |
|------|----------------|----------------------------------------------------------|
| E1   | None           | system local, per-instant offset (NOT local_tz())        |
| E2   | timezone.utc   | tzinfo is timezone.utc                                   |
| E3   | "UTC" (str)    | resolved via resolve_tz                (needs tzdb)      |
| E4   | "Not/AZone"    | falls back, still returns aware datetime, never raises   |

Dimension F — format_timestamp: ``value`` type and range
------------------------------------------------------------------
| Cell | value                   | Expected                                     |
|------|-------------------------|----------------------------------------------|
| F1   | None                    | default                                      |
| F2   | 0 (epoch)               | "1970-01-01 00:00:00" in UTC                 |
| F3   | -1 (pre-epoch)          | "1969-12-31 23:59:59" in UTC                 |
| F4   | 0.5 (fractional)        | formats, sub-second truncated by fmt         |
| F5   | float("nan")            | default (ValueError swallowed)               |
| F6   | 1e18 (out of range)     | default (OSError swallowed)                  |
| F7   | float("inf")            | default                                      |
| F8   | datetime (naive)        | assumed UTC, then converted                  |
| F9   | datetime (aware)        | converted                                    |
| F10  | True / False (bool)     | TypeError — never a meaningful instant       |
| F11  | "0" (str)               | TypeError                                    |
| F12  | date (not datetime)     | TypeError                                    |

Dimension G — format_timestamp: ``fmt`` and ``default``
------------------------------------------------------------------
| Cell | Input                    | Expected                                    |
|------|--------------------------|---------------------------------------------|
| G1   | fmt default              | DEFAULT_FORMAT applied                      |
| G2   | fmt="%Y-%m-%d"           | date only                                   |
| G3   | fmt="" (empty)           | "" — a valid strftime format                |
| G4   | fmt with unicode         | unicode preserved in output                 |
| G5   | default="" (default)     | "" for None                                 |
| G6   | default="(unknown)"      | "(unknown)" for None                        |
| G7   | fmt="%Q" / "%" / "%-d"   | ValueError on every OS — a caller bug       |
| G8   | each portable directive  | identical literal text on every OS          |
| G9   | "%%Y" / "%%%Y"           | escaped percent then literal/directive text |
| G10  | literal containing NUL   | passed through untouched, never hits C      |
| G11  | arbitrary text w/o "%"   | property: output equals the input verbatim  |

Dimension H — the calendar-day defect this module exists to prevent
------------------------------------------------------------------
| Cell | Scenario                                             | Expected                |
|------|------------------------------------------------------|-------------------------|
| H1   | late-evening local instant, rendered in a west zone   | local day, not UTC day  |
| H2   | local_tz() used to convert across a DST boundary     | documented to be wrong  |
| H3   | to_tz(dt, None) across a DST boundary                | correct per-instant     |

Dimension I — concurrency
------------------------------------------------------------------
| Cell | Scenario                                    | Expected                       |
|------|---------------------------------------------|--------------------------------|
| I1   | resolve_tz from many threads at once        | all agree, no exception        |
| I2   | format_timestamp from many threads at once  | all agree, no exception        |
"""

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from genekit.tz import DEFAULT_FORMAT, format_timestamp, local_tz, resolve_tz, to_tz

UTC = timezone.utc


def _tzdb_has(key: str) -> bool:
    """Whether this interpreter can resolve ``key``.

    CPython ships no tz database on Windows, so every lookup fails unless ``tzdata`` is installed.
    Tests that assert real IANA behaviour skip rather than fail there; the fallback path those same
    hosts actually take is covered unconditionally.
    """
    try:
        ZoneInfo(key)
    except (KeyError, ValueError, TypeError):
        return False
    return True


_HAS_TZDB = _tzdb_has("America/Denver")
needs_tzdb = pytest.mark.skipif(_HAS_TZDB is False, reason="no IANA tz database on this host")

# Values that must never raise and must never resolve, whatever is installed.
_UNRESOLVABLE = [
    pytest.param("america/chicago", id="A8-wrong-case"),
    pytest.param("Not/AZone", id="A9-unknown"),
    pytest.param("../etc/passwd", id="A10-not-normalized-ValueError"),
    pytest.param("Zürich/Ünïcode", id="A11-unicode"),
    pytest.param("\x00bad", id="A12-nul-byte"),
    pytest.param("a" * 300, id="A13-long"),
    pytest.param(42, id="A14-wrong-type-TypeError"),
]

_BLANK = [
    pytest.param("", id="A1-empty"),
    pytest.param("   ", id="A2-spaces"),
    pytest.param("\t\n", id="A3-tab-newline"),
    pytest.param(None, id="A4-None"),
]


# --------------------------------------------------------------------------------------
# local_tz
# --------------------------------------------------------------------------------------


def test_local_tz_returns_a_usable_tzinfo() -> None:
    """C3: the contract is a tzinfo, never None, so it can be handed to a scheduler or a test."""
    tz = local_tz()
    assert tz is not None
    assert datetime.now(tz).tzinfo is tz
    assert tz.utcoffset(datetime(2026, 1, 15, 12, 0)) is not None


def test_local_tz_is_a_frozen_snapshot_not_a_dst_aware_zone() -> None:
    """H2: the documented caveat, pinned as a test so the docstring cannot quietly go stale.

    ``local_tz()`` reports the offset in effect *now*. Converting through it gives a single fixed
    offset for every instant, whereas the stdlib's no-argument ``astimezone()`` recomputes per
    instant. On a host observing DST the two disagree for at least one of these two dates — that
    disagreement is precisely why :func:`to_tz` does not use ``local_tz()`` for ``tz=None``.

    The comparison is on the *wall clock*, not on the datetimes: two aware datetimes denoting one
    instant compare equal however different the clock faces they show, which is exactly the
    equality that lets this bug hide in production code.
    """
    snapshot = local_tz()
    jan = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    jul = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert jan.astimezone(snapshot).utcoffset() == jul.astimezone(snapshot).utcoffset()
    observes_dst = jan.astimezone().utcoffset() != jul.astimezone().utcoffset()
    if observes_dst:
        frozen = (jan.astimezone(snapshot), jul.astimezone(snapshot))
        live = (jan.astimezone(), jul.astimezone())
        assert [d.replace(tzinfo=None) for d in frozen] != [d.replace(tzinfo=None) for d in live]


# --------------------------------------------------------------------------------------
# resolve_tz
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BLANK)
def test_blank_names_return_the_fallback(name: object) -> None:
    """A1-A4 + C2: blank is a request for the fallback, not an error."""
    assert resolve_tz(name, fallback=UTC) is UTC  # type: ignore[arg-type]


@pytest.mark.parametrize("name", _BLANK)
def test_blank_names_return_the_fallback_even_when_strict(name: object) -> None:
    """B4-B5: ``strict`` is about unresolvable names; an absent name is not one."""
    assert resolve_tz(name, fallback=UTC, strict=True) is UTC  # type: ignore[arg-type]


@pytest.mark.parametrize("name", _BLANK)
def test_blank_names_default_to_the_local_zone(name: object) -> None:
    """C1: ``fallback=None`` means the system local zone."""
    assert resolve_tz(name) == local_tz()  # type: ignore[arg-type]


@pytest.mark.parametrize("name", _UNRESOLVABLE)
def test_unresolvable_names_fall_back_without_raising(name: object) -> None:
    """A8-A14: the whole point of the policy — a bad config value is not a crash.

    ZoneInfo raises four different things here: ZoneInfoNotFoundError for an unknown key,
    ValueError for a key that is not a normalized relative path (``"../etc/passwd"``), TypeError for
    a non-string, and OSError when the key is long enough to blow the platform's filename limit. A
    fallback that caught only the documented exception would still take the process down on exactly
    the inputs a config file produces.
    """
    assert resolve_tz(name, fallback=UTC) is UTC  # type: ignore[arg-type]


@pytest.mark.parametrize("name", _UNRESOLVABLE)
def test_unresolvable_names_warn(name: object, caplog: pytest.LogCaptureFixture) -> None:
    """B-dimension of the original sighting: falling back silently hides a typo forever."""
    with caplog.at_level(logging.WARNING, logger="genekit.tz"):
        resolve_tz(name, fallback=UTC)  # type: ignore[arg-type]
    assert len(caplog.records) == 1
    assert repr(name) in caplog.records[0].getMessage()


@pytest.mark.parametrize("name", _BLANK)
def test_blank_names_do_not_warn(name: object, caplog: pytest.LogCaptureFixture) -> None:
    """The companion negative: a warning on every unset config value is noise nobody reads."""
    with caplog.at_level(logging.WARNING, logger="genekit.tz"):
        resolve_tz(name, fallback=UTC)  # type: ignore[arg-type]
    assert caplog.records == []


@pytest.mark.parametrize("name", _UNRESOLVABLE)
def test_strict_raises_one_exception_type_for_every_failure(name: object) -> None:
    """B1-B3: ValueError and TypeError are normalised to ZoneInfoNotFoundError.

    Callers get a single thing to catch; without this they would have to catch three types to
    cover the same "that zone is not usable" condition.
    """
    with pytest.raises(ZoneInfoNotFoundError):
        resolve_tz(name, strict=True)  # type: ignore[arg-type]


def test_strict_failure_chains_the_underlying_cause() -> None:
    """The normalisation must not destroy the diagnosis."""
    with pytest.raises(ZoneInfoNotFoundError) as excinfo:
        resolve_tz("Not/AZone", strict=True)
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize(
    "tz",
    [pytest.param(UTC, id="A15-timezone"), pytest.param(timezone(timedelta(hours=5)), id="offset")],
)
def test_tzinfo_passes_through_by_identity(tz: timezone) -> None:
    """A15: normalising ``str | tzinfo | None`` in one place only works if tzinfo is idempotent."""
    assert resolve_tz(tz) is tz
    assert resolve_tz(tz, strict=True) is tz
    assert resolve_tz(tz, fallback=UTC) is tz


@needs_tzdb
def test_zoneinfo_instance_passes_through_by_identity() -> None:
    """A16: the pass-through must not re-resolve and hand back a different object."""
    zone = ZoneInfo("America/Denver")
    assert resolve_tz(zone) is zone


@needs_tzdb
@pytest.mark.parametrize(
    "name",
    [
        pytest.param("UTC", id="A5"),
        pytest.param("America/Denver", id="A6"),
        pytest.param("Asia/Kolkata", id="half-hour-offset"),
        pytest.param("Pacific/Kiritimati", id="far-east-+14"),
    ],
)
def test_valid_iana_names_resolve_to_zoneinfo(name: str) -> None:
    """A5-A6: the happy path, including two zones whose offsets are easy to get wrong."""
    resolved = resolve_tz(name)
    assert isinstance(resolved, ZoneInfo)
    assert str(resolved) == name


@needs_tzdb
def test_surrounding_whitespace_is_stripped_from_a_name() -> None:
    """A7: config files and env vars carry stray whitespace; that is not a typo worth punishing."""
    assert resolve_tz("  America/Denver  ") == ZoneInfo("America/Denver")


def test_missing_tz_database_degrades_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows-without-``tzdata`` state, forced so it is covered on hosts that do have a tzdb.

    There, *every* key fails including ``"UTC"``. Importing genekit must not become a liability on
    such a host, so a perfectly valid name still degrades to local with a warning.
    """

    def _no_database(key: str) -> ZoneInfo:
        raise ZoneInfoNotFoundError(f"No time zone found with key {key}")

    monkeypatch.setattr("genekit.tz.ZoneInfo", _no_database)
    assert resolve_tz("America/Denver", fallback=UTC) is UTC
    with pytest.raises(ZoneInfoNotFoundError):
        resolve_tz("America/Denver", strict=True)


# --------------------------------------------------------------------------------------
# to_tz
# --------------------------------------------------------------------------------------


def test_naive_input_is_assumed_utc_not_system_local() -> None:
    """D1: the decision. The stdlib guesses system local, which is wrong for naive-UTC storage."""
    naive = datetime(2026, 1, 15, 12, 0)
    assert to_tz(naive, UTC) == datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def test_assume_none_restores_the_stdlib_guess() -> None:
    """D2: the opinionated default is overridable, per the charter."""
    naive = datetime(2026, 1, 15, 12, 0)
    assert to_tz(naive, UTC, assume=None) == naive.astimezone(UTC)


def test_assume_none_and_target_none_together_match_the_stdlib_exactly() -> None:
    """D2b: ``tz=None`` routes a naive value through ``_as_system_local`` *twice*.

    When ``assume=None`` the naive branch already calls ``_as_system_local``; the ``tz is None``
    branch then calls it again on the now-aware result. That second call must be a genuine no-op —
    re-localizing an already-local instant cannot change it — so the composed result still matches
    plain ``naive.astimezone()``. A regression that made the second call re-interpret the value
    (instead of just re-confirming the offset) would drift from the stdlib here without either
    single-call test (D1/D2, which pin ``tz=UTC``) catching it.
    """
    naive = datetime(2026, 1, 15, 12, 0)
    assert to_tz(naive, None, assume=None) == naive.astimezone()


def test_assume_is_ignored_for_aware_input() -> None:
    """D3: ``assume`` answers "what does naive mean", never "reinterpret this instant"."""
    aware = datetime(2026, 1, 15, 12, 0, tzinfo=timezone(timedelta(hours=9)))
    assert to_tz(aware, UTC, assume=timezone(timedelta(hours=-5))) == aware.astimezone(UTC)


def test_conversion_preserves_the_instant() -> None:
    """D4: converting changes the wall clock shown, never the moment denoted."""
    aware = datetime(2026, 7, 4, 23, 30, tzinfo=UTC)
    for target in (UTC, timezone(timedelta(hours=-11)), timezone(timedelta(hours=14))):
        assert to_tz(aware, target).timestamp() == aware.timestamp()


def test_target_none_defers_to_the_stdlib_per_instant_lookup() -> None:
    """E1 / H3: ``tz=None`` must not shortcut through ``local_tz()``'s frozen offset."""
    jan = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    jul = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert to_tz(jan, None) == jan.astimezone()
    assert to_tz(jul, None) == jul.astimezone()


def test_unresolvable_target_still_returns_an_aware_datetime() -> None:
    """E4: the fallback policy composes — a bad zone name degrades the display, not the call."""
    result = to_tz(datetime(2026, 1, 15, 12, 0), "Not/AZone")
    assert result.tzinfo is not None


@needs_tzdb
def test_target_may_be_an_iana_name() -> None:
    """E3: callers should not have to construct a ZoneInfo to name a zone."""
    aware = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    assert to_tz(aware, "America/Denver") == aware.astimezone(ZoneInfo("America/Denver"))


@pytest.mark.parametrize(
    ("value", "target"),
    [
        pytest.param(datetime.min, timezone(timedelta(hours=-14)), id="D5-min-westward"),
        pytest.param(datetime.max, timezone(timedelta(hours=14)), id="D6-max-eastward"),
    ],
)
def test_datetime_range_boundaries_overflow(value: datetime, target: timezone) -> None:
    """D5-D6: the documented OverflowError, not a silent wrap."""
    with pytest.raises(OverflowError):
        to_tz(value, target)


def test_local_conversion_of_a_historical_instant_degrades_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The Windows pre-1970 limit on the no-argument local lookup.

    ``astimezone()`` with no argument goes through the C library, which on Windows raises OSError
    for instants before the epoch. Propagating that would make ``tz=None`` a portability landmine
    that fails on a contributor's machine and passes on CI. It degrades with a warning instead, and
    the instant is preserved either way.
    """
    historical = datetime(1969, 1, 1, 0, 0, tzinfo=UTC)
    with caplog.at_level(logging.WARNING, logger="genekit.tz"):
        result = to_tz(historical, None)
    assert result.tzinfo is not None
    assert result.timestamp() == historical.timestamp()
    if caplog.records:
        assert result.utcoffset() == local_tz().utcoffset(None)


def test_local_target_overflows_at_the_range_boundary_like_an_explicit_one() -> None:
    """D7: the platform degradation covers a platform that cannot answer, not a result that cannot
    exist.

    ``to_tz(datetime.min, tz=None)`` shifts west of ``datetime.min`` on a western host exactly as
    ``to_tz(datetime.min, timezone(-14h))`` does. Both raise OverflowError; that the first also
    passes through the OSError fallback must not turn it into a different exception or a wrong
    answer. Eastern hosts overflow at ``datetime.max`` instead, so accept either end.
    """
    overflowed = []
    for extreme in (datetime.min, datetime.max):
        try:
            result = to_tz(extreme, None)
        except OverflowError:
            overflowed.append(extreme)
        else:
            assert result.timestamp() == extreme.replace(tzinfo=UTC).timestamp()
    assert len(overflowed) <= 1


def test_a_malformed_format_raises_rather_than_rendering_as_default() -> None:
    """G7: the companion to the wrong-type rule — ``default`` means "unknown value", not "bug".

    A typo in a format string would otherwise become a column that is permanently blank, with the
    sentinel indistinguishable from a genuinely missing timestamp. Must hold on every OS: glibc
    copies an unknown directive through verbatim where the Windows UCRT raises, and the glibc-only
    extensions below would otherwise work on Linux and break on Windows.
    """
    for fmt in (
        "%Q",
        "%",
        "%Y-%",
        "%-d",
        "%P",
        "%k",
        "%s",
        "%:z",
        "%#d",
        "%E",
        "%年",
        "%\U0001f600",  # non-BMP directive char: a single Python code point, never a surrogate pair
    ):
        with pytest.raises(ValueError):
            format_timestamp(datetime(2026, 1, 15, 12, 0), UTC, fmt=fmt, default="unreached")


def test_the_degrade_path_warns_once_per_call(caplog: pytest.LogCaptureFixture) -> None:
    """D8: ``assume=None`` with ``tz=None`` resolves system local once, not once per branch.

    Both the naive-input branch and the target branch mean "system local"; running the lookup twice
    doubled the warning for a single conversion. Self-calibrating: on a platform that never needs
    the fallback (glibc handles pre-1970) both counts are 0 and the equality still holds.
    """
    historical = datetime(1969, 1, 1, 0, 0)
    with caplog.at_level(logging.WARNING, logger="genekit.tz"):
        to_tz(historical.replace(tzinfo=UTC), None)
        baseline = len(caplog.records)
        caplog.clear()
        to_tz(historical, None, assume=None)
        assert len(caplog.records) == baseline


def test_datetime_boundaries_are_fine_in_the_safe_direction() -> None:
    """The other half of D5-D6: the boundary is not categorically unusable."""
    assert to_tz(datetime.min, UTC).year == 1
    assert to_tz(datetime.max, UTC).year == 9999


# --------------------------------------------------------------------------------------
# format_timestamp
# --------------------------------------------------------------------------------------


def test_none_renders_as_the_default() -> None:
    """F1 / G5-G6."""
    assert format_timestamp(None) == ""
    assert format_timestamp(None, default="(unknown)") == "(unknown)"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(0, "1970-01-01 00:00:00", id="F2-epoch-zero"),
        pytest.param(-1, "1969-12-31 23:59:59", id="F3-pre-epoch"),
        pytest.param(0.5, "1970-01-01 00:00:00", id="F4-fractional"),
    ],
)
def test_epoch_values_format_in_the_requested_zone(value: float, expected: str) -> None:
    """F2-F4: epoch is UTC by definition; the rendering zone is the caller's choice."""
    assert format_timestamp(value, UTC) == expected


def test_far_pre_epoch_is_platform_dependent_but_never_raises() -> None:
    """The Windows C runtime rejects distant negative timestamps where glibc accepts them.

    The contract is not "every platform renders 1900"; it is that the caller gets a string either
    way and never has to care which platform it is on.
    """
    rendered = format_timestamp(-2208988800, UTC, default="(unknown)")
    assert rendered in {"1900-01-01 00:00:00", "(unknown)"}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="F5-nan"),
        pytest.param(1e18, id="F6-out-of-range"),
        pytest.param(float("inf"), id="F7-inf"),
        pytest.param(float("-inf"), id="F7-neg-inf"),
        pytest.param(2**40, id="out-of-range-int"),
    ],
)
def test_unrepresentable_numbers_render_as_the_default(value: float) -> None:
    """F5-F7: a display string is not worth an exception."""
    assert format_timestamp(value, UTC, default="(unknown)") == "(unknown)"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="F10-True"),
        pytest.param(False, id="F10-False"),
        pytest.param("0", id="F11-str"),
        pytest.param(date(2026, 1, 15), id="F12-date"),
        pytest.param([], id="list"),
    ],
)
def test_wrong_types_raise_rather_than_hiding(value: object) -> None:
    """F10-F12: an unknown value is ``default``; a wrong type is a caller bug, and bool is one.

    ``isinstance(True, int)`` is True, so a bool reaches the epoch branch and would silently render
    as one second past the epoch.
    """
    with pytest.raises(TypeError):
        format_timestamp(value)  # type: ignore[arg-type]


def test_naive_datetime_is_assumed_utc() -> None:
    """F8: consistent with :func:`to_tz`, which is the whole reason it delegates there."""
    assert format_timestamp(datetime(2026, 1, 15, 12, 0), UTC) == "2026-01-15 12:00:00"


def test_aware_datetime_is_converted() -> None:
    """F9."""
    aware = datetime(2026, 1, 15, 12, 0, tzinfo=timezone(timedelta(hours=-7)))
    assert format_timestamp(aware, UTC) == "2026-01-15 19:00:00"


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        pytest.param(DEFAULT_FORMAT, "2026-01-15 12:00:00", id="G1-default"),
        pytest.param("%Y-%m-%d", "2026-01-15", id="G2-date-only"),
        pytest.param("", "", id="G3-empty-format"),
        pytest.param("%Y年%m月%d日", "2026年01月15日", id="G4-unicode"),
        pytest.param("→ %H:%M ←", "→ 12:00 ←", id="G4-unicode-surround"),
    ],
)
def test_format_is_a_parameter(fmt: str, expected: str) -> None:
    """G1-G4: the default is opinionated, and every consumer can override it."""
    assert format_timestamp(datetime(2026, 1, 15, 12, 0), UTC, fmt=fmt) == expected


def test_every_portable_directive_renders_the_same_text_on_every_platform() -> None:
    """G8: the accepted set is neither too narrow nor platform-dependent.

    Expected values are literal, not ``datetime.strftime`` echoed back, so a leg whose C library
    renders one of these differently fails here instead of shipping an OS-specific column.
    """
    moment = datetime(2026, 1, 5, 3, 4, 5, tzinfo=UTC)
    expected = {
        "a": "Mon", "A": "Monday", "b": "Jan", "B": "January", "c": "Mon Jan  5 03:04:05 2026",
        "C": "20", "d": "05", "D": "01/05/26", "e": " 5", "f": "000000", "F": "2026-01-05",
        "g": "26", "G": "2026", "h": "Jan", "H": "03", "I": "03", "j": "005", "m": "01",
        "M": "04", "n": "\n", "p": "AM", "r": "03:04:05 AM", "R": "03:04", "S": "05", "t": "\t",
        "T": "03:04:05", "u": "1", "U": "01", "V": "02", "w": "1", "W": "01", "x": "01/05/26",
        "X": "03:04:05", "y": "26", "Y": "2026", "z": "+0000", "Z": "UTC", "%": "%",
    }  # fmt: skip
    for code, text in expected.items():
        assert format_timestamp(moment, UTC, fmt=f"<%{code}>") == f"<{text}>", code


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        pytest.param("%%Y", "%Y", id="G9-escaped-percent-then-literal"),
        pytest.param("%%%Y", "%2026", id="G9-escaped-percent-then-directive"),
    ],
)
def test_escaped_percent_advances_the_tokenizer_by_two(fmt: str, expected: str) -> None:
    """G9: ``%%`` must consume exactly its own two characters, not one or three.

    ``"%%Y"`` is an escaped percent followed by the plain letter ``Y`` — never the year directive.
    ``"%%%Y"`` is the same escape immediately followed by a real ``%Y``. An off-by-one in how far
    the scan advances past ``%%`` would misalign the next token and either swallow the following
    directive into a literal or treat a literal character as a directive.
    """
    assert format_timestamp(datetime(2026, 1, 15, 12, 0), UTC, fmt=fmt) == expected


def test_nul_byte_in_a_literal_is_passed_through_untouched() -> None:
    """G10: proves the fix's actual mechanism — literal text never reaches C ``strftime``.

    A NUL terminates a C string early; formatting this through the old ``moment.strftime(fmt)``
    path would silently truncate the output at the NUL on at least one platform. Routing the
    literal through Python string concatenation instead must preserve it exactly.
    """
    result = format_timestamp(datetime(2026, 1, 15, 12, 0), UTC, fmt="a\x00b-%Y")
    assert result == "a\x00b-2026"


def test_default_format_matches_the_logging_module() -> None:
    """One library, one timestamp shape: a log line and a rendered field should not disagree."""
    from genekit.logging import VERBOSE_DATEFMT

    assert DEFAULT_FORMAT == VERBOSE_DATEFMT


# --------------------------------------------------------------------------------------
# H — the defect this module exists to prevent
# --------------------------------------------------------------------------------------


def test_late_evening_local_instant_renders_the_local_calendar_day() -> None:
    """H1: the regression the third sighting was fixing, stated as a test.

    2026-01-16 04:30 UTC is still 2026-01-15 in the Americas. Formatting the UTC value directly
    shows the 16th — a date one day ahead of the reader's own — and that is what happens whenever
    the conversion is skipped.
    """
    instant = datetime(2026, 1, 16, 4, 30, tzinfo=UTC)
    mountain = timezone(timedelta(hours=-7))
    assert format_timestamp(instant, mountain, fmt="%Y-%m-%d") == "2026-01-15"
    assert format_timestamp(instant, UTC, fmt="%Y-%m-%d") == "2026-01-16"


@needs_tzdb
def test_dst_boundary_uses_the_offset_in_effect_at_that_instant() -> None:
    """H3: a real DST-aware zone, where a frozen offset would be an hour out.

    2026-03-08 09:00 UTC is 02:00 MST, and 10:00 UTC is 04:00 MDT — the hour 02:00-03:00 local does
    not exist that morning. Getting this right is what ZoneInfo is for and why the module resolves
    to one rather than to a fixed offset.
    """
    denver = ZoneInfo("America/Denver")
    before = datetime(2026, 3, 8, 8, 59, tzinfo=UTC)
    after = datetime(2026, 3, 8, 9, 30, tzinfo=UTC)
    assert to_tz(before, denver).utcoffset() == timedelta(hours=-7)
    assert to_tz(after, denver).utcoffset() == timedelta(hours=-6)


# --------------------------------------------------------------------------------------
# I — concurrency
# --------------------------------------------------------------------------------------


def test_concurrent_callers_agree(caplog: pytest.LogCaptureFixture) -> None:
    """I1-I2: the module holds no mutable state, but ZoneInfo caches and logging is shared.

    This pins the absence of state: a hundred threads hitting the resolve/fallback/format paths at
    once must produce one distinct answer each, and no exception.
    """
    instant = datetime(2026, 1, 16, 4, 30, tzinfo=UTC)
    resolved: list[object] = []
    rendered: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    start = threading.Barrier(24)

    def worker(index: int) -> None:
        try:
            start.wait(timeout=10)
            name = "Not/AZone" if index % 2 else ""
            tz = resolve_tz(name, fallback=UTC)
            text = format_timestamp(instant, tz)
        except BaseException as exc:  # noqa: BLE001 - recorded and re-asserted on the main thread
            with lock:
                errors.append(exc)
            return
        with lock:
            resolved.append(tz)
            rendered.append(text)

    with caplog.at_level(logging.WARNING, logger="genekit.tz"):
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

    assert errors == []
    assert len(rendered) == 24
    assert set(resolved) == {UTC}
    assert set(rendered) == {"2026-01-16 04:30:00"}


# --------------------------------------------------------------------------------------
# Properties — every public function here is pure except local_tz
# --------------------------------------------------------------------------------------

_TZ_STRATEGY = st.sampled_from(
    [None, UTC, timezone(timedelta(hours=-11)), timezone(timedelta(hours=14)), timezone.min]
)
# datetime.min/max overflow under conversion by design (D5-D6); stay inside the safe band so the
# properties below test the invariants rather than re-testing the documented boundary.
_SAFE_DATETIMES = st.datetimes(
    min_value=datetime(2, 1, 1), max_value=datetime(9998, 12, 31, 23, 59, 59)
)


@given(name=st.text(max_size=60))
def test_property_resolve_tz_never_raises_and_never_returns_none(name: str) -> None:
    """The non-strict contract, over arbitrary text rather than the handful of names above."""
    assert resolve_tz(name, fallback=UTC) is not None


@given(name=st.text(max_size=60))
def test_property_resolve_tz_is_idempotent(name: str) -> None:
    """Resolving a resolved zone is the pass-through branch, so it must be a fixed point."""
    once = resolve_tz(name, fallback=UTC)
    assert resolve_tz(once) is once


@given(value=_SAFE_DATETIMES, tz=_TZ_STRATEGY, assume=st.sampled_from([None, UTC]))
def test_property_to_tz_always_returns_an_aware_datetime(
    value: datetime, tz: timezone | None, assume: timezone | None
) -> None:
    """The point of the module: nothing leaves it naive."""
    assert to_tz(value, tz, assume=assume).tzinfo is not None


@given(value=_SAFE_DATETIMES.map(lambda d: d.replace(tzinfo=UTC)), tz=_TZ_STRATEGY)
def test_property_to_tz_preserves_the_instant(value: datetime, tz: timezone | None) -> None:
    """Conversion is a change of representation, never of the moment denoted."""
    assert to_tz(value, tz).timestamp() == value.timestamp()


@given(value=_SAFE_DATETIMES, tz=_TZ_STRATEGY)
def test_property_to_tz_is_idempotent_on_its_own_output(
    value: datetime, tz: timezone | None
) -> None:
    """Re-converting into the same zone is a no-op — a caller cannot corrupt a value by normalising
    twice, which is what makes it safe to call at a boundary and again deeper in."""
    once = to_tz(value, tz)
    assert to_tz(once, tz) == once


@given(
    value=st.one_of(st.none(), _SAFE_DATETIMES, st.floats(), st.integers()),
    tz=_TZ_STRATEGY,
    default=st.text(max_size=20),
)
@settings(max_examples=300)
def test_property_format_timestamp_always_returns_a_string(
    value: datetime | float | None, tz: timezone | None, default: str
) -> None:
    """Total over its declared input domain, including NaN, infinities and out-of-range integers.

    ``st.integers()`` is unbounded, so this covers the values that overflow the platform's
    ``fromtimestamp`` as well as the ones that do not.
    """
    assert isinstance(format_timestamp(value, tz, default=default), str)


@given(value=st.one_of(st.floats(), st.integers()), tz=_TZ_STRATEGY)
def test_property_format_timestamp_agrees_with_to_tz(value: float, tz: timezone | None) -> None:
    """The epoch path and the datetime path must not diverge: one is defined in terms of the other.

    Whenever the epoch is representable, formatting it must equal formatting the datetime it
    denotes — otherwise a caller holding a timestamp and a caller holding a datetime for the same
    instant would print different things.
    """
    try:
        equivalent = datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        assert format_timestamp(value, tz, default="\x00sentinel") == "\x00sentinel"
        return
    assert format_timestamp(value, tz) == format_timestamp(equivalent, tz)


@given(default=st.text(max_size=20))
def test_property_none_always_renders_as_default_whatever_it_is(default: str) -> None:
    """Including empty and unicode — the sentinel is returned verbatim, never formatted."""
    assert format_timestamp(None, default=default) == default


@given(fmt=st.text(max_size=200).filter(lambda s: "%" not in s))
def test_property_a_format_with_no_directive_passes_through_verbatim(fmt: str) -> None:
    """G11: with no ``%`` the tokenizer loop never fires, so this is only the final append.

    Generated over arbitrary text — including NUL, control characters, and non-BMP code points —
    rather than the handful of hand-picked literals in G3/G4/G10, so an off-by-one that drops or
    duplicates a trailing slice would show up regardless of which characters happen to be there.
    """
    assert format_timestamp(datetime(2026, 1, 15, 12, 0), UTC, fmt=fmt) == fmt
