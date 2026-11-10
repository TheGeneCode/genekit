"""Capped exponential backoff: the delay before the next retry of a caller-owned loop.

The decision this module encodes: the delay is ``base * 2**failures`` seconds, capped, and the
policy around that one line is what is worth sharing. The recurring defects it exists to prevent
are the ordinary one-line versions — ``min(base * 2**n, cap)`` — which raise :exc:`OverflowError`
the moment a float ``base`` meets a failure counter of 1024 or more (a counter read back from a
database row or a state file is unbounded), build an enormous :class:`int` when ``base`` is an int
and the counter is huge, and quietly return *half* of ``base`` for a ``-1`` that crept in from an
off-by-one at the call site.

The policy added on top of the arithmetic:

* failures are counted *zero-based*: the number of failures *before* the one just seen, so the
  first retry waits ``base`` and the next ``2 * base``. A caller that counts attempts from 1 maps
  with ``backoff_seconds(max(attempts - 1, 0), ...)``.
* the cap always wins, even when ``base`` is larger than ``cap``: a ``cap`` is a promise about the
  longest a caller will ever wait, so it is never exceeded to honour a ``base``.
* the exponent is clamped before it is used. Any positive finite float is below ``2**1024``, so a
  large enough exponent can only ever overflow into the cap; clamping changes no result, it only
  bounds the work and removes the :exc:`OverflowError`.
* invalid input raises. A negative counter, or a negative, NaN or infinite ``base`` or ``cap``,
  is a bug at the call site and is reported there rather than turned into a plausible-looking
  delay.

Nothing in the standard library does this. ``tenacity`` and ``backoff`` do, but they are
retry-controller frameworks and a hard third-party dependency, while every caller this module
replaces already owns its loop, its sleep and its logging and needs only the number. So this
module returns only the number. There is no jitter — callers that need it add it — and no
:class:`datetime.timedelta` twin: ``timedelta(seconds=backoff_seconds(...))`` is one expression.
"""

from __future__ import annotations

import math

__all__ = ["backoff_seconds"]

# Every positive finite float lies in [2**-1074, 2**1024), so 2**2100 times any positive base
# overflows: clamping the exponent here never changes a result, it only bounds the work.
_MAX_EXPONENT = 2100


def backoff_seconds(failures: int, *, base: float, cap: float) -> float:
    """Seconds to wait before the next attempt: base, 2*base, 4*base, ... never above cap.

    Args:
        failures: Failures so far, *before* the one just seen — 0 for the first retry.
            Any size is safe; past the cap the result is simply ``cap``.
        base: Delay for the first retry, in seconds. Finite, >= 0.
        cap: Upper bound for every delay, in seconds. Finite, >= 0. Wins over ``base``.

    Returns:
        ``min(base * 2**failures, cap)`` as a float.

    Raises:
        ValueError: ``failures`` is negative, or ``base`` / ``cap`` is negative, NaN or infinite.
        TypeError: ``failures`` is not an int.

    Examples:
        >>> from genekit.backoff import backoff_seconds
        >>> [backoff_seconds(n, base=0.5, cap=2.0) for n in range(4)]
        [0.5, 1.0, 2.0, 2.0]
        >>> backoff_seconds(10**12, base=5, cap=900)
        900.0
        >>> backoff_seconds(0, base=5.0, cap=2.0)
        2.0
    """
    if failures < 0:
        raise ValueError(f"failures must be >= 0, got {failures!r}")
    for name, value in (("base", base), ("cap", cap)):
        try:
            valid = math.isfinite(value) and value >= 0
        except OverflowError:  # an int too large for a float is not a usable number of seconds
            valid = False
        if not valid:
            raise ValueError(f"{name} must be finite and >= 0, got {value!r}")
    try:
        delay = math.ldexp(base, min(failures, _MAX_EXPONENT))
    except OverflowError:
        return float(cap)
    return min(delay, float(cap))
