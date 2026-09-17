"""Timezone-aware conversion and display: the instant a thing happened, the day a person saw it.

The decision this module encodes: *the instant* and *the calendar day shown to a person* are
different facts, and the conversion between them is explicit, injectable, and cannot be skipped by
accident. The recurring defect it exists to prevent is code that is correct about the instant
(epoch, UTC) but wrong about the date on screen, because the conversion to a local zone was left out
or frozen at the wrong moment — which surfaces as a displayed date a day off for anything
timestamped near midnight local.

The standard library already does the hard parts and this module does not reimplement them:
:class:`zoneinfo.ZoneInfo` owns the tz database and DST arithmetic, and
:meth:`datetime.datetime.astimezone` owns the conversion. What is added is the policy the stdlib
deliberately has none of:

* an unresolvable zone *name* is user input, not a crash (:func:`resolve_tz`);
* a naive datetime means UTC, not system local (:func:`to_tz`);
* a missing or unrepresentable instant renders as a placeholder, not an exception
  (:func:`format_timestamp`).

CPython does not ship the IANA tz database on Windows. Without it every :class:`~zoneinfo.ZoneInfo`
lookup fails — including ``"UTC"`` — so install the ``genekit[tzdata]`` extra to get one. Without
the extra, :func:`resolve_tz` logs a warning and degrades to the system local zone rather than
raising.
"""

import logging
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["DEFAULT_FORMAT", "format_timestamp", "local_tz", "resolve_tz", "to_tz"]

_log = logging.getLogger(__name__)

DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Sortable, locale-independent display format, matching ``genekit.logging.VERBOSE_DATEFMT``.

Append ``" %Z"`` to show the zone abbreviation (``MST``/``MDT``). ``%Z`` only renders a real
abbreviation for a :class:`~zoneinfo.ZoneInfo`; on the fixed offset returned by :func:`local_tz` it
renders the platform's long zone name instead.
"""

# ZoneInfo's failure surface is wider than its own exception: an unknown key raises
# ZoneInfoNotFoundError (a KeyError), a key that is not a normalized relative path raises ValueError
# (e.g. "" or "../etc/passwd"), a non-string raises TypeError, and a key long enough to blow the
# platform's filename limit raises OSError from the tz-database lookup itself. A fallback policy
# that catches only the documented exception still crashes on the inputs most likely to arrive from
# a config file.
_LOOKUP_ERRORS = (KeyError, ValueError, TypeError, OSError)


def local_tz() -> tzinfo:
    """Return the system local zone as a real :class:`~datetime.tzinfo`, never ``None``.

    The stdlib has no ``zoneinfo.localzone()``; the incantation is
    ``datetime.now(timezone.utc).astimezone().tzinfo``. This exists because a zone sometimes has to
    be *passed* somewhere — a scheduler, a formatter under test — where letting
    :meth:`~datetime.datetime.astimezone` infer it is not an option.

    **This is a fixed-offset snapshot of the offset in effect right now, not a DST-aware zone.**
    Converting an instant from the other side of a DST boundary through it yields the wrong wall
    clock. For converting, call :func:`to_tz` with ``tz=None`` — it defers to the stdlib, which
    recomputes the local offset per instant. For future-dated scheduling, pass an explicit IANA name
    instead, so the job does not drift when the offset changes.

    Returns:
        The system local zone as a fixed-offset :class:`~datetime.timezone`, or
        :data:`~datetime.timezone.utc` on the platforms where the offset cannot be determined.

    Example:
        >>> from genekit.tz import local_tz
        >>> from datetime import datetime
        >>> isinstance(datetime.now(local_tz()), datetime)
        True
    """
    snapshot = datetime.now(timezone.utc).astimezone().tzinfo
    if snapshot is None:  # pragma: no cover - astimezone() always attaches a fixed offset
        return timezone.utc
    return snapshot


def resolve_tz(
    name: str | tzinfo | None,
    *,
    fallback: tzinfo | None = None,
    strict: bool = False,
) -> tzinfo:
    """Resolve a zone name to a :class:`~datetime.tzinfo`, degrading instead of raising.

    A zone name normally arrives from configuration, which makes it user input: a typo, a wrong
    case (``"america/chicago"``), or a host with no tz database should not take an application down
    over a display detail. The default policy is to log a warning and fall back. Pass
    ``strict=True`` where a wrong zone is a deployment error worth failing on.

    An already-resolved :class:`~datetime.tzinfo` passes through untouched, so a caller can accept
    ``str | tzinfo | None`` from its own config and normalize in one place.

    Args:
        name: An IANA zone name (``"America/Denver"``), an existing :class:`~datetime.tzinfo` to
            pass through, or ``None``/empty/whitespace-only to request the fallback.
        fallback: Zone to use when ``name`` is empty or unresolvable. Defaults to ``None``, meaning
            the system local zone from :func:`local_tz`. ``fallback=timezone.utc`` is the usual
            choice for a service that would rather be predictably wrong than locally wrong.
        strict: When ``True``, an unresolvable ``name`` raises instead of falling back. An empty or
            ``None`` name still returns the fallback — that is a request, not a failure.

    Returns:
        A :class:`~datetime.tzinfo`. Never ``None``.

    Raises:
        ZoneInfoNotFoundError: Only when ``strict=True`` and ``name`` cannot be resolved. Every
            underlying failure — unknown key, malformed key, wrong type, missing tz database — is
            reported as this one type so callers have a single thing to catch.

    Example:
        >>> from datetime import timezone
        >>> from genekit.tz import resolve_tz
        >>> resolve_tz("this is not a zone", fallback=timezone.utc)
        datetime.timezone.utc
        >>> resolve_tz(None, fallback=timezone.utc)
        datetime.timezone.utc
        >>> resolve_tz(timezone.utc)
        datetime.timezone.utc
    """
    if isinstance(name, tzinfo):
        return name
    default = local_tz() if fallback is None else fallback
    if not isinstance(name, str) or not name.strip():
        if name is not None and not isinstance(name, str):
            if strict:
                raise ZoneInfoNotFoundError(f"cannot resolve timezone from {name!r}")
            _log.warning("Unusable timezone %r; falling back to %s", name, default)
        return default
    try:
        return ZoneInfo(name.strip())
    except _LOOKUP_ERRORS as exc:
        if strict:
            raise ZoneInfoNotFoundError(f"unknown timezone {name!r}: {exc}") from exc
        _log.warning("Unknown timezone %r; falling back to %s", name, default)
        return default


def to_tz(
    value: datetime,
    tz: str | tzinfo | None = None,
    *,
    assume: tzinfo | None = timezone.utc,
) -> datetime:
    """Convert a datetime into ``tz``, making an explicit decision about naive input.

    :meth:`~datetime.datetime.astimezone` silently treats a naive datetime as *system local*. That
    is the wrong guess for the most common source of naive datetimes — a timestamp stored as naive
    UTC — and it is wrong in a way that only shows up on machines outside UTC. This attaches
    ``assume`` first, so the interpretation is written down rather than inherited from the host.

    Args:
        value: The datetime to convert. Aware values are converted; naive values are first stamped
            with ``assume``.
        tz: Target zone, resolved through :func:`resolve_tz`. ``None`` means the system local zone
            and defers to the stdlib's per-instant offset lookup — which is why ``None`` is not the
            same as passing :func:`local_tz`, whose offset is frozen at the current moment.
        assume: Zone a naive ``value`` is taken to be in. Defaults to UTC. Pass ``assume=None`` to
            restore the stdlib's behaviour of treating naive input as system local.

    Returns:
        An aware datetime denoting the same instant as ``value``, with ``tzinfo`` set to ``tz``.

    Note:
        With ``tz=None`` the per-instant lookup goes through the C library, which on Windows cannot
        answer for instants before 1970 and raises ``OSError``. Rather than make the function
        non-portable for historical data, that case warns and degrades to :func:`local_tz`'s frozen
        offset — the same degrade-and-say-so policy :func:`resolve_tz` applies. The instant is still
        preserved; only the offset may be the wrong one for that date. Pass an explicit IANA zone
        for historical instants and the platform is out of the loop entirely.

        That degradation covers the *platform* limit only. Within roughly one UTC offset of
        :attr:`datetime.datetime.min` or :attr:`~datetime.datetime.max` the converted result has
        nowhere to land, and ``OverflowError`` is raised exactly as it is for an explicit ``tz`` —
        the range of :class:`~datetime.datetime` is not something a fallback can paper over.

    Raises:
        AttributeError: If ``value`` is not a :class:`~datetime.datetime`.
        OverflowError: If the converted result falls outside :class:`~datetime.datetime`'s range.
        ZoneInfoNotFoundError: Never from here; see :func:`resolve_tz` for the strict-mode case.

    Example:
        >>> from datetime import datetime, timezone
        >>> from genekit.tz import to_tz
        >>> naive = datetime(2026, 1, 15, 12, 0)
        >>> to_tz(naive, timezone.utc)
        datetime.datetime(2026, 1, 15, 12, 0, tzinfo=datetime.timezone.utc)
        >>> to_tz(naive, timezone.utc).timestamp() == naive.replace(tzinfo=timezone.utc).timestamp()
        True
    """
    if value.tzinfo is None:
        if assume is not None:
            value = value.replace(tzinfo=assume)
        else:
            # Naive means system local. That is the same platform lookup ``tz=None`` performs, so
            # doing it here and again below would warn twice for one call on the degrade path.
            value = _as_system_local(value)
            if tz is None:
                return value
    if tz is None:
        return _as_system_local(value)
    return value.astimezone(resolve_tz(tz))


def _as_system_local(value: datetime) -> datetime:
    """Attach or convert to the system local zone, degrading when the platform cannot say.

    Both the naive and the aware case route through :meth:`~datetime.datetime.astimezone`, whose
    no-argument form asks the C library for the offset in effect at that instant. Windows cannot
    answer for instants before 1970 and raises ``OSError``; the frozen offset from :func:`local_tz`
    is then the only answer available, and saying so beats propagating a platform error out of a
    display path.

    Args:
        value: Naive (interpreted as system local) or aware datetime.

    Returns:
        An aware datetime in the system local zone, denoting the same instant as ``value``.

    Raises:
        OverflowError: If the shifted result leaves :class:`~datetime.datetime`'s range. The
            fallback covers a platform that cannot answer, not a result with nowhere to land.

    Example:
        >>> from datetime import datetime, timezone
        >>> from genekit.tz import _as_system_local
        >>> _as_system_local(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)).tzinfo is not None
        True
    """
    try:
        return value.astimezone()
    except OSError:
        snapshot = local_tz()
        _log.warning(
            "This platform cannot report the local offset for %s; using the current offset (%s) "
            "instead. Pass an explicit timezone for historical instants.",
            value,
            snapshot,
        )
        if value.tzinfo is None:
            return value.replace(tzinfo=snapshot)
        return value.astimezone(snapshot)


def format_timestamp(
    value: datetime | float | None,
    tz: str | tzinfo | None = None,
    *,
    fmt: str = DEFAULT_FORMAT,
    assume: tzinfo | None = timezone.utc,
    default: str = "",
) -> str:
    """Render an instant as a display string, always via an explicit zone conversion.

    This is the composition that has to happen together every time and is easy to half-do: an epoch
    or UTC datetime is converted into the zone a person reads, and only then formatted. Formatting
    before converting produces the UTC calendar day, which is a day ahead of the reader's for
    anything late in their evening.

    Missing and unrepresentable instants render as ``default`` rather than raising, because a
    display string is not worth an exception. A value of the wrong *type* still raises — that is a
    caller bug, not an unknown value.

    Args:
        value: A :class:`~datetime.datetime`, a POSIX timestamp in seconds, or ``None``.
        tz: Zone to render in, resolved through :func:`resolve_tz`. ``None`` means system local, so
            the date shown is the reader's calendar day.
        fmt: :meth:`~datetime.datetime.strftime` format. Defaults to :data:`DEFAULT_FORMAT`.
        assume: Zone a naive ``value`` is taken to be in; see :func:`to_tz`. Epoch input is always
            UTC by definition and ignores this.
        default: Returned for ``None`` and for numbers outside the platform's representable range
            (including NaN). Defaults to ``""``; ``"(unknown)"`` is the usual choice for a table a
            person reads, where a blank cell reads as a bug.

    Returns:
        The formatted string, or ``default``.

    Raises:
        TypeError: If ``value`` is neither a datetime, a real number, nor ``None``. :class:`bool` is
            rejected too: ``True`` is never a meaningful instant.
        ValueError: If ``fmt`` is not a valid :meth:`~datetime.datetime.strftime` format. A bad
            format is a caller bug, not an unknown value, so it is not absorbed into ``default``.

    Example:
        >>> from datetime import datetime, timezone
        >>> from genekit.tz import format_timestamp
        >>> format_timestamp(0, timezone.utc)
        '1970-01-01 00:00:00'
        >>> format_timestamp(datetime(2026, 1, 15, 12, 0), timezone.utc, fmt="%Y-%m-%d")
        '2026-01-15'
        >>> format_timestamp(None, default="(unknown)")
        '(unknown)'
    """
    if value is None:
        return default
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"format_timestamp() expects a datetime, a POSIX timestamp, or None, got {value!r}"
        )
    else:
        try:
            moment = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return default
    try:
        moment = to_tz(moment, tz, assume=assume)
    except (OSError, OverflowError):
        return default
    # Deliberately unguarded: strftime raises ValueError only for a malformed ``fmt``, which is a
    # caller bug of the same kind as a wrong ``value`` type. Swallowing it into ``default`` would
    # turn a typo in a format string into a column that is silently blank forever.
    return moment.strftime(fmt)
