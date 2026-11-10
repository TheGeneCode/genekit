"""Tests for genekit.backoff.

Boundary Matrix
===============

Dimension A — happy path
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| A1   | base 0.5, cap 2.0, failures 0..4      | [0.5, 1.0, 2.0, 2.0, 2.0]         |
| A2   | failures 0                            | base                              |
| A3   | base above cap                        | cap                               |
| A4   | base 0                                | 0.0 at any failure count          |
| A5   | cap 0                                 | 0.0 at any failure count          |

Dimension B — validation
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| B1   | failures -1                           | ValueError                        |
| B2   | base or cap in -1, nan, inf, -inf     | ValueError naming the argument    |

Dimension C — overflow / huge counts
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| C1   | failures 1023, 1024, 2100, 10**18, 10**100 | cap, no OverflowError        |
| C2   | subnormal base, huge cap, 10**6       | reaches the cap exactly           |

Dimension D — types
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| D1   | failures None                         | TypeError                         |
| D2   | failures 2.0                          | TypeError                         |
| D3   | int base and cap                      | float result, below and past cap  |

Dimension E — properties (hypothesis)
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| E1   | any valid input                       | 0 <= result <= cap                |
| E2   | failures n vs n + 1                   | non-decreasing                    |
| E3   | below the cap                         | exact doubling                    |
| E4   | result equals cap                     | every later count equals cap      |
| E5   | counts where the naive formula works  | equals min(base * 2**n, cap)      |
| E6   | failures 10**18                       | cap, or 0.0 when base is 0        |

Dimension F — documentation
------------------------------------------------------------------
| Cell | Case                                  | Expected                          |
|------|---------------------------------------|-----------------------------------|
| F1   | doctest.testmod on the module         | examples ran, none failed         |

Concurrency — N/A: pure, stateless function, no shared state to race.
"""

from __future__ import annotations

import doctest
import math
import sys

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from genekit import backoff
from genekit.backoff import backoff_seconds

_FINITE = st.floats(min_value=0.0, allow_nan=False, allow_infinity=False)
_SMALL = st.floats(min_value=0.0, max_value=1e6, allow_nan=False)
_N = st.integers(min_value=0, max_value=2200)


# --- A: happy path ---------------------------------------------------------------------------


@pytest.mark.parametrize(("n", "expected"), [(0, 0.5), (1, 1.0), (2, 2.0), (3, 2.0), (4, 2.0)])
def test_ladder_doubles_then_holds_at_cap(n: int, expected: float) -> None:
    assert backoff_seconds(n, base=0.5, cap=2.0) == expected


def test_first_retry_waits_base() -> None:
    assert backoff_seconds(0, base=5.0, cap=900.0) == 5.0


def test_base_above_cap_returns_cap() -> None:
    assert backoff_seconds(0, base=5.0, cap=2.0) == 2.0


@pytest.mark.parametrize("n", [0, 1, 10**12])
def test_zero_base_is_always_zero(n: int) -> None:
    assert backoff_seconds(n, base=0.0, cap=900.0) == 0.0


@pytest.mark.parametrize("n", [0, 3])
def test_zero_cap_is_always_zero(n: int) -> None:
    assert backoff_seconds(n, base=5.0, cap=0.0) == 0.0


# --- B: validation ---------------------------------------------------------------------------


def test_negative_failures_rejected() -> None:
    with pytest.raises(ValueError, match="failures"):
        backoff_seconds(-1, base=5.0, cap=900.0)


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf, -math.inf])
def test_invalid_base_or_cap_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="base"):
        backoff_seconds(0, base=bad, cap=900.0)
    with pytest.raises(ValueError, match="cap"):
        backoff_seconds(0, base=5.0, cap=bad)


@pytest.mark.parametrize("huge", [10**400, -(10**400)])
def test_int_too_large_for_float_rejected_as_value_error(huge: int) -> None:
    with pytest.raises(ValueError, match="base"):
        backoff_seconds(1, base=huge, cap=900.0)
    with pytest.raises(ValueError, match="cap"):
        backoff_seconds(1, base=5.0, cap=huge)


# --- C: overflow / huge counts ---------------------------------------------------------------


@pytest.mark.parametrize("n", [1023, 1024, 2100, 10**18, 10**100])
def test_huge_failures_returns_cap_without_overflow(n: int) -> None:
    assert backoff_seconds(n, base=5.0, cap=900.0) == 900.0


def test_subnormal_base_still_reaches_max_cap() -> None:
    cap = sys.float_info.max
    assert backoff_seconds(10**6, base=5e-324, cap=cap) == cap


@pytest.mark.parametrize(
    ("base", "last_finite"),
    [(1.0, 1023), (5e-324, 2097)],
)
def test_exact_overflow_edge_is_power_of_two_then_cap(base: float, last_finite: int) -> None:
    cap = sys.float_info.max
    exact = math.ldexp(base, last_finite)
    assert exact < cap
    assert backoff_seconds(last_finite, base=base, cap=cap) == exact
    assert backoff_seconds(last_finite + 1, base=base, cap=cap) == cap


# --- D: types --------------------------------------------------------------------------------


def test_none_failures_raises_type_error() -> None:
    with pytest.raises(TypeError):
        backoff_seconds(None, base=5.0, cap=900.0)  # pyright: ignore[reportArgumentType]


def test_float_failures_raises_type_error() -> None:
    with pytest.raises(TypeError):
        backoff_seconds(2.0, base=5.0, cap=900.0)  # pyright: ignore[reportArgumentType]


def test_int_arguments_return_float() -> None:
    below = backoff_seconds(2, base=300, cap=21600)
    assert below == 1200.0
    assert type(below) is float
    past = backoff_seconds(10**6, base=300, cap=21600)
    assert past == 21600.0
    assert type(past) is float


# --- E: properties ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(n=_N, base=_FINITE, cap=_FINITE)
def test_property_bounded_by_zero_and_cap(n: int, base: float, cap: float) -> None:
    assert 0.0 <= backoff_seconds(n, base=base, cap=cap) <= cap


@settings(max_examples=200)
@given(n=_N, base=_FINITE, cap=_FINITE)
def test_property_monotone_in_failures(n: int, base: float, cap: float) -> None:
    assert backoff_seconds(n, base=base, cap=cap) <= backoff_seconds(n + 1, base=base, cap=cap)


@settings(max_examples=200)
@given(n=_N, base=_FINITE, cap=_FINITE)
def test_property_exact_doubling_below_cap(n: int, base: float, cap: float) -> None:
    current = backoff_seconds(n, base=base, cap=cap)
    assume(math.isfinite(2 * current) and 2 * current <= cap)
    assert backoff_seconds(n + 1, base=base, cap=cap) == 2 * current


@settings(max_examples=200)
@given(n=_N, k=st.integers(0, 10**6), base=_FINITE, cap=_FINITE)
def test_property_cap_is_absorbing(n: int, k: int, base: float, cap: float) -> None:
    assume(backoff_seconds(n, base=base, cap=cap) == cap)
    assert backoff_seconds(n + k, base=base, cap=cap) == cap


@settings(max_examples=200)
@given(n=st.integers(0, 1000), base=_SMALL, cap=_SMALL)
def test_property_matches_naive_formula_where_it_works(n: int, base: float, cap: float) -> None:
    assert backoff_seconds(n, base=base, cap=cap) == min(base * 2**n, cap)


@settings(max_examples=200)
@given(base=_FINITE, cap=_FINITE)
def test_property_huge_count_hits_cap_unless_base_zero(base: float, cap: float) -> None:
    expected = cap if base > 0 else 0.0
    assert backoff_seconds(10**18, base=base, cap=cap) == expected


# --- F: documentation ------------------------------------------------------------------------


def test_docstring_examples_run() -> None:
    result = doctest.testmod(backoff)
    assert result.failed == 0
    assert result.attempted > 0
