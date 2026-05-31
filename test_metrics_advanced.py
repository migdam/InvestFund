"""Runnable test suite for ``metrics_advanced.py``.

Plain-python harness: prints ``PASS``/``FAIL`` lines and exits with status
0 (all passed) or 1 (any failure). Mock price data is generated locally with
numpy/pandas (a seeded geometric random walk) -- no network access.

Run with::

    python test_metrics_advanced.py
"""

from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

import metrics_advanced as ma


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------
def make_prices(
    n: int = 300,
    seed: int = 42,
    drift: float = 0.0005,
    vol: float = 0.01,
    start: float = 100.0,
) -> pd.DataFrame:
    """Build a seeded geometric-random-walk price DataFrame.

    Returns a DataFrame with ``Date`` (business days) and ``Close`` columns.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.normal(loc=drift, scale=vol, size=n)
    close = start * np.exp(np.cumsum(shocks))
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({"Date": dates, "Close": close})


def make_correlated_benchmark(
    base: pd.DataFrame, seed: int = 7, noise: float = 0.004
) -> pd.DataFrame:
    """Build a benchmark whose returns are correlated with ``base``.

    The benchmark shares ``base``'s dates and is the base price path plus a
    small amount of seeded noise, ensuring a meaningful (non-zero) beta.
    """
    rng = np.random.default_rng(seed)
    base_returns = base["Close"].pct_change().fillna(0.0).values
    bench_returns = base_returns * 0.8 + rng.normal(0.0, noise, size=len(base))
    close = 100.0 * np.exp(np.cumsum(bench_returns))
    return pd.DataFrame({"Date": base["Date"].values, "Close": close})


# ---------------------------------------------------------------------------
# Tiny assertion harness
# ---------------------------------------------------------------------------
_failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _failures
    if condition:
        print(f"PASS: {name}")
    else:
        _failures += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"FAIL: {name}{suffix}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_treynor_finite() -> None:
    fund = make_prices(n=300, seed=42, drift=0.0006)
    bench = make_correlated_benchmark(fund)
    result = ma.treynor_ratio(fund, bench)
    check(
        "treynor_ratio is finite for correlated benchmark",
        result is not None and math.isfinite(result),
        detail=f"got {result!r}",
    )


def test_treynor_insufficient_overlap() -> None:
    fund = make_prices(n=300, seed=42)
    # Benchmark dates do not overlap the fund's dates at all.
    bench = make_prices(n=300, seed=99)
    bench = bench.copy()
    bench["Date"] = pd.date_range("2050-01-01", periods=len(bench), freq="B")
    result = ma.treynor_ratio(fund, bench)
    check(
        "treynor_ratio returns None on insufficient overlap",
        result is None,
        detail=f"got {result!r}",
    )

    # Also: short but overlapping series (< 60 days) -> None.
    short_fund = make_prices(n=40, seed=1)
    short_bench = make_correlated_benchmark(short_fund)
    result_short = ma.treynor_ratio(short_fund, short_bench)
    check(
        "treynor_ratio returns None when < 60 overlapping days",
        result_short is None,
        detail=f"got {result_short!r}",
    )


def test_omega_upward() -> None:
    fund = make_prices(n=300, seed=3, drift=0.0015, vol=0.008)
    result = ma.omega_ratio(fund, threshold=0.0)
    check(
        "omega_ratio > 1 for upward-drifting series",
        result is not None and result > 1.0,
        detail=f"got {result!r}",
    )


def test_omega_no_downside() -> None:
    # Strictly increasing prices => every return is positive => no losses.
    dates = pd.date_range("2021-01-01", periods=60, freq="B")
    close = np.linspace(100.0, 200.0, 60)
    df = pd.DataFrame({"Date": dates, "Close": close})
    result = ma.omega_ratio(df, threshold=0.0)
    check(
        "omega_ratio returns None when there is no downside",
        result is None,
        detail=f"got {result!r}",
    )


def test_ulcer_nonnegative() -> None:
    fund = make_prices(n=300, seed=5)
    result = ma.ulcer_index(fund)
    check(
        "ulcer_index is non-negative",
        result is not None and result >= 0.0,
        detail=f"got {result!r}",
    )

    # A monotonically rising series has no drawdown => Ulcer Index ~ 0.
    dates = pd.date_range("2021-01-01", periods=60, freq="B")
    rising = pd.DataFrame(
        {"Date": dates, "Close": np.linspace(100.0, 200.0, 60)}
    )
    rising_ui = ma.ulcer_index(rising)
    check(
        "ulcer_index ~0 for monotonically rising prices",
        rising_ui is not None and abs(rising_ui) < 1e-9,
        detail=f"got {rising_ui!r}",
    )


def test_rolling_sharpe_length() -> None:
    n = 300
    window = 63
    fund = make_prices(n=n, seed=8)
    series = ma.rolling_sharpe(fund, window=window)
    # Returns has n-1 elements; rolling(window) yields (n-1)-window+1 valid.
    expected = (n - 1) - window + 1
    check(
        "rolling_sharpe returns a pandas Series",
        isinstance(series, pd.Series),
        detail=f"got {type(series)!r}",
    )
    check(
        "rolling_sharpe non-empty with expected length for sufficient data",
        len(series) == expected and len(series) > 0,
        detail=f"got len {len(series)}, expected {expected}",
    )
    check(
        "rolling_sharpe values are finite",
        bool(np.isfinite(series.values).all()),
        detail="found non-finite values",
    )


def test_rolling_sharpe_short() -> None:
    short = make_prices(n=20, seed=11)
    series = ma.rolling_sharpe(short, window=63)
    check(
        "rolling_sharpe returns empty Series for short data",
        isinstance(series, pd.Series) and series.empty,
        detail=f"got len {len(series)}",
    )


def test_gain_to_pain_sign() -> None:
    up = make_prices(n=300, seed=13, drift=0.0015, vol=0.008)
    down = make_prices(n=300, seed=13, drift=-0.0015, vol=0.008)
    up_gtp = ma.gain_to_pain_ratio(up)
    down_gtp = ma.gain_to_pain_ratio(down)
    check(
        "gain_to_pain positive for upward-drifting series",
        up_gtp is not None and up_gtp > 0,
        detail=f"got {up_gtp!r}",
    )
    check(
        "gain_to_pain negative for downward-drifting series",
        down_gtp is not None and down_gtp < 0,
        detail=f"got {down_gtp!r}",
    )

    # No negative returns => None.
    dates = pd.date_range("2021-01-01", periods=60, freq="B")
    rising = pd.DataFrame(
        {"Date": dates, "Close": np.linspace(100.0, 200.0, 60)}
    )
    check(
        "gain_to_pain returns None when no negative returns",
        ma.gain_to_pain_ratio(rising) is None,
    )


def test_none_and_empty_inputs() -> None:
    empty = pd.DataFrame({"Date": [], "Close": []})
    check("treynor_ratio handles None", ma.treynor_ratio(None, None) is None)
    check("omega_ratio handles None", ma.omega_ratio(None) is None)
    check("omega_ratio handles empty", ma.omega_ratio(empty) is None)
    check("ulcer_index handles None", ma.ulcer_index(None) is None)
    check("gain_to_pain handles None", ma.gain_to_pain_ratio(None) is None)
    check(
        "rolling_sharpe handles None",
        isinstance(ma.rolling_sharpe(None), pd.Series)
        and ma.rolling_sharpe(None).empty,
    )


def main() -> int:
    test_treynor_finite()
    test_treynor_insufficient_overlap()
    test_omega_upward()
    test_omega_no_downside()
    test_ulcer_nonnegative()
    test_rolling_sharpe_length()
    test_rolling_sharpe_short()
    test_gain_to_pain_sign()
    test_none_and_empty_inputs()

    print("-" * 50)
    if _failures == 0:
        print("ALL TESTS PASSED")
        return 0
    print(f"{_failures} TEST(S) FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
