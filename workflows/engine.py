"""
workflows/engine.py
-------------------

A small, dynamic, config-driven workflow engine for the Polish Funds Analyzer.

A *workflow* is a spec (dict, or YAML/JSON file) listing ordered *steps*::

    name: my pipeline
    steps:
      - action: screen
        params: {max_funds: 100, benchmark: wig}
      - action: filter
        params: {recommendation: [Buy], min_score: 70}
      - action: alert
        params: {}
      - action: export
        params: {format: [csv, html], output: results}

Each step is a registered callable ``fn(ctx, params)`` that reads/writes a
shared :class:`WorkflowContext`. New steps can be added from anywhere with the
``@register_step("name")`` decorator, so workflows are extensible without
touching the engine.

A **demo mode** generates synthetic screening data so an entire pipeline can run
without any network access (used by the test suite).

This module reuses the real building blocks from the project:
``FundAnalyzer`` (analyze_polish_funds), plus the ``rebalancing`` and
``alerts`` modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from analyze_polish_funds import FundAnalyzer, FundMetrics

# Registry of step name -> callable(ctx, params) -> ctx
STEP_REGISTRY: Dict[str, Callable[["WorkflowContext", dict], "WorkflowContext"]] = {}


def register_step(name: str) -> Callable:
    """Decorator registering a function as a workflow step under ``name``."""
    def decorator(fn: Callable) -> Callable:
        STEP_REGISTRY[name] = fn
        return fn
    return decorator


@dataclass
class WorkflowContext:
    """Mutable state threaded through every step of a workflow run."""
    analyzer: FundAnalyzer
    demo: bool = False
    # Step outputs keyed by name; 'funds' holds the working screen DataFrame
    results: Dict[str, Any] = field(default_factory=dict)
    # Raw FundMetrics from the screen step (used by the alert step)
    metrics: List[FundMetrics] = field(default_factory=list)
    # (positions, summary) from the portfolio step
    portfolio: Optional[tuple] = None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_metrics(n: int, seed: int = 42) -> List[FundMetrics]:
    """Synthetic FundMetrics so workflows run without network access."""
    rng = np.random.default_rng(seed)
    analyzer = FundAnalyzer(use_cache=False)
    out: List[FundMetrics] = []
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
        )
        rec, score = analyzer.assign_recommendation(m)
        m.recommendation, m.score = rec, score
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@register_step("screen")
def step_screen(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Screen funds (or generate synthetic results in demo mode)."""
    max_funds = int(params.get("max_funds", 50) or 0)
    if ctx.demo:
        metrics = _demo_metrics(max_funds if max_funds > 0 else 30)
    else:
        if params.get("benchmark"):
            ctx.analyzer.set_benchmark(params["benchmark"])
        funds = ctx.analyzer.get_fund_list()
        if max_funds > 0:
            funds = funds[:max_funds]
        metrics = ctx.analyzer.analyze_funds(
            funds, max_workers=int(params.get("workers", 10))
        )
    ctx.metrics = metrics
    ctx.results["funds"] = ctx.analyzer.create_summary_dataframe(metrics)
    return ctx


@register_step("filter")
def step_filter(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Filter the working fund set by recommendation and/or minimum score."""
    df = ctx.results.get("funds")
    if df is None or df.empty:
        return ctx
    out = df
    recs = params.get("recommendation")
    if recs:
        recs = recs if isinstance(recs, list) else [recs]
        out = out[out["recommendation"].isin(recs)]
    min_score = params.get("min_score")
    if min_score is not None:
        out = out[out["score"] >= float(min_score)]
    ctx.results["funds"] = out.reset_index(drop=True)
    return ctx


@register_step("portfolio")
def step_portfolio(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Value a holdings file into positions and a summary."""
    path = params.get("path") or params.get("file")
    if not path:
        return ctx
    holdings = ctx.analyzer.load_portfolio(path)
    positions, summary = ctx.analyzer.analyze_portfolio(holdings)
    ctx.portfolio = (positions, summary)
    ctx.results["portfolio_summary"] = summary
    return ctx


@register_step("rebalance")
def step_rebalance(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Compute rebalancing orders for the loaded portfolio toward targets."""
    import rebalancing

    if ctx.portfolio is None:
        return ctx
    positions, _ = ctx.portfolio
    targets = params.get("target_weights", {})
    orders = rebalancing.compute_rebalance(
        positions, targets,
        drift_threshold=float(params.get("drift_threshold", 0.0)),
        cash=float(params.get("cash", 0.0)),
    )
    ctx.results["rebalance"] = orders
    return ctx


@register_step("alert")
def step_alert(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Evaluate alert rules over the screened funds."""
    import alerts

    rules = alerts.DEFAULT_RULES
    if params.get("rules_file"):
        rules = alerts.load_rules(params["rules_file"])
    ctx.results["alerts"] = alerts.evaluate_rules(ctx.metrics, rules)
    return ctx


@register_step("project_fees")
def step_project_fees(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Project fee drag on a given amount (or the loaded portfolio value)."""
    amount = float(params.get("amount", 0) or 0)
    if not amount and ctx.portfolio is not None:
        _, summary = ctx.portfolio
        amount = summary.get("total_value") or 0
    ctx.results["fee_projection"] = FundAnalyzer.project_fee_drag(
        amount,
        float(params.get("ter", 0.0)),
        int(params.get("years", 10)),
        float(params.get("gross_return", 0.06)),
    )
    return ctx


@register_step("export")
def step_export(ctx: WorkflowContext, params: dict) -> WorkflowContext:
    """Export the working fund set to one or more formats."""
    df = ctx.results.get("funds")
    if df is None:
        return ctx
    out = params.get("output", "workflow_output")
    for fmt in params.get("format", ["csv"]):
        path = f"{out}.{fmt}"
        if fmt == "csv":
            ctx.analyzer.export_to_csv(df, path)
        elif fmt == "json":
            ctx.analyzer.export_to_json(df, path)
        elif fmt == "excel":
            ctx.analyzer.export_to_excel(df, path)
        elif fmt == "html":
            ctx.analyzer.export_to_html(df, path)
    return ctx


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_workflow(spec: dict, analyzer: Optional[FundAnalyzer] = None,
                 demo: bool = False) -> WorkflowContext:
    """
    Execute a workflow spec and return the final context.

    Parameters
    ----------
    spec : dict
        ``{"name": ..., "steps": [{"action": str, "params": dict}, ...]}``.
    analyzer : FundAnalyzer, optional
        Reused across steps; created if not supplied.
    demo : bool
        Run with synthetic data (no network).

    Raises
    ------
    ValueError
        If a step names an unregistered action.
    """
    if analyzer is None:
        analyzer = FundAnalyzer(use_cache=not demo)
    ctx = WorkflowContext(analyzer=analyzer, demo=demo)

    for step in spec.get("steps", []):
        action = step.get("action")
        params = step.get("params", {}) or {}
        fn = STEP_REGISTRY.get(action)
        if fn is None:
            raise ValueError(
                f"Unknown workflow action: {action!r}. "
                f"Available: {sorted(STEP_REGISTRY)}"
            )
        fn(ctx, params)

    return ctx


def load_and_run(path: str, analyzer: Optional[FundAnalyzer] = None,
                 demo: bool = False) -> WorkflowContext:
    """Load a workflow spec from a YAML or JSON file and run it."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml  # optional dependency
        spec = yaml.safe_load(text)
    else:
        spec = json.loads(text)
    return run_workflow(spec, analyzer=analyzer, demo=demo)
