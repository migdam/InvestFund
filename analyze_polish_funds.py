"""
analyze_polish_funds.py
----------------------

Enhanced script for analyzing Polish investment funds from the Stooq financial portal.
This version includes advanced metrics, parallel processing, caching, and comprehensive
risk analysis.

Features:
- Risk-adjusted returns (Sharpe ratio, Sortino ratio)
- Volatility and drawdown analysis
- Parallel data downloads for improved performance
- Smart caching to reduce network requests
- Multiple export formats (CSV, Excel, JSON, HTML)
- Interactive visualizations
- Configurable recommendation engine
- Statistical analysis and percentile rankings

Background:
~~~~~~~~~~
On Stooq's web site each fund is identified by a ticker code such as ``1006.N``.
Historical data can be downloaded as CSV from ``https://stooq.pl/q/d/l/?s=1006.n&i=d``.
The main fund listing page at ``https://stooq.pl/t/`` presents all available funds.

This script is designed for informational and educational purposes only – it does not
constitute professional investment advice. You should consult a qualified financial
advisor before making any investment decisions.

Requirements:
============
pandas, requests, beautifulsoup4, numpy, scipy, matplotlib, seaborn, openpyxl, tqdm

Install with: pip install pandas requests beautifulsoup4 numpy scipy matplotlib seaborn openpyxl tqdm
"""

import argparse
import datetime
import json
import os
import pickle
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from io import StringIO

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from scipy import stats
from tqdm import tqdm

# Optional imports for visualization
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False
    warnings.warn("matplotlib/seaborn not available. Plotting features disabled.")


# Constants
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.05  # 5% annual risk-free rate (adjust as needed)
CACHE_DIR = Path(".fund_cache")
CACHE_EXPIRY_DAYS = 1  # Cache expires after 1 day


@dataclass
class FundInfo:
    """Container for fund meta information."""
    symbol: str
    name: str


@dataclass
class FundMetrics:
    """Container for all calculated fund metrics."""
    symbol: str
    name: str
    # Returns
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_6m: Optional[float] = None
    return_1y: Optional[float] = None
    return_ytd: Optional[float] = None
    # Risk metrics
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    calmar_ratio: Optional[float] = None
    # Statistical
    skewness: Optional[float] = None
    kurtosis: Optional[float] = None
    var_95: Optional[float] = None  # Value at Risk 95%
    cvar_95: Optional[float] = None  # Conditional VaR
    # Benchmark-relative (populated only when a benchmark is set)
    beta: Optional[float] = None  # Sensitivity to benchmark moves
    alpha: Optional[float] = None  # Annualized CAPM excess return
    tracking_error: Optional[float] = None  # Annualized std of active returns
    information_ratio: Optional[float] = None  # Active return / tracking error
    up_capture: Optional[float] = None  # Share of benchmark up-moves captured
    down_capture: Optional[float] = None  # Share of benchmark down-moves captured
    # Recommendation
    recommendation: str = "Hold"
    score: float = 0.0
    percentile_rank: Optional[float] = None


@dataclass
class Holding:
    """A single position in a personal portfolio."""
    symbol: str
    shares: float
    cost_basis: float  # price paid per share
    ter: Optional[float] = None  # annual expense ratio, e.g. 0.018 = 1.8%
    name: str = ""


@dataclass
class PortfolioPosition:
    """Computed state of one holding, including current value and P&L."""
    symbol: str
    name: str
    shares: float
    cost_basis: float
    current_price: Optional[float] = None
    cost_value: float = 0.0
    current_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    weight: Optional[float] = None  # share of total portfolio value
    return_1y: Optional[float] = None
    ter: Optional[float] = None
    annual_fee_cost: Optional[float] = None  # ter * current_value


class FundAnalyzer:
    """Main class for analyzing Polish investment funds."""

    def __init__(self, use_cache: bool = True, cache_dir: Path = CACHE_DIR):
        """
        Initialize the analyzer.

        Parameters
        ----------
        use_cache : bool
            Whether to use caching for downloaded data
        cache_dir : Path
            Directory for cache storage
        """
        self.use_cache = use_cache
        self.cache_dir = cache_dir
        if use_cache:
            self.cache_dir.mkdir(exist_ok=True)

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/118.0 Safari/537.36"
            )
        }

        # Benchmark price data, set via set_benchmark(); enables relative metrics
        self.benchmark_symbol: Optional[str] = None
        self.benchmark_df: Optional[pd.DataFrame] = None

    def set_benchmark(self, symbol: str) -> bool:
        """
        Download and store a benchmark price series (e.g. a market index).

        Once set, ``analyze_fund`` will compute benchmark-relative metrics
        (beta, alpha, tracking error, information ratio, up/down capture)
        for every fund.

        Parameters
        ----------
        symbol : str
            Benchmark ticker on Stooq (e.g. "wig" for the WIG index).

        Returns
        -------
        bool
            True if the benchmark was downloaded successfully, else False.
        """
        df = self.download_quotes(symbol)
        if df is None or len(df) < 60:
            print(
                f"Warning: could not load benchmark '{symbol}' "
                f"(insufficient data); relative metrics disabled.",
                file=sys.stderr,
            )
            return False
        self.benchmark_symbol = symbol
        self.benchmark_df = df
        return True

    def get_fund_list(self, url: str = "https://stooq.pl/t/") -> List[FundInfo]:
        """
        Download the master list of funds from Stooq.

        Parameters
        ----------
        url : str
            The URL of the Stooq fund listing

        Returns
        -------
        List[FundInfo]
            A list of fund meta information

        Raises
        ------
        RuntimeError
            If the table cannot be found or parsed
        """
        cache_file = self.cache_dir / "fund_list.pkl"

        # Check cache (with race condition protection)
        if self.use_cache and cache_file.exists():
            try:
                cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(
                    cache_file.stat().st_mtime
                )
                if cache_age.days < CACHE_EXPIRY_DAYS:
                    with open(cache_file, "rb") as f:
                        return pickle.load(f)
            except (FileNotFoundError, EOFError, pickle.UnpicklingError):
                # Cache file was deleted, corrupted, or incomplete - ignore and re-download
                pass

        # Download fresh data
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the table with fund listings
        table = soup.find("table")
        while table:
            headers_row = [th.get_text(strip=True) for th in table.find_all("th")]
            if "Symbol" in headers_row and "Nazwa" in headers_row:
                break
            table = table.find_next("table")

        if not table:
            raise RuntimeError("Could not locate fund listing table on the page")

        funds = []
        for tr in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if not cols or cols[0] == "Symbol":
                continue
            symbol = cols[0]
            name = cols[1] if len(cols) > 1 else ""
            funds.append(FundInfo(symbol=symbol, name=name))

        # Cache the results (with race condition protection)
        if self.use_cache:
            try:
                # Write to temp file first, then atomic rename
                temp_file = cache_file.with_suffix('.tmp')
                with open(temp_file, "wb") as f:
                    pickle.dump(funds, f)
                temp_file.replace(cache_file)
            except Exception:
                # If caching fails, continue without it
                pass

        return funds

    def download_quotes(self, symbol: str, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        Fetch historical daily quotes for a given fund symbol.

        Parameters
        ----------
        symbol : str
            Ticker of the fund (e.g. "1006.N")
        max_retries : int
            Maximum number of retry attempts

        Returns
        -------
        pd.DataFrame or None
            DataFrame with Date, Open, High, Low, Close, Volume columns
        """
        cache_file = self.cache_dir / f"{symbol.replace('.', '_')}.pkl"

        # Check cache (with race condition protection)
        if self.use_cache and cache_file.exists():
            try:
                cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(
                    cache_file.stat().st_mtime
                )
                if cache_age.days < CACHE_EXPIRY_DAYS:
                    with open(cache_file, "rb") as f:
                        return pickle.load(f)
            except (FileNotFoundError, EOFError, pickle.UnpicklingError):
                # Cache file was deleted, corrupted, or incomplete - ignore and re-download
                pass

        # Download with retries
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"

        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=self.headers, timeout=30)
                resp.raise_for_status()

                csv_data = resp.content.decode("utf-8", errors="ignore")
                lines = csv_data.splitlines()
                if not lines:
                    # Empty response, skip to next retry
                    continue
                first_line = lines[0].lower()
                has_header = first_line.startswith("date")

                df = pd.read_csv(
                    StringIO(csv_data),
                    sep=",",
                    header=0 if has_header else None,
                    names=["Date", "Open", "High", "Low", "Close", "Volume"],
                    parse_dates=["Date"],
                    dayfirst=False,
                )

                # Data validation and cleaning
                df = df.dropna(subset=["Close"])
                df = df[df["Close"] > 0]  # Remove invalid prices
                df = df.sort_values("Date").reset_index(drop=True)

                # Cache the results (with race condition protection)
                if self.use_cache and len(df) > 0:
                    try:
                        # Write to temp file first, then atomic rename
                        temp_file = cache_file.with_suffix('.tmp')
                        with open(temp_file, "wb") as f:
                            pickle.dump(df, f)
                        temp_file.replace(cache_file)
                    except Exception:
                        # If caching fails, continue without it
                        pass

                return df

            except Exception as exc:
                if attempt == max_retries - 1:
                    print(f"Warning: failed to fetch {symbol} after {max_retries} attempts: {exc}",
                          file=sys.stderr)
                    return None

        return None

    def calculate_returns(self, df: pd.DataFrame) -> Dict[str, Optional[float]]:
        """
        Calculate various return metrics.

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data

        Returns
        -------
        dict
            Dictionary with return metrics
        """
        if df is None or len(df) < 2:
            return {
                "1m": None, "3m": None, "6m": None,
                "1y": None, "ytd": None
            }

        def calc_return(days: int) -> Optional[float]:
            if len(df) <= days:
                return None
            end_price = df["Close"].iloc[-1]
            start_price = df["Close"].iloc[-(days + 1)]
            if start_price == 0:
                return None
            return (end_price - start_price) / start_price

        # Year-to-date return
        ytd_return = None
        current_year = datetime.datetime.now().year
        ytd_data = df[df["Date"].dt.year == current_year]
        if len(ytd_data) > 1:
            start_price_ytd = ytd_data["Close"].iloc[0]
            if start_price_ytd == 0:
                ytd_return = None
            else:
                ytd_return = (ytd_data["Close"].iloc[-1] - start_price_ytd) / start_price_ytd

        return {
            "1m": calc_return(21),
            "3m": calc_return(63),
            "6m": calc_return(126),
            "1y": calc_return(252),
            "ytd": ytd_return
        }

    def calculate_volatility(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate annualized volatility.

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data

        Returns
        -------
        float or None
            Annualized volatility
        """
        if df is None or len(df) < 20:
            return None

        # Calculate daily returns
        returns = df["Close"].pct_change().dropna()

        # Annualize the standard deviation
        return returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    def calculate_sharpe_ratio(self, df: pd.DataFrame, risk_free_rate: float = RISK_FREE_RATE) -> Optional[float]:
        """
        Calculate Sharpe ratio (risk-adjusted return).

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data
        risk_free_rate : float
            Annual risk-free rate

        Returns
        -------
        float or None
            Sharpe ratio
        """
        if df is None or len(df) < 252:
            return None

        returns = df["Close"].pct_change().dropna()

        # Annualized return (arithmetic annualization for Sharpe ratio)
        annual_return = returns.mean() * TRADING_DAYS_PER_YEAR

        # Annualized volatility
        annual_vol = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        if annual_vol == 0:
            return None

        return (annual_return - risk_free_rate) / annual_vol

    def calculate_sortino_ratio(self, df: pd.DataFrame, risk_free_rate: float = RISK_FREE_RATE) -> Optional[float]:
        """
        Calculate Sortino ratio (downside risk-adjusted return).

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data
        risk_free_rate : float
            Annual risk-free rate

        Returns
        -------
        float or None
            Sortino ratio
        """
        if df is None or len(df) < 252:
            return None

        returns = df["Close"].pct_change().dropna()

        # Annualized return (arithmetic annualization for Sortino ratio)
        annual_return = returns.mean() * TRADING_DAYS_PER_YEAR

        # Downside deviation (only negative returns)
        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0:
            return None

        downside_std = negative_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        if downside_std == 0:
            return None

        return (annual_return - risk_free_rate) / downside_std

    def calculate_max_drawdown(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate maximum drawdown.

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data

        Returns
        -------
        float or None
            Maximum drawdown as a negative percentage
        """
        if df is None or len(df) < 2:
            return None

        prices = df["Close"].values
        cummax = np.maximum.accumulate(prices)

        # Guard against division by zero if cummax contains zeros
        if np.any(cummax == 0):
            return None

        drawdown = (prices - cummax) / cummax

        return drawdown.min()

    def calculate_calmar_ratio(self, df: pd.DataFrame) -> Optional[float]:
        """
        Calculate Calmar ratio (return / max drawdown).

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data

        Returns
        -------
        float or None
            Calmar ratio
        """
        if df is None or len(df) < 252:
            return None

        returns = df["Close"].pct_change().dropna()
        # Annualized return (arithmetic annualization for Calmar ratio)
        annual_return = returns.mean() * TRADING_DAYS_PER_YEAR

        max_dd = self.calculate_max_drawdown(df)
        if max_dd is None or max_dd == 0:
            return None

        return annual_return / abs(max_dd)

    def calculate_var_cvar(self, df: pd.DataFrame, confidence: float = 0.95) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate Value at Risk and Conditional VaR.

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data
        confidence : float
            Confidence level (default 0.95 for 95%)

        Returns
        -------
        tuple
            (VaR, CVaR) both as negative percentages
        """
        if df is None or len(df) < 100:
            return None, None

        returns = df["Close"].pct_change().dropna()

        # VaR: percentile of returns
        var = np.percentile(returns, (1 - confidence) * 100)

        # CVaR: mean of returns below VaR
        cvar = returns[returns <= var].mean()

        return var, cvar

    def calculate_statistics(self, df: pd.DataFrame) -> Dict[str, Optional[float]]:
        """
        Calculate statistical measures.

        Parameters
        ----------
        df : pd.DataFrame
            Historical price data

        Returns
        -------
        dict
            Dictionary with skewness and kurtosis
        """
        if df is None or len(df) < 30:
            return {"skewness": None, "kurtosis": None}

        returns = df["Close"].pct_change().dropna()

        return {
            "skewness": stats.skew(returns),
            "kurtosis": stats.kurtosis(returns)
        }

    def calculate_benchmark_metrics(
        self, df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Optional[float]]:
        """
        Calculate metrics that compare a fund against a benchmark.

        Daily returns are aligned on common trading dates (an inner join on
        Date) so funds and the benchmark that trade on different days are
        compared fairly.

        Parameters
        ----------
        df : pd.DataFrame
            Fund price data with Date and Close columns.
        benchmark_df : pd.DataFrame, optional
            Benchmark price data. Defaults to ``self.benchmark_df``.

        Returns
        -------
        dict
            beta, alpha (annualized), tracking_error (annualized),
            information_ratio, up_capture, down_capture. Any value may be
            None when it cannot be computed.
        """
        empty = {
            "beta": None, "alpha": None, "tracking_error": None,
            "information_ratio": None, "up_capture": None, "down_capture": None,
        }

        if benchmark_df is None:
            benchmark_df = self.benchmark_df
        if df is None or benchmark_df is None:
            return empty

        # Daily returns keyed by date (normalize to calendar day so series
        # align even if timestamps carry a time component)
        fund_ret = df[["Date", "Close"]].copy()
        fund_ret["Date"] = pd.to_datetime(fund_ret["Date"]).dt.normalize()
        fund_ret["r"] = fund_ret["Close"].pct_change()
        bench_ret = benchmark_df[["Date", "Close"]].copy()
        bench_ret["Date"] = pd.to_datetime(bench_ret["Date"]).dt.normalize()
        bench_ret["b"] = bench_ret["Close"].pct_change()

        merged = pd.merge(
            fund_ret[["Date", "r"]], bench_ret[["Date", "b"]], on="Date", how="inner"
        ).dropna()

        # Need a meaningful overlap to produce stable statistics
        if len(merged) < 60:
            return empty

        r = merged["r"].to_numpy()
        b = merged["b"].to_numpy()
        rf_daily = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR

        # Beta / alpha from excess returns (CAPM)
        excess_r = r - rf_daily
        excess_b = b - rf_daily
        var_b = np.var(excess_b)
        if var_b == 0:
            beta = None
            alpha = None
        else:
            beta = float(np.cov(excess_r, excess_b)[0, 1] / var_b)
            alpha_daily = excess_r.mean() - beta * excess_b.mean()
            alpha = float(alpha_daily * TRADING_DAYS_PER_YEAR)

        # Tracking error and information ratio from active returns
        active = r - b
        te_daily = active.std(ddof=1)
        tracking_error = float(te_daily * np.sqrt(TRADING_DAYS_PER_YEAR))
        if tracking_error == 0:
            information_ratio = None
        else:
            information_ratio = float(
                (active.mean() * TRADING_DAYS_PER_YEAR) / tracking_error
            )

        # Up/down capture ratios
        up = b > 0
        down = b < 0
        up_capture = (
            float(r[up].mean() / b[up].mean())
            if up.any() and b[up].mean() != 0 else None
        )
        down_capture = (
            float(r[down].mean() / b[down].mean())
            if down.any() and b[down].mean() != 0 else None
        )

        return {
            "beta": beta,
            "alpha": alpha,
            "tracking_error": tracking_error,
            "information_ratio": information_ratio,
            "up_capture": up_capture,
            "down_capture": down_capture,
        }

    def compute_correlation_matrix(
        self, symbols: List[str], min_overlap: int = 60, high_threshold: float = 0.8
    ) -> Tuple[Optional[pd.DataFrame], List[Tuple[str, str, float]]]:
        """
        Build a return-correlation matrix across funds and flag redundant pairs.

        Highly correlated holdings move together, so holding several of them
        adds little diversification. This downloads each symbol (cache makes
        repeats cheap), aligns daily returns on common dates, and reports the
        correlation matrix plus pairs above ``high_threshold``.

        Parameters
        ----------
        symbols : List[str]
            Fund tickers to compare.
        min_overlap : int
            Minimum number of shared trading days required for a pair.
        high_threshold : float
            Correlation above which a pair is flagged as redundant.

        Returns
        -------
        tuple
            (correlation DataFrame or None, list of (symbol_a, symbol_b,
            correlation) sorted by descending correlation).
        """
        series = {}
        for symbol in symbols:
            df = self.download_quotes(symbol)
            if df is None or len(df) < min_overlap:
                continue
            tmp = df[["Date", "Close"]].copy()
            # Normalize to calendar day so series from different funds align
            tmp["Date"] = pd.to_datetime(tmp["Date"]).dt.normalize()
            s = tmp.set_index("Date")["Close"].pct_change().dropna()
            if not s.empty:
                series[symbol] = s

        if len(series) < 2:
            return None, []

        # Align on common dates; columns with too little overlap drop out
        returns_df = pd.DataFrame(series).dropna()
        if len(returns_df) < min_overlap:
            return None, []

        corr = returns_df.corr()

        # Collect unique upper-triangle pairs above the threshold
        high_pairs: List[Tuple[str, str, float]] = []
        cols = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                value = corr.iloc[i, j]
                if pd.notna(value) and value >= high_threshold:
                    high_pairs.append((cols[i], cols[j], float(value)))

        high_pairs.sort(key=lambda x: x[2], reverse=True)
        return corr, high_pairs

    # ------------------------------------------------------------------
    # Portfolio tracking
    # ------------------------------------------------------------------

    @staticmethod
    def load_portfolio(path: str) -> List[Holding]:
        """
        Load a list of holdings from a JSON or CSV file.

        JSON format (either a top-level list or a {"holdings": [...]} object)::

            [
              {"symbol": "1006.N", "shares": 100, "cost_basis": 45.5,
               "ter": 0.018, "name": "Example Fund"}
            ]

        CSV format: a header row with columns
        ``symbol,shares,cost_basis[,ter,name]``.

        Parameters
        ----------
        path : str
            Path to the holdings file.

        Returns
        -------
        List[Holding]
        """
        p = Path(path)
        holdings: List[Holding] = []

        if p.suffix.lower() == ".json":
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = data["holdings"] if isinstance(data, dict) else data
            for row in rows:
                holdings.append(Holding(
                    symbol=str(row["symbol"]),
                    shares=float(row["shares"]),
                    cost_basis=float(row["cost_basis"]),
                    ter=float(row["ter"]) if row.get("ter") is not None else None,
                    name=str(row.get("name", "")),
                ))
        else:
            # Treat anything else as CSV
            holdings_df = pd.read_csv(p)
            for _, row in holdings_df.iterrows():
                ter = row["ter"] if "ter" in holdings_df.columns and pd.notna(row["ter"]) else None
                name = row["name"] if "name" in holdings_df.columns and pd.notna(row["name"]) else ""
                holdings.append(Holding(
                    symbol=str(row["symbol"]),
                    shares=float(row["shares"]),
                    cost_basis=float(row["cost_basis"]),
                    ter=float(ter) if ter is not None else None,
                    name=str(name),
                ))

        return holdings

    def analyze_portfolio(
        self, holdings: List[Holding]
    ) -> Tuple[List[PortfolioPosition], Dict[str, Optional[float]]]:
        """
        Value a portfolio: current price, P&L, allocation and weighted return.

        Each holding's latest price is taken from its most recent close. Funds
        whose data cannot be fetched are still reported, but with ``None`` for
        price-derived fields and excluded from totals.

        Parameters
        ----------
        holdings : List[Holding]

        Returns
        -------
        tuple
            (list of PortfolioPosition, summary dict with total_cost,
            total_value, total_pnl, total_pnl_pct, total_annual_fees,
            weighted_return_1y, num_positions, num_priced).
        """
        positions: List[PortfolioPosition] = []

        for h in holdings:
            df = self.download_quotes(h.symbol)
            cost_value = h.shares * h.cost_basis

            pos = PortfolioPosition(
                symbol=h.symbol,
                name=h.name or h.symbol,
                shares=h.shares,
                cost_basis=h.cost_basis,
                cost_value=cost_value,
                ter=h.ter,
            )

            if df is not None and len(df) > 0:
                current_price = float(df["Close"].iloc[-1])
                current_value = h.shares * current_price
                pos.current_price = current_price
                pos.current_value = current_value
                pos.unrealized_pnl = current_value - cost_value
                pos.unrealized_pnl_pct = (
                    (current_value - cost_value) / cost_value if cost_value else None
                )
                pos.return_1y = self.calculate_returns(df)["1y"]
                if h.ter is not None:
                    pos.annual_fee_cost = h.ter * current_value

            positions.append(pos)

        # Totals over positions that have a current value
        priced = [p for p in positions if p.current_value is not None]
        total_value = sum(p.current_value for p in priced)
        total_cost = sum(p.cost_value for p in priced)
        total_pnl = total_value - total_cost if priced else None
        total_pnl_pct = (total_pnl / total_cost) if (priced and total_cost) else None
        total_annual_fees = sum(
            p.annual_fee_cost for p in priced if p.annual_fee_cost is not None
        )

        # Allocation weights and value-weighted 1y return
        weighted_return_1y = None
        if total_value:
            weighted_sum = 0.0
            weight_with_return = 0.0
            for p in priced:
                p.weight = p.current_value / total_value
                if p.return_1y is not None:
                    weighted_sum += p.weight * p.return_1y
                    weight_with_return += p.weight
            if weight_with_return > 0:
                # Normalize by covered weight so missing returns don't dilute
                weighted_return_1y = weighted_sum / weight_with_return

        summary = {
            "num_positions": len(positions),
            "num_priced": len(priced),
            "total_cost": total_cost if priced else None,
            "total_value": total_value if priced else None,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "total_annual_fees": total_annual_fees if priced else None,
            "weighted_return_1y": weighted_return_1y,
        }

        return positions, summary

    @staticmethod
    def project_fee_drag(
        amount: float, ter: float, years: int, gross_annual_return: float
    ) -> Dict[str, float]:
        """
        Project the long-term cost of an expense ratio (TER).

        Compounds ``amount`` for ``years`` at ``gross_annual_return`` both with
        and without the annual fee, where the fee is charged on the balance each
        year (net factor = (1 + gross) * (1 - ter)).

        Parameters
        ----------
        amount : float
            Starting investment.
        ter : float
            Annual expense ratio (e.g. 0.018 for 1.8%).
        years : int
            Investment horizon in years.
        gross_annual_return : float
            Assumed gross annual return before fees (e.g. 0.06 for 6%).

        Returns
        -------
        dict
            gross_value, net_value, total_fees (terminal value lost to fees),
            drag_pct (fees as a share of the no-fee terminal value).
        """
        gross_value = amount
        net_value = amount
        for _ in range(max(int(years), 0)):
            gross_value *= (1 + gross_annual_return)
            net_value *= (1 + gross_annual_return) * (1 - ter)

        total_fees = gross_value - net_value
        drag_pct = (total_fees / gross_value) if gross_value else 0.0

        return {
            "gross_value": gross_value,
            "net_value": net_value,
            "total_fees": total_fees,
            "drag_pct": drag_pct,
        }

    def analyze_fund(self, fund: FundInfo) -> Optional[FundMetrics]:
        """
        Perform complete analysis on a single fund.

        Parameters
        ----------
        fund : FundInfo
            Fund information

        Returns
        -------
        FundMetrics or None
            Complete metrics for the fund
        """
        df = self.download_quotes(fund.symbol)

        if df is None or len(df) < 20:
            return None

        # Calculate all metrics
        returns = self.calculate_returns(df)
        volatility = self.calculate_volatility(df)
        sharpe = self.calculate_sharpe_ratio(df)
        sortino = self.calculate_sortino_ratio(df)
        max_dd = self.calculate_max_drawdown(df)
        calmar = self.calculate_calmar_ratio(df)
        var, cvar = self.calculate_var_cvar(df)
        stats_metrics = self.calculate_statistics(df)

        # Benchmark-relative metrics (only when a benchmark has been set)
        bench = self.calculate_benchmark_metrics(df)

        metrics = FundMetrics(
            symbol=fund.symbol,
            name=fund.name,
            return_1m=returns["1m"],
            return_3m=returns["3m"],
            return_6m=returns["6m"],
            return_1y=returns["1y"],
            return_ytd=returns["ytd"],
            volatility=volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            calmar_ratio=calmar,
            skewness=stats_metrics["skewness"],
            kurtosis=stats_metrics["kurtosis"],
            var_95=var,
            cvar_95=cvar,
            beta=bench["beta"],
            alpha=bench["alpha"],
            tracking_error=bench["tracking_error"],
            information_ratio=bench["information_ratio"],
            up_capture=bench["up_capture"],
            down_capture=bench["down_capture"],
        )

        return metrics

    def assign_recommendation(self, metrics: FundMetrics,
                            score_weights: Optional[Dict[str, float]] = None) -> Tuple[str, float]:
        """
        Assign recommendation based on multi-factor scoring.

        Parameters
        ----------
        metrics : FundMetrics
            Fund metrics
        score_weights : dict, optional
            Custom weights for scoring factors

        Returns
        -------
        tuple
            (recommendation, score)
        """
        if score_weights is None:
            score_weights = {
                "return_6m": 0.25,
                "return_1y": 0.20,
                "sharpe_ratio": 0.25,
                "sortino_ratio": 0.15,
                "max_drawdown": 0.15,
            }

        score = 0.0
        total_weight = 0.0

        # 6-month return scoring
        if metrics.return_6m is not None:
            if metrics.return_6m > 0.15:
                score += 100 * score_weights["return_6m"]
            elif metrics.return_6m > 0.10:
                score += 80 * score_weights["return_6m"]
            elif metrics.return_6m > 0.05:
                score += 60 * score_weights["return_6m"]
            elif metrics.return_6m > 0:
                score += 40 * score_weights["return_6m"]
            elif metrics.return_6m > -0.05:
                score += 20 * score_weights["return_6m"]
            total_weight += score_weights["return_6m"]

        # 1-year return scoring
        if metrics.return_1y is not None:
            if metrics.return_1y > 0.20:
                score += 100 * score_weights["return_1y"]
            elif metrics.return_1y > 0.15:
                score += 80 * score_weights["return_1y"]
            elif metrics.return_1y > 0.10:
                score += 60 * score_weights["return_1y"]
            elif metrics.return_1y > 0:
                score += 40 * score_weights["return_1y"]
            elif metrics.return_1y > -0.05:
                score += 20 * score_weights["return_1y"]
            total_weight += score_weights["return_1y"]

        # Sharpe ratio scoring
        if metrics.sharpe_ratio is not None:
            if metrics.sharpe_ratio > 2.0:
                score += 100 * score_weights["sharpe_ratio"]
            elif metrics.sharpe_ratio > 1.5:
                score += 80 * score_weights["sharpe_ratio"]
            elif metrics.sharpe_ratio > 1.0:
                score += 60 * score_weights["sharpe_ratio"]
            elif metrics.sharpe_ratio > 0.5:
                score += 40 * score_weights["sharpe_ratio"]
            elif metrics.sharpe_ratio > 0:
                score += 20 * score_weights["sharpe_ratio"]
            total_weight += score_weights["sharpe_ratio"]

        # Sortino ratio scoring
        if metrics.sortino_ratio is not None:
            if metrics.sortino_ratio > 2.5:
                score += 100 * score_weights["sortino_ratio"]
            elif metrics.sortino_ratio > 2.0:
                score += 80 * score_weights["sortino_ratio"]
            elif metrics.sortino_ratio > 1.5:
                score += 60 * score_weights["sortino_ratio"]
            elif metrics.sortino_ratio > 1.0:
                score += 40 * score_weights["sortino_ratio"]
            elif metrics.sortino_ratio > 0:
                score += 20 * score_weights["sortino_ratio"]
            total_weight += score_weights["sortino_ratio"]

        # Max drawdown scoring (less negative is better)
        if metrics.max_drawdown is not None:
            if metrics.max_drawdown > -0.05:
                score += 100 * score_weights["max_drawdown"]
            elif metrics.max_drawdown > -0.10:
                score += 80 * score_weights["max_drawdown"]
            elif metrics.max_drawdown > -0.15:
                score += 60 * score_weights["max_drawdown"]
            elif metrics.max_drawdown > -0.20:
                score += 40 * score_weights["max_drawdown"]
            elif metrics.max_drawdown > -0.30:
                score += 20 * score_weights["max_drawdown"]
            total_weight += score_weights["max_drawdown"]

        # Normalize score
        if total_weight > 0:
            score = score / total_weight

        # Assign recommendation
        if score >= 70:
            recommendation = "Buy"
        elif score >= 40:
            recommendation = "Hold"
        else:
            recommendation = "Sell"

        return recommendation, score

    def analyze_funds(self, funds: List[FundInfo], max_workers: int = 10,
                     score_weights: Optional[Dict[str, float]] = None) -> List[FundMetrics]:
        """
        Analyze multiple funds in parallel.

        Parameters
        ----------
        funds : List[FundInfo]
            List of funds to analyze
        max_workers : int
            Number of parallel workers
        score_weights : dict, optional
            Custom weights for scoring

        Returns
        -------
        List[FundMetrics]
            List of fund metrics
        """
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_fund = {
                executor.submit(self.analyze_fund, fund): fund
                for fund in funds
            }

            # Process results with progress bar
            with tqdm(total=len(funds), desc="Analyzing funds", file=sys.stderr) as pbar:
                for future in as_completed(future_to_fund):
                    fund = future_to_fund[future]
                    try:
                        metrics = future.result()
                        if metrics is not None:
                            # Assign recommendation and score
                            rec, score = self.assign_recommendation(metrics, score_weights)
                            metrics.recommendation = rec
                            metrics.score = score
                            results.append(metrics)
                    except Exception as exc:
                        print(f"Error analyzing {fund.symbol}: {exc}", file=sys.stderr)
                    finally:
                        pbar.update(1)

        # Calculate percentile ranks
        if results:
            scores = [m.score for m in results]
            for metrics in results:
                metrics.percentile_rank = stats.percentileofscore(scores, metrics.score)

        return results

    def create_summary_dataframe(self, results: List[FundMetrics]) -> pd.DataFrame:
        """
        Convert results to a pandas DataFrame.

        Parameters
        ----------
        results : List[FundMetrics]
            List of fund metrics

        Returns
        -------
        pd.DataFrame
            Summary DataFrame
        """
        data = [asdict(m) for m in results]
        df = pd.DataFrame(data)

        # Format percentage columns
        pct_cols = [
            "return_1m", "return_3m", "return_6m", "return_1y", "return_ytd",
            "volatility", "max_drawdown", "var_95", "cvar_95"
        ]

        # Sort by score descending
        df = df.sort_values("score", ascending=False).reset_index(drop=True)

        return df

    def export_to_csv(self, df: pd.DataFrame, output_path: str):
        """Export results to CSV."""
        df.to_csv(output_path, index=False)
        print(f"Results exported to {output_path}", file=sys.stderr)

    def export_to_excel(self, df: pd.DataFrame, output_path: str):
        """Export results to Excel with formatting."""
        try:
            from openpyxl.utils import get_column_letter

            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Fund Analysis', index=False)

                # Get the worksheet
                worksheet = writer.sheets['Fund Analysis']

                # Auto-adjust column widths
                for idx, col in enumerate(df.columns, 1):
                    try:
                        col_max = df[col].astype(str).apply(len).max()
                        # Handle NaN or invalid values
                        if pd.isna(col_max):
                            col_max = len(col)
                        max_length = max(int(col_max), len(col))
                        worksheet.column_dimensions[get_column_letter(idx)].width = min(max_length + 2, 50)
                    except (ValueError, TypeError):
                        # Fallback to column name length
                        worksheet.column_dimensions[get_column_letter(idx)].width = len(col) + 2

            print(f"Results exported to {output_path}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not export to Excel: {e}", file=sys.stderr)

    def export_to_json(self, df: pd.DataFrame, output_path: str):
        """Export results to JSON."""
        df.to_json(output_path, orient='records', indent=2, date_format='iso')
        print(f"Results exported to {output_path}", file=sys.stderr)

    def export_to_html(self, df: pd.DataFrame, output_path: str):
        """Export results to HTML with styling."""
        # Create a styled HTML report
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Polish Funds Analysis Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
            text-align: center;
        }}
        .summary {{
            background: white;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th {{
            background-color: #4CAF50;
            color: white;
            padding: 12px;
            text-align: left;
            position: sticky;
            top: 0;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .buy {{
            background-color: #c8e6c9 !important;
        }}
        .sell {{
            background-color: #ffcdd2 !important;
        }}
        .hold {{
            background-color: #fff9c4 !important;
        }}
        .metric-positive {{
            color: #2e7d32;
        }}
        .metric-negative {{
            color: #c62828;
        }}
    </style>
</head>
<body>
    <h1>Polish Investment Funds Analysis</h1>
    <div class="summary">
        <h2>Summary Statistics</h2>
        <p><strong>Total Funds Analyzed:</strong> {len(df)}</p>
        <p><strong>Buy Recommendations:</strong> {len(df[df['recommendation'] == 'Buy'])}</p>
        <p><strong>Hold Recommendations:</strong> {len(df[df['recommendation'] == 'Hold'])}</p>
        <p><strong>Sell Recommendations:</strong> {len(df[df['recommendation'] == 'Sell'])}</p>
        <p><strong>Report Generated:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
"""

        # Convert DataFrame to HTML
        df_display = df.copy()

        # Format percentage columns
        pct_cols = [
            "return_1m", "return_3m", "return_6m", "return_1y", "return_ytd",
            "volatility", "max_drawdown", "var_95", "cvar_95"
        ]
        for col in pct_cols:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A"
                )

        # Format ratio columns
        ratio_cols = ["sharpe_ratio", "sortino_ratio", "calmar_ratio", "skewness", "kurtosis"]
        for col in ratio_cols:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: f"{x:.3f}" if pd.notna(x) else "N/A"
                )

        # Format score and percentile
        if "score" in df_display.columns:
            df_display["score"] = df_display["score"].apply(lambda x: f"{x:.1f}")
        if "percentile_rank" in df_display.columns:
            df_display["percentile_rank"] = df_display["percentile_rank"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"
            )

        table_html = df_display.to_html(index=False, escape=False, classes='data')

        # Add row coloring based on recommendation
        for rec in ["Buy", "Hold", "Sell"]:
            table_html = table_html.replace(
                f"<td>{rec}</td>",
                f'<td class="{rec.lower()}">{rec}</td>'
            )

        html += table_html
        html += """
    <div class="summary" style="margin-top: 20px;">
        <p><small><em>Disclaimer: This analysis is for informational and educational purposes only.
        It does not constitute professional investment advice. Consult a qualified financial advisor
        before making investment decisions.</em></small></p>
    </div>
</body>
</html>
"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"HTML report exported to {output_path}", file=sys.stderr)

    def create_visualizations(self, df: pd.DataFrame, output_dir: str = "."):
        """
        Create visualization charts.

        Parameters
        ----------
        df : pd.DataFrame
            Results DataFrame
        output_dir : str
            Directory for saving plots
        """
        if not PLOT_AVAILABLE:
            print("Plotting libraries not available. Skipping visualizations.", file=sys.stderr)
            return

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        sns.set_style("whitegrid")

        # 1. Return distribution
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # 6-month returns histogram
        returns_6m = df["return_6m"].dropna() * 100
        axes[0, 0].hist(returns_6m, bins=30, color='steelblue', edgecolor='black', alpha=0.7)
        axes[0, 0].axvline(returns_6m.mean(), color='red', linestyle='--', label=f'Mean: {returns_6m.mean():.2f}%')
        axes[0, 0].set_xlabel('6-Month Return (%)')
        axes[0, 0].set_ylabel('Frequency')
        axes[0, 0].set_title('Distribution of 6-Month Returns')
        axes[0, 0].legend()

        # Recommendation counts
        rec_counts = df['recommendation'].value_counts()
        colors = {'Buy': '#4CAF50', 'Hold': '#FFC107', 'Sell': '#F44336'}
        rec_colors = [colors.get(x, 'gray') for x in rec_counts.index]
        axes[0, 1].bar(rec_counts.index, rec_counts.values, color=rec_colors, edgecolor='black')
        axes[0, 1].set_ylabel('Count')
        axes[0, 1].set_title('Recommendation Distribution')

        # Risk-Return scatter (Sharpe ratio vs Return)
        valid_data = df.dropna(subset=['return_1y', 'sharpe_ratio'])
        scatter = axes[1, 0].scatter(
            valid_data['volatility'] * 100,
            valid_data['return_1y'] * 100,
            c=valid_data['sharpe_ratio'],
            cmap='RdYlGn',
            s=100,
            alpha=0.6,
            edgecolors='black'
        )
        axes[1, 0].set_xlabel('Volatility (Annualized %)')
        axes[1, 0].set_ylabel('1-Year Return (%)')
        axes[1, 0].set_title('Risk-Return Profile')
        plt.colorbar(scatter, ax=axes[1, 0], label='Sharpe Ratio')

        # Top 10 funds by score
        top10 = df.nlargest(10, 'score')
        axes[1, 1].barh(range(len(top10)), top10['score'], color='steelblue', edgecolor='black')
        axes[1, 1].set_yticks(range(len(top10)))
        axes[1, 1].set_yticklabels(top10['symbol'], fontsize=8)
        axes[1, 1].set_xlabel('Score')
        axes[1, 1].set_title('Top 10 Funds by Score')
        axes[1, 1].invert_yaxis()

        plt.tight_layout()
        plot_path = output_path / "fund_analysis_overview.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        print(f"Visualization saved to {plot_path}", file=sys.stderr)
        plt.close()

        # 2. Advanced metrics comparison
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # Sharpe vs Sortino
        valid_data = df.dropna(subset=['sharpe_ratio', 'sortino_ratio'])
        axes[0, 0].scatter(valid_data['sharpe_ratio'], valid_data['sortino_ratio'],
                          alpha=0.6, s=80, edgecolors='black')
        axes[0, 0].set_xlabel('Sharpe Ratio')
        axes[0, 0].set_ylabel('Sortino Ratio')
        axes[0, 0].set_title('Sharpe vs Sortino Ratio')
        axes[0, 0].axhline(0, color='gray', linestyle='--', alpha=0.5)
        axes[0, 0].axvline(0, color='gray', linestyle='--', alpha=0.5)

        # Max Drawdown distribution
        dd_data = df['max_drawdown'].dropna() * 100
        axes[0, 1].hist(dd_data, bins=30, color='coral', edgecolor='black', alpha=0.7)
        axes[0, 1].axvline(dd_data.mean(), color='red', linestyle='--',
                          label=f'Mean: {dd_data.mean():.2f}%')
        axes[0, 1].set_xlabel('Maximum Drawdown (%)')
        axes[0, 1].set_ylabel('Frequency')
        axes[0, 1].set_title('Maximum Drawdown Distribution')
        axes[0, 1].legend()

        # Volatility vs Max Drawdown
        valid_data = df.dropna(subset=['volatility', 'max_drawdown'])
        axes[1, 0].scatter(valid_data['volatility'] * 100, valid_data['max_drawdown'] * 100,
                          alpha=0.6, s=80, edgecolors='black', c='purple')
        axes[1, 0].set_xlabel('Volatility (%)')
        axes[1, 0].set_ylabel('Max Drawdown (%)')
        axes[1, 0].set_title('Volatility vs Maximum Drawdown')

        # Score distribution
        axes[1, 1].hist(df['score'], bins=30, color='teal', edgecolor='black', alpha=0.7)
        axes[1, 1].axvline(df['score'].mean(), color='red', linestyle='--',
                          label=f'Mean: {df["score"].mean():.1f}')
        axes[1, 1].set_xlabel('Score')
        axes[1, 1].set_ylabel('Frequency')
        axes[1, 1].set_title('Score Distribution')
        axes[1, 1].legend()

        plt.tight_layout()
        plot_path = output_path / "fund_analysis_metrics.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        print(f"Metrics visualization saved to {plot_path}", file=sys.stderr)
        plt.close()


def run_portfolio(args):
    """Run portfolio tracking and fee-drag analysis from a holdings file."""
    analyzer = FundAnalyzer(use_cache=not args.no_cache)

    try:
        holdings = analyzer.load_portfolio(args.portfolio)
    except Exception as exc:
        print(f"Error: could not load portfolio '{args.portfolio}': {exc}",
              file=sys.stderr)
        return

    if not holdings:
        print("No holdings found in portfolio file.", file=sys.stderr)
        return

    print(f"Valuing {len(holdings)} holding(s)…", file=sys.stderr)
    positions, summary = analyzer.analyze_portfolio(holdings)

    # Build a DataFrame and export in the requested formats
    df = pd.DataFrame([asdict(p) for p in positions])
    # Order columns for readability
    col_order = [
        "symbol", "name", "shares", "cost_basis", "current_price",
        "cost_value", "current_value", "unrealized_pnl", "unrealized_pnl_pct",
        "weight", "return_1y", "ter", "annual_fee_cost",
    ]
    df = df[[c for c in col_order if c in df.columns]]
    if summary.get("total_value"):
        df = df.sort_values("current_value", ascending=False).reset_index(drop=True)

    for fmt in args.format:
        output_path = f"{args.output}.{fmt}"
        if fmt == "csv":
            analyzer.export_to_csv(df, output_path)
        elif fmt == "excel":
            analyzer.export_to_excel(df, output_path)
        elif fmt == "json":
            analyzer.export_to_json(df, output_path)
        # HTML report is geared to fund screening; skip for portfolio mode

    # Console summary
    def fmt_money(x):
        return f"{x:,.2f}" if x is not None else "N/A"

    def fmt_pct(x):
        return f"{x*100:.2f}%" if x is not None else "N/A"

    print("\n" + "=" * 80, file=sys.stderr)
    print("PORTFOLIO SUMMARY", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Positions: {summary['num_positions']} "
          f"(priced: {summary['num_priced']})", file=sys.stderr)
    print(f"Total cost:    {fmt_money(summary['total_cost'])}", file=sys.stderr)
    print(f"Total value:   {fmt_money(summary['total_value'])}", file=sys.stderr)
    print(f"Unrealized P&L: {fmt_money(summary['total_pnl'])} "
          f"({fmt_pct(summary['total_pnl_pct'])})", file=sys.stderr)
    print(f"Value-weighted 1Y return: {fmt_pct(summary['weighted_return_1y'])}",
          file=sys.stderr)
    if summary.get("total_annual_fees"):
        print(f"Estimated annual fees (TER): {fmt_money(summary['total_annual_fees'])}",
              file=sys.stderr)

    # Fee-drag projection on the current portfolio value
    total_value = summary.get("total_value")
    fee_positions = [p for p in positions if p.ter is not None and p.current_value]
    if total_value and fee_positions:
        # Value-weighted average TER across positions that have one
        weighted_ter = sum(p.ter * p.current_value for p in fee_positions) / \
            sum(p.current_value for p in fee_positions)
        proj = analyzer.project_fee_drag(
            amount=total_value,
            ter=weighted_ter,
            years=args.project_years,
            gross_annual_return=args.assumed_return,
        )
        print("\n" + "-" * 80, file=sys.stderr)
        print(f"FEE-DRAG PROJECTION ({args.project_years} yrs @ "
              f"{args.assumed_return*100:.1f}% gross, avg TER "
              f"{weighted_ter*100:.2f}%)", file=sys.stderr)
        print("-" * 80, file=sys.stderr)
        print(f"Value without fees: {fmt_money(proj['gross_value'])}", file=sys.stderr)
        print(f"Value with fees:    {fmt_money(proj['net_value'])}", file=sys.stderr)
        print(f"Lost to fees:       {fmt_money(proj['total_fees'])} "
              f"({fmt_pct(proj['drag_pct'])} of the fee-free total)", file=sys.stderr)
    print("=" * 80 + "\n", file=sys.stderr)


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Enhanced analysis of Polish investment funds from Stooq",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze top 50 funds and export to CSV
  python analyze_polish_funds.py --max-funds 50 --output results.csv

  # Analyze all funds with Excel and HTML reports
  python analyze_polish_funds.py --max-funds 0 --format excel html

  # Disable caching and create visualizations
  python analyze_polish_funds.py --no-cache --plots

  # Custom scoring weights
  python analyze_polish_funds.py --score-config custom_weights.json
        """
    )

    parser.add_argument(
        "--max-funds",
        type=int,
        default=50,
        help="Maximum number of funds to analyze (0 for all, default: 50)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="funds_analysis",
        help="Base path for output files (default: funds_analysis)"
    )

    parser.add_argument(
        "--format",
        nargs='+',
        choices=['csv', 'excel', 'json', 'html'],
        default=['csv', 'html'],
        help="Output format(s) (default: csv html)"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching (always download fresh data)"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of parallel workers for downloading (default: 10)"
    )

    parser.add_argument(
        "--plots",
        action="store_true",
        help="Generate visualization plots"
    )

    parser.add_argument(
        "--score-config",
        type=str,
        help="Path to JSON file with custom scoring weights"
    )

    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear the cache directory and exit"
    )

    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        help="Benchmark ticker (e.g. 'wig') to compute relative metrics "
             "(beta, alpha, tracking error, information ratio, up/down capture)"
    )

    parser.add_argument(
        "--correlation",
        action="store_true",
        help="Compute a correlation matrix across analyzed funds and flag "
             "redundant (highly correlated) holdings"
    )

    parser.add_argument(
        "--portfolio",
        type=str,
        default=None,
        help="Path to a holdings file (JSON or CSV) to run portfolio "
             "tracking: current value, P&L, allocation and fee analysis"
    )

    parser.add_argument(
        "--project-years",
        type=int,
        default=10,
        help="Horizon in years for portfolio fee-drag projection (default: 10)"
    )

    parser.add_argument(
        "--assumed-return",
        type=float,
        default=0.06,
        help="Assumed gross annual return for fee-drag projection (default: 0.06)"
    )

    args = parser.parse_args()

    # Handle cache clearing
    if args.clear_cache:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            print(f"Cache directory {CACHE_DIR} cleared.", file=sys.stderr)
        else:
            print(f"Cache directory {CACHE_DIR} does not exist.", file=sys.stderr)
        return

    # Portfolio tracking mode: value holdings instead of screening all funds
    if args.portfolio:
        run_portfolio(args)
        return

    # Load custom scoring weights if provided
    score_weights = None
    if args.score_config:
        try:
            with open(args.score_config, 'r') as f:
                score_weights = json.load(f)
            print(f"Loaded custom scoring weights from {args.score_config}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not load score config: {e}", file=sys.stderr)

    # Initialize analyzer
    analyzer = FundAnalyzer(use_cache=not args.no_cache)

    # Load benchmark for relative metrics, if requested
    if args.benchmark:
        print(f"Loading benchmark '{args.benchmark}'…", file=sys.stderr)
        if analyzer.set_benchmark(args.benchmark):
            print(f"Benchmark '{args.benchmark}' loaded; computing relative metrics.",
                  file=sys.stderr)

    # Get fund list
    print("Downloading list of funds…", file=sys.stderr)
    funds = analyzer.get_fund_list()
    print(f"Found {len(funds)} funds.", file=sys.stderr)

    # Limit funds if requested
    if args.max_funds > 0:
        funds = funds[:args.max_funds]
        print(f"Analyzing first {len(funds)} funds.", file=sys.stderr)

    # Analyze funds
    results = analyzer.analyze_funds(funds, max_workers=args.workers, score_weights=score_weights)

    if not results:
        print("No funds were successfully analyzed.", file=sys.stderr)
        return

    # Create DataFrame
    df = analyzer.create_summary_dataframe(results)

    # Display summary to console
    print("\n" + "="*80, file=sys.stderr)
    print("ANALYSIS SUMMARY", file=sys.stderr)
    print("="*80, file=sys.stderr)
    print(f"Total funds analyzed: {len(df)}", file=sys.stderr)
    print(f"Buy recommendations: {len(df[df['recommendation'] == 'Buy'])}", file=sys.stderr)
    print(f"Hold recommendations: {len(df[df['recommendation'] == 'Hold'])}", file=sys.stderr)
    print(f"Sell recommendations: {len(df[df['recommendation'] == 'Sell'])}", file=sys.stderr)
    print("\nTop 10 funds by score:", file=sys.stderr)
    top10 = df[['symbol', 'name', 'score', 'recommendation', 'return_6m', 'sharpe_ratio']].head(10)
    print(top10.to_string(index=False), file=sys.stderr)
    print("="*80 + "\n", file=sys.stderr)

    # Export to requested formats
    for fmt in args.format:
        output_path = f"{args.output}.{fmt}"
        if fmt == 'csv':
            analyzer.export_to_csv(df, output_path)
        elif fmt == 'excel':
            analyzer.export_to_excel(df, output_path)
        elif fmt == 'json':
            analyzer.export_to_json(df, output_path)
        elif fmt == 'html':
            analyzer.export_to_html(df, output_path)

    # Create visualizations if requested
    if args.plots:
        analyzer.create_visualizations(df, output_dir="plots")

    # Correlation / diversification report if requested
    if args.correlation:
        print("\nComputing correlation across analyzed funds…", file=sys.stderr)
        symbols = [m.symbol for m in results]
        corr, high_pairs = analyzer.compute_correlation_matrix(symbols)
        if corr is None:
            print("Not enough overlapping data to compute correlations.", file=sys.stderr)
        else:
            corr_path = f"{args.output}_correlation.csv"
            corr.to_csv(corr_path)
            print(f"Correlation matrix written to {corr_path}", file=sys.stderr)
            if high_pairs:
                print("\nHighly correlated pairs (>=0.80) — limited diversification:",
                      file=sys.stderr)
                for sym_a, sym_b, value in high_pairs[:20]:
                    print(f"  {sym_a} ~ {sym_b}: {value:.2f}", file=sys.stderr)
            else:
                print("No highly correlated pairs found (good diversification).",
                      file=sys.stderr)


if __name__ == "__main__":
    main()
