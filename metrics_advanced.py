"""Advanced risk and performance metrics for fund price data.

This is a self-contained companion module to ``analyze_polish_funds.py``.
It follows the same conventions used there:

* Price data is a :class:`pandas.DataFrame` with a ``Close`` column (prices)
  and a ``Date`` column (timestamps).
* Daily returns are computed with ``df["Close"].pct_change().dropna()``.
* The trading calendar uses ``TRADING_DAYS_PER_YEAR = 252`` and the default
  annual risk-free rate is ``RISK_FREE_RATE = 0.05``.

Every metric guards against missing/empty input and zero-division, and
returns ``Optional[float]`` (``None`` when there is not enough data), except
:func:`rolling_sharpe`, which returns a (possibly empty) :class:`pandas.Series`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Match the constants used in analyze_polish_funds.py.
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.05


def _daily_returns(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    """Return cleaned daily returns from a price DataFrame, or ``None``.

    Mirrors the project convention ``df["Close"].pct_change().dropna()`` while
    additionally guarding against ``None``/empty inputs and a missing
    ``Close`` column. Infinite values (e.g. from a zero price) are dropped.

    Args:
        df: Price DataFrame with a ``Close`` column.

    Returns:
        A :class:`pandas.Series` of daily returns, or ``None`` if the input is
        unusable.
    """
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return None
    returns = df["Close"].pct_change().dropna()
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return None
    return returns


def _aligned_returns(
    df: pd.DataFrame, benchmark_df: pd.DataFrame
) -> Optional[pd.DataFrame]:
    """Align fund and benchmark returns on a normalized ``Date`` column.

    Returns are computed per frame, attached to their (date-normalized)
    ``Date`` column, and inner-merged so that only overlapping dates remain.

    Args:
        df: Fund price DataFrame with ``Close`` and ``Date`` columns.
        benchmark_df: Benchmark price DataFrame with ``Close`` and ``Date``.

    Returns:
        A DataFrame with columns ``fund`` and ``bench`` (aligned returns), or
        ``None`` if either input is unusable or lacks a ``Date`` column.
    """
    if df is None or benchmark_df is None:
        return None
    if "Date" not in df.columns or "Date" not in benchmark_df.columns:
        return None

    fund_returns = _daily_returns(df)
    bench_returns = _daily_returns(benchmark_df)
    if fund_returns is None or bench_returns is None:
        return None

    # pct_change drops the first row; align the Date column accordingly.
    fund = pd.DataFrame(
        {
            "Date": pd.to_datetime(df["Date"]).dt.normalize().iloc[1:].values,
            "fund": fund_returns.values,
        }
    )
    bench = pd.DataFrame(
        {
            "Date": pd.to_datetime(benchmark_df["Date"])
            .dt.normalize()
            .iloc[1:]
            .values,
            "bench": bench_returns.values,
        }
    )
    merged = pd.merge(fund, bench, on="Date", how="inner")
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["fund", "bench"]
    )
    if merged.empty:
        return None
    return merged


def treynor_ratio(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    risk_free_rate: float = RISK_FREE_RATE,
) -> Optional[float]:
    """Compute the Treynor ratio: (annualized return - rf) / beta.

    Beta is ``cov(fund_excess, bench_excess) / var(bench_excess)`` computed on
    returns aligned by the normalized ``Date`` column (inner merge). The fund
    return is annualized arithmetically (``mean * 252``). Excess returns are
    measured against the per-period risk-free rate.

    At least 60 overlapping days are required.

    Args:
        df: Fund price DataFrame with ``Close`` and ``Date`` columns.
        benchmark_df: Benchmark price DataFrame with ``Close`` and ``Date``.
        risk_free_rate: Annual risk-free rate (default ``RISK_FREE_RATE``).

    Returns:
        The Treynor ratio, or ``None`` if there is insufficient overlap
        (< 60 days) or beta is zero.
    """
    merged = _aligned_returns(df, benchmark_df)
    if merged is None or len(merged) < 60:
        return None

    rf_period = risk_free_rate / TRADING_DAYS_PER_YEAR
    fund_excess = merged["fund"] - rf_period
    bench_excess = merged["bench"] - rf_period

    bench_var = float(np.var(bench_excess.values, ddof=1))
    if bench_var == 0:
        return None
    covariance = float(np.cov(fund_excess.values, bench_excess.values, ddof=1)[0, 1])
    beta = covariance / bench_var
    if beta == 0:
        return None

    annualized_return = float(merged["fund"].mean()) * TRADING_DAYS_PER_YEAR
    return (annualized_return - risk_free_rate) / beta


def omega_ratio(df: pd.DataFrame, threshold: float = 0.0) -> Optional[float]:
    """Compute the Omega ratio relative to a per-period return ``threshold``.

    Omega is the sum of returns above ``threshold`` divided by the absolute
    sum of returns below ``threshold`` (probability-weighted gains over
    losses, relative to the threshold).

    At least 30 returns are required.

    Args:
        df: Price DataFrame with a ``Close`` column.
        threshold: Per-period return threshold (default ``0.0``).

    Returns:
        The Omega ratio, or ``None`` if there is insufficient data (< 30
        returns) or there are no returns below the threshold.
    """
    returns = _daily_returns(df)
    if returns is None or len(returns) < 30:
        return None

    excess = returns - threshold
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()  # positive magnitude of losses
    if losses == 0:
        return None
    return float(gains / losses)


def ulcer_index(df: pd.DataFrame) -> Optional[float]:
    """Compute the Ulcer Index: depth and duration of drawdowns.

    Drawdown at each point is the percent decline from the running maximum
    price. The Ulcer Index is ``sqrt(mean(drawdown_pct ** 2))`` and is a
    measure of downside volatility that penalizes deep, prolonged declines.

    Args:
        df: Price DataFrame with a ``Close`` column.

    Returns:
        The Ulcer Index (>= 0), or ``None`` if the input is unusable.
    """
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return None

    prices = df["Close"].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(prices) < 2:
        return None

    running_max = prices.cummax()
    # Guard against zero/negative running max prices.
    valid = running_max > 0
    if not valid.any():
        return None

    drawdown_pct = pd.Series(0.0, index=prices.index)
    drawdown_pct[valid] = (
        (prices[valid] - running_max[valid]) / running_max[valid]
    ) * 100.0
    return float(np.sqrt(np.mean(np.square(drawdown_pct.values))))


def rolling_sharpe(
    df: pd.DataFrame,
    window: int = 63,
    risk_free_rate: float = RISK_FREE_RATE,
) -> pd.Series:
    """Compute an annualized rolling Sharpe ratio over ``window`` periods.

    For each window the Sharpe ratio is ``mean / std * sqrt(252)`` of excess
    returns (the per-period risk-free rate is subtracted from each return).

    Args:
        df: Price DataFrame with a ``Close`` column.
        window: Rolling window length in trading days (default ``63``).
        risk_free_rate: Annual risk-free rate (default ``RISK_FREE_RATE``).

    Returns:
        A :class:`pandas.Series` of annualized rolling Sharpe values, indexed
        like the underlying returns. An empty Series is returned when there is
        insufficient data (fewer than ``window`` returns) or invalid input.
    """
    if window is None or window < 2:
        return pd.Series(dtype=float)

    returns = _daily_returns(df)
    if returns is None or len(returns) < window:
        return pd.Series(dtype=float)

    rf_period = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = returns - rf_period

    roll_mean = excess.rolling(window).mean()
    roll_std = excess.rolling(window).std(ddof=1)

    sharpe = (roll_mean / roll_std) * np.sqrt(TRADING_DAYS_PER_YEAR)
    # Where std is zero the division yields inf/NaN; clean those up.
    sharpe = sharpe.replace([np.inf, -np.inf], np.nan).dropna()
    return sharpe


def gain_to_pain_ratio(df: pd.DataFrame) -> Optional[float]:
    """Compute the Gain-to-Pain ratio: sum of returns over total losses.

    Defined as ``sum(returns) / abs(sum(negative returns))`` -- total net
    return per unit of cumulative downside ("pain").

    Args:
        df: Price DataFrame with a ``Close`` column.

    Returns:
        The Gain-to-Pain ratio, or ``None`` if there is insufficient data or
        no negative returns.
    """
    returns = _daily_returns(df)
    if returns is None or returns.empty:
        return None

    negative_sum = returns[returns < 0].sum()
    pain = abs(negative_sum)
    if pain == 0:
        return None
    return float(returns.sum() / pain)
