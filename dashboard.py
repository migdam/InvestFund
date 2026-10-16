"""
dashboard.py
------------

Interactive Streamlit dashboard for the Polish Funds Analyzer.

It wraps the analyzer in ``analyze_polish_funds`` to provide:

- **Fund Screener** — screen funds with live data, filter/sort the results,
  view charts, add optional benchmark-relative metrics, download data.
- **Portfolio Tracker** — load a holdings file, see value/P&L/allocation, and a
  fee-drag projection.

Data sources: **analizy.pl** (Polish TFI funds, the default), **Stooq** (needs
an API key) and, for the screener, **Demo**, which generates synthetic funds so
the UI works without network access. Live screening runs the CLI's own code
(``screen_funds``): each fund is fetched once, in parallel, and cached on disk
for a day.

Run with::

    streamlit run dashboard.py

Requires ``streamlit`` (``pip install streamlit``) in addition to the base
project dependencies.

This tool is for informational and educational purposes only and is not
investment advice.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from analyze_polish_funds import (
    STOOQ_APIKEY_ENV,
    FundAnalyzer,
    FundMetrics,
    _percentile_rank,
    build_quote_source,
    load_symbols_file,
    parse_symbols,
    prefetch_analizy,
    screen_funds,
)

# Percentage-valued columns shared across formatting helpers
PCT_COLUMNS = [
    "return_1m", "return_3m", "return_6m", "return_1y", "return_ytd",
    "volatility", "max_drawdown", "var_95", "cvar_95",
]

# Data sources as offered in the sidebar
SOURCES = {
    "analizy": "analizy.pl (Polish TFI funds)",
    "stooq": "Stooq (needs an API key)",
    "demo": "Demo (synthetic data)",
}
SOURCE_NAMES = {"analizy": "analizy.pl", "stooq": "Stooq"}
EXAMPLE_SYMBOLS = {"analizy": "ING35", "stooq": "1006.N"}

# The screener starts with these analizy.pl symbols (each verified live)
DEFAULT_SYMBOLS_FILE = Path(__file__).resolve().with_name("test_symbols_analizy.txt")


# ---------------------------------------------------------------------------
# Data helpers (pure / cached)
# ---------------------------------------------------------------------------

def _demo_screening_results(n: int, seed: int = 42) -> list:
    """Build synthetic FundMetrics so the dashboard works without network."""
    rng = np.random.default_rng(seed)
    analyzer = FundAnalyzer(use_cache=False)
    results = []
    for i in range(n):
        m = FundMetrics(
            symbol=f"DEMO{i:03d}.N",
            name=f"Demo Fund {i + 1}",
            return_1m=float(rng.normal(0.01, 0.04)),
            return_3m=float(rng.normal(0.03, 0.07)),
            return_6m=float(rng.normal(0.06, 0.10)),
            return_1y=float(rng.normal(0.10, 0.18)),
            return_ytd=float(rng.normal(0.05, 0.12)),
            volatility=float(abs(rng.normal(0.15, 0.06))),
            sharpe_ratio=float(rng.normal(1.0, 0.8)),
            sortino_ratio=float(rng.normal(1.4, 1.0)),
            max_drawdown=float(-abs(rng.normal(0.15, 0.08))),
            calmar_ratio=float(rng.normal(0.8, 0.6)),
            skewness=float(rng.normal(0, 0.5)),
            kurtosis=float(abs(rng.normal(3, 1))),
            var_95=float(-abs(rng.normal(0.02, 0.01))),
            cvar_95=float(-abs(rng.normal(0.03, 0.01))),
        )
        rec, score = analyzer.assign_recommendation(m)
        m.recommendation = rec
        m.score = score
        results.append(m)

    scores = [m.score for m in results]
    for m in results:
        m.percentile_rank = _percentile_rank(scores, m.score)
    return results


def run_screening(source: str, symbols: tuple, max_funds: int, workers: int,
                  use_cache: bool, benchmark: str = "",
                  stooq_apikey: str = "") -> pd.DataFrame:
    """
    Screen funds (or simulate it) and return the summary DataFrame, best first.

    Live sources run the CLI's ``screen_funds``; an empty ``symbols`` means
    Stooq's listing page. Not memoized: the results stay in session state, so
    this runs only when asked to, and the disk cache already spares repeat
    downloads for a day.
    """
    if source == "demo":
        results = _demo_screening_results(max_funds if max_funds > 0 else 30)
        return FundAnalyzer(use_cache=False).create_summary_dataframe(results)

    analyzer = FundAnalyzer(use_cache=use_cache, quote_source=build_quote_source(source),
                            stooq_apikey=stooq_apikey or None)
    if benchmark:
        analyzer.set_benchmark(benchmark)
    results = screen_funds(analyzer, source, list(symbols) or None, max_funds, workers)
    if not results:
        return pd.DataFrame()
    return analyzer.create_summary_dataframe(results)


# Memoized because the portfolio view recomputes on every rerun (each slider
# move); the TTL lets a long-running dashboard pick up new prices.
@st.cache_data(show_spinner=False, ttl=3600)
def run_portfolio(file_bytes: bytes, filename: str, source: str = "analizy",
                  use_cache: bool = True, stooq_apikey: str = "") -> tuple:
    """Value a portfolio from uploaded holdings file bytes."""
    analyzer = FundAnalyzer(use_cache=use_cache, quote_source=build_quote_source(source),
                            stooq_apikey=stooq_apikey or None)

    # load_portfolio reads a path and picks the format from its suffix
    suffix = ".json" if filename.lower().endswith(".json") else ".csv"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"holdings{suffix}"
        path.write_bytes(file_bytes)
        holdings = analyzer.load_portfolio(str(path))

    if source == "analizy":
        # Fetch every holding up front, in parallel, as the CLI does
        prefetch_analizy(analyzer, dict.fromkeys(h.symbol for h in holdings))
    positions, summary = analyzer.analyze_portfolio(holdings)
    df = pd.DataFrame([asdict(p) for p in positions])
    return df, summary


def fee_projection(value: float, ter: float, years: int, gross: float) -> dict:
    """Thin wrapper around FundAnalyzer.project_fee_drag for caching-free calls."""
    return FundAnalyzer.project_fee_drag(value, ter, years, gross)


def _default_symbols(source: str) -> str:
    """Initial content of the symbols box: the verified analizy.pl list."""
    if source == "analizy" and DEFAULT_SYMBOLS_FILE.exists():
        return "\n".join(load_symbols_file(str(DEFAULT_SYMBOLS_FILE)))
    return ""


def _fill_symbols_from_upload(upload_key: str, box_key: str) -> None:
    """file_uploader callback: replace the symbols box with the file's symbols."""
    uploaded = st.session_state.get(upload_key)
    if uploaded is None:
        return
    try:
        symbols = parse_symbols(uploaded.getvalue().decode("utf-8-sig"))
    except ValueError as exc:  # bad JSON or not text
        st.session_state[f"{upload_key}_error"] = f"Could not read {uploaded.name}: {exc}"
        return
    st.session_state[box_key] = "\n".join(symbols)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with human-friendly percentage/ratio formatting."""
    out = df.copy()
    for col in PCT_COLUMNS:
        if col in out.columns:
            out[col] = out[col].apply(lambda x: f"{x * 100:.2f}%" if pd.notna(x) else "—")
    for col in ["sharpe_ratio", "sortino_ratio", "calmar_ratio", "beta", "alpha",
                "information_ratio", "up_capture", "down_capture", "skewness", "kurtosis"]:
        if col in out.columns:
            out[col] = out[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
    if "score" in out.columns:
        out["score"] = out["score"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
    if "percentile_rank" in out.columns:
        out["percentile_rank"] = out["percentile_rank"].apply(
            lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
    return out


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _stooq_apikey_input(key: str) -> str:
    """Password box for the Stooq API key (empty: the STOOQ_APIKEY env var)."""
    apikey = st.text_input(
        "Stooq API key", type="password", key=key,
        help="Stooq's CSV downloads need a key (one-time captcha at "
             "https://stooq.pl/q/d/?s=wig&get_apikey). Leave empty to use "
             f"the {STOOQ_APIKEY_ENV} environment variable.")
    if not apikey.strip() and not os.environ.get(STOOQ_APIKEY_ENV):
        st.caption("No API key set: Stooq will refuse the downloads.")
    return apikey.strip()


def _symbols_input(source: str) -> list:
    """Symbols box plus file upload for a live source; returns the symbols."""
    box_key, upload_key = f"symbols_{source}", f"symbols_file_{source}"
    if box_key not in st.session_state:
        st.session_state[box_key] = _default_symbols(source)
    hint = "" if source == "analizy" else " Leave empty to use Stooq's fund listing."
    st.text_area("Fund symbols", key=box_key, height=160,
                 help=f"One per line, e.g. {EXAMPLE_SYMBOLS[source]}; lines starting "
                      f"with # are ignored.{hint}")
    st.file_uploader("…or load them from a file", type=["txt", "json"], key=upload_key,
                     on_change=_fill_symbols_from_upload, args=(upload_key, box_key),
                     help="One symbol per line or a JSON list, as for the CLI's "
                          "--symbols-file.")
    error = st.session_state.pop(f"{upload_key}_error", None)
    if error:
        st.error(error)
    try:
        # Each symbol once, in the order given
        return list(dict.fromkeys(parse_symbols(st.session_state[box_key])))
    except ValueError as exc:
        st.error(f"Could not read the symbols: {exc}")
        return []


def _report_missing(df: pd.DataFrame, run: dict) -> None:
    """Name the requested symbols that are not in the results."""
    symbols, limit = run["symbols"], run["max_funds"]
    analyzed = set(df["symbol"]) if not df.empty else set()
    tried = symbols
    if 0 < limit < len(symbols):
        # Symbols are fetched in order until `limit` resolve: every one before
        # the last analyzed symbol was tried, later ones perhaps not.
        last = max((symbols.index(s) for s in analyzed), default=-1)
        tried = symbols[:last + 1]
        st.caption(f"Max funds is {limit}: symbols were checked in order until "
                   f"{limit} resolved; later ones were not requested.")
    missing = [s for s in tried if s not in analyzed]
    if missing:
        st.warning(f"No results for {len(missing)} symbol(s): {', '.join(missing)} "
                   "(unknown symbol, failed download, or fewer than 20 quotes).")


def render_screener():
    st.header("📊 Fund Screener")

    with st.sidebar:
        st.subheader("Screening settings")
        source = st.radio("Data source", list(SOURCES), format_func=SOURCES.get,
                          key="source")
        live = source != "demo"
        apikey, symbols = "", []
        if source == "stooq":
            apikey = _stooq_apikey_input("stooq_apikey")
        if live:
            symbols = _symbols_input(source)
        max_funds = st.number_input("Max funds (0 = all)", min_value=0, value=30, step=10,
                                    key="max_funds")
        workers = st.slider("Parallel workers", 1, 20, 10, disabled=not live,
                            help="At most this many downloads at a time.")
        benchmark = st.text_input("Benchmark (optional)", value="", disabled=not live,
                                  help="A fund or index from the same data source "
                                       "(analizy.pl: a fund code; Stooq: e.g. 'wig'). "
                                       "Adds beta, alpha and other relative metrics.")
        use_cache = st.checkbox("Use cache", value=True, disabled=not live,
                                help="Reuse quotes downloaded in the last 24 hours.")
        run = st.button("Run analysis", type="primary", key="run_screen")
    # What the results depend on (workers and cache only change the speed)
    settings = (source, tuple(symbols), int(max_funds), benchmark.strip())

    # Demo data is generated locally, so it is shown right away; live data is
    # downloaded only when asked for.
    if run or (not live and "screen_df" not in st.session_state):
        if source == "analizy" and not symbols:
            st.warning("Enter at least one analizy.pl fund symbol in the sidebar.")
            return
        label = (f"Fetching quotes from {SOURCE_NAMES[source]} and analyzing…" if live
                 else "Generating demo data…")
        with st.spinner(label):
            try:
                df = run_screening(source, tuple(symbols), int(max_funds), int(workers),
                                   bool(use_cache), benchmark.strip(), apikey)
            except Exception as exc:  # network/parse failures shouldn't crash UI
                st.error(f"Analysis failed: {exc}")
                return
        st.session_state.screen_df = df
        st.session_state.screen_run = {"source": source, "symbols": symbols,
                                       "max_funds": int(max_funds), "settings": settings}

    if "screen_df" not in st.session_state:
        st.info(f"Check the fund symbols in the sidebar, then press **Run analysis** "
                f"to fetch live data from {SOURCE_NAMES[source]}.")
        return

    df = st.session_state.screen_df
    shown = st.session_state.screen_run
    if shown["source"] == "demo":
        st.caption("⚠️ Showing **synthetic demo data** — choose analizy.pl as the "
                   "data source for live data.")
    else:
        st.caption(f"Live data from {SOURCE_NAMES[shown['source']]}.")
        _report_missing(df, shown)
    if shown["settings"] != settings:
        st.info("Settings changed: press **Run analysis** to update these results.")

    if df.empty:
        st.info("No results. Adjust settings and run the analysis.")
        return

    # Summary metric cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Funds", len(df))
    c2.metric("Buy", int((df["recommendation"] == "Buy").sum()))
    c3.metric("Hold", int((df["recommendation"] == "Hold").sum()))
    c4.metric("Sell", int((df["recommendation"] == "Sell").sum()))

    # Filters
    with st.expander("Filters", expanded=True):
        fc1, fc2 = st.columns(2)
        recs = fc1.multiselect("Recommendation", ["Buy", "Hold", "Sell"],
                               default=["Buy", "Hold", "Sell"])
        min_score = fc2.slider("Minimum score", 0, 100, 0)

    filtered = df[df["recommendation"].isin(recs) & (df["score"] >= min_score)]

    # Table
    st.subheader(f"Results ({len(filtered)})")
    st.dataframe(format_display(filtered), width='stretch', hide_index=True)

    # Download buttons
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ CSV", filtered.to_csv(index=False).encode("utf-8"),
                       "funds_analysis.csv", "text/csv")
    d2.download_button("⬇️ JSON",
                       filtered.to_json(orient="records", indent=2).encode("utf-8"),
                       "funds_analysis.json", "application/json")

    # Charts
    st.subheader("Charts")
    ch1, ch2 = st.columns(2)
    with ch1:
        st.caption("Recommendation breakdown")
        counts = filtered["recommendation"].value_counts()
        st.bar_chart(counts)
    with ch2:
        st.caption("Risk vs return (1Y)")
        scatter = filtered.dropna(subset=["volatility", "return_1y"])
        if not scatter.empty:
            chart_df = pd.DataFrame({
                "Volatility": scatter["volatility"] * 100,
                "Return 1Y": scatter["return_1y"] * 100,
            })
            st.scatter_chart(chart_df, x="Volatility", y="Return 1Y")
        else:
            st.info("Not enough data for scatter plot.")

    st.caption("Score distribution")
    if not filtered.empty:
        score_hist = pd.cut(filtered["score"], bins=10).value_counts().sort_index()
        # Interval labels aren't chart-serializable; render as strings
        score_hist.index = score_hist.index.astype(str)
        st.bar_chart(score_hist.rename("count"))


def render_portfolio():
    st.header("💼 Portfolio Tracker")

    with st.sidebar:
        st.subheader("Portfolio settings")
        source = st.radio("Price source", ["analizy", "stooq"], format_func=SOURCES.get,
                          key="pf_source")
        apikey = _stooq_apikey_input("pf_apikey") if source == "stooq" else ""
        use_cache = st.checkbox("Use cache", value=True, key="pf_cache")
        years = st.slider("Projection horizon (years)", 1, 40, 10)
        gross = st.slider("Assumed gross annual return", 0.0, 0.15, 0.06, 0.01)

    st.write("Upload a holdings file (JSON or CSV with "
             "`symbol, shares, cost_basis[, ter, name]`), using "
             f"{SOURCE_NAMES[source]} symbols such as `{EXAMPLE_SYMBOLS[source]}`.")
    uploaded = st.file_uploader("Holdings file", type=["json", "csv"])

    if uploaded is None:
        st.info("Upload a holdings file to value your portfolio. "
                "See `sample_portfolio.json` in the repo for the format.")
        return

    try:
        with st.spinner(f"Fetching prices from {SOURCE_NAMES[source]}…"):
            df, summary = run_portfolio(uploaded.getvalue(), uploaded.name, source=source,
                                        use_cache=bool(use_cache), stooq_apikey=apikey)
    except Exception as exc:
        st.error(f"Could not process portfolio: {exc}")
        return

    if summary["num_priced"] == 0:
        st.warning(f"None of the holdings could be priced from {SOURCE_NAMES[source]} "
                   "(network blocked or unknown symbols). Showing holdings without "
                   "valuation.")
        st.dataframe(df, width='stretch', hide_index=True)
        return
    unpriced = list(dict.fromkeys(df.loc[df["current_value"].isna(), "symbol"]))
    if unpriced:
        st.warning(f"No price from {SOURCE_NAMES[source]} for: {', '.join(unpriced)} "
                   "(excluded from the totals).")

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total value", f"{summary['total_value']:,.0f}")
    c2.metric("Total cost", f"{summary['total_cost']:,.0f}")
    pnl = summary["total_pnl"] or 0.0
    pnl_pct = (summary["total_pnl_pct"] or 0.0) * 100
    c3.metric("Unrealized P&L", f"{pnl:,.0f}", f"{pnl_pct:.2f}%")
    wr = summary["weighted_return_1y"]
    c4.metric("Wtd 1Y return", f"{wr * 100:.2f}%" if wr is not None else "—")

    # Positions table
    st.subheader("Positions")
    st.dataframe(df, width='stretch', hide_index=True)

    # Allocation
    priced = df.dropna(subset=["current_value"])
    if not priced.empty:
        st.subheader("Allocation")
        alloc = priced.set_index("symbol")["current_value"]
        st.bar_chart(alloc)

    # Fee-drag projection
    st.subheader("Fee-drag projection")
    fee_rows = priced.dropna(subset=["ter"]) if "ter" in priced.columns else pd.DataFrame()
    if not fee_rows.empty and summary["total_value"]:
        weighted_ter = float(
            (fee_rows["ter"] * fee_rows["current_value"]).sum()
            / fee_rows["current_value"].sum()
        )
        proj = fee_projection(summary["total_value"], weighted_ter, int(years), float(gross))
        st.caption(f"Avg TER {weighted_ter * 100:.2f}% · {years} yrs @ "
                   f"{gross * 100:.1f}% gross")
        p1, p2, p3 = st.columns(3)
        p1.metric("Without fees", f"{proj['gross_value']:,.0f}")
        p2.metric("With fees", f"{proj['net_value']:,.0f}")
        p3.metric("Lost to fees", f"{proj['total_fees']:,.0f}",
                  f"-{proj['drag_pct'] * 100:.1f}%", delta_color="inverse")
    else:
        st.info("Add a `ter` (expense ratio) to your holdings to see the "
                "fee-drag projection.")


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Polish Funds Analyzer", page_icon="📈",
                       layout="wide")
    st.title("📈 Polish Funds Analyzer")

    view = st.sidebar.radio("View", ["Fund Screener", "Portfolio Tracker"])
    st.sidebar.divider()

    if view == "Fund Screener":
        render_screener()
    else:
        render_portfolio()

    st.sidebar.divider()
    st.sidebar.caption(
        "For informational/educational use only. Not investment advice."
    )


if __name__ == "__main__":
    main()
