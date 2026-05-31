"""
dashboard.py
------------

Interactive Streamlit dashboard for the Polish Funds Analyzer.

It wraps the :class:`FundAnalyzer` from ``analyze_polish_funds`` to provide:

- **Fund Screener** — run the analysis, filter/sort results, view charts,
  optional benchmark-relative metrics and a correlation heatmap, download data.
- **Portfolio Tracker** — load a holdings file, see value/P&L/allocation, and a
  fee-drag projection.

A **Demo mode** generates synthetic data so the UI is fully usable without any
network access (handy for trying it out or when Stooq is unreachable).

Run with::

    streamlit run dashboard.py

Requires ``streamlit`` (``pip install streamlit``) in addition to the base
project dependencies.

This tool is for informational and educational purposes only and is not
investment advice.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd
import streamlit as st

from analyze_polish_funds import FundAnalyzer, FundMetrics

# Percentage-valued columns shared across formatting helpers
PCT_COLUMNS = [
    "return_1m", "return_3m", "return_6m", "return_1y", "return_ytd",
    "volatility", "max_drawdown", "var_95", "cvar_95",
]


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

    from scipy import stats as _stats
    scores = [m.score for m in results]
    for m in results:
        m.percentile_rank = float(_stats.percentileofscore(scores, m.score))
    return results


@st.cache_data(show_spinner=False)
def run_screening(max_funds: int, workers: int, use_cache: bool,
                  benchmark: str, demo: bool) -> pd.DataFrame:
    """Run (or simulate) the fund screening and return a summary DataFrame."""
    analyzer = FundAnalyzer(use_cache=use_cache)

    if demo:
        results = _demo_screening_results(max_funds if max_funds > 0 else 30)
        return analyzer.create_summary_dataframe(results)

    if benchmark:
        analyzer.set_benchmark(benchmark)
    funds = analyzer.get_fund_list()
    if max_funds > 0:
        funds = funds[:max_funds]
    results = analyzer.analyze_funds(funds, max_workers=workers)
    return analyzer.create_summary_dataframe(results)


@st.cache_data(show_spinner=False)
def run_portfolio(file_bytes: bytes, filename: str, use_cache: bool) -> tuple:
    """Value a portfolio from uploaded holdings file bytes."""
    analyzer = FundAnalyzer(use_cache=use_cache)

    suffix = ".json" if filename.lower().endswith(".json") else ".csv"
    tmp_path = f".portfolio_upload{suffix}"
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)

    holdings = analyzer.load_portfolio(tmp_path)
    positions, summary = analyzer.analyze_portfolio(holdings)
    df = pd.DataFrame([asdict(p) for p in positions])
    return df, summary


def fee_projection(value: float, ter: float, years: int, gross: float) -> dict:
    """Thin wrapper around FundAnalyzer.project_fee_drag for caching-free calls."""
    return FundAnalyzer.project_fee_drag(value, ter, years, gross)


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

def render_screener():
    st.header("📊 Fund Screener")

    with st.sidebar:
        st.subheader("Screening settings")
        demo = st.toggle("Demo mode (synthetic data)", value=True,
                         help="Generate synthetic funds so the dashboard works "
                              "without network access.")
        max_funds = st.number_input("Max funds (0 = all)", min_value=0, value=30, step=10)
        workers = st.slider("Parallel workers", 1, 20, 10, disabled=demo)
        benchmark = st.text_input("Benchmark ticker (optional)", value="",
                                  disabled=demo,
                                  help="e.g. 'wig' to add beta/alpha/etc.")
        use_cache = st.checkbox("Use cache", value=True, disabled=demo)
        run = st.button("Run analysis", type="primary")

    if run or "screen_df" not in st.session_state:
        with st.spinner("Analyzing funds…"):
            try:
                st.session_state.screen_df = run_screening(
                    int(max_funds), int(workers), bool(use_cache),
                    benchmark.strip(), bool(demo),
                )
                st.session_state.screen_demo = demo
            except Exception as exc:  # network/parse failures shouldn't crash UI
                st.error(f"Analysis failed: {exc}")
                return

    df = st.session_state.get("screen_df")
    if df is None or df.empty:
        st.info("No results. Adjust settings and run the analysis.")
        return

    if st.session_state.get("screen_demo"):
        st.caption("⚠️ Showing **synthetic demo data** — turn off Demo mode for live Stooq data.")

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
        use_cache = st.checkbox("Use cache", value=True, key="pf_cache")
        years = st.slider("Projection horizon (years)", 1, 40, 10)
        gross = st.slider("Assumed gross annual return", 0.0, 0.15, 0.06, 0.01)

    st.write("Upload a holdings file (JSON or CSV with "
             "`symbol, shares, cost_basis[, ter, name]`).")
    uploaded = st.file_uploader("Holdings file", type=["json", "csv"])

    if uploaded is None:
        st.info("Upload a holdings file to value your portfolio. "
                "See `sample_portfolio.json` in the repo for the format.")
        return

    try:
        df, summary = run_portfolio(uploaded.getvalue(), uploaded.name, bool(use_cache))
    except Exception as exc:
        st.error(f"Could not process portfolio: {exc}")
        return

    if summary["num_priced"] == 0:
        st.warning("None of the holdings could be priced (network blocked or "
                   "unknown tickers). Showing holdings without valuation.")
        st.dataframe(df, width='stretch', hide_index=True)
        return

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
