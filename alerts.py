"""Rule-based alert engine for FundMetrics objects.

This is a self-contained module that evaluates simple comparison rules
against :class:`FundMetrics` instances (as produced by
``analyze_polish_funds.py``) and emits :class:`Alert` records.

The engine is deliberately dependency-light: it only relies on the
standard library so it can be imported and tested without any network
access or third-party packages.

Typical usage
-------------
>>> from analyze_polish_funds import FundMetrics
>>> from alerts import evaluate_rules, DEFAULT_RULES, summarize_alerts
>>> metrics = [FundMetrics(symbol="ABC", name="Bad Fund", score=10.0)]
>>> alerts = evaluate_rules(metrics, DEFAULT_RULES)
>>> summarize_alerts(alerts)
{'info': 0, 'warning': ..., 'critical': ...}
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

#: Mapping of operator strings to their callable implementations.
_OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class AlertRule:
    """A single condition evaluated against a :class:`FundMetrics` field.

    Parameters
    ----------
    field : str
        Name of the ``FundMetrics`` attribute to inspect (numeric or the
        string ``recommendation`` field).
    op : str
        Comparison operator, one of ``"<"``, ``"<="``, ``">"``, ``">="``,
        ``"=="`` or ``"!="``.
    threshold : Any
        Value the field is compared against.
    severity : str
        One of ``"info"``, ``"warning"`` or ``"critical"``. Defaults to
        ``"warning"``.
    message : Optional[str]
        Optional message template. May reference ``{symbol}``, ``{name}``,
        ``{field}``, ``{value}``, ``{op}`` and ``{threshold}``.
    """

    field: str
    op: str
    threshold: Any
    severity: str = "warning"
    message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.op not in _OPERATORS:
            raise ValueError(
                f"Unsupported operator {self.op!r}; "
                f"expected one of {sorted(_OPERATORS)}"
            )

    def describe(self) -> str:
        """Return a short human-readable form of the rule, e.g. ``score < 40``."""
        return f"{self.field} {self.op} {self.threshold}"


@dataclass
class Alert:
    """A fired alert for a particular fund / rule combination."""

    symbol: str
    name: str
    field: str
    rule: str
    value: Any
    severity: str
    message: str


# ---------------------------------------------------------------------------
# Safe comparison helper
# ---------------------------------------------------------------------------
def safe_compare(value: Any, op: str, threshold: Any) -> bool:
    """Compare ``value`` to ``threshold`` using ``op`` without raising.

    Returns ``False`` (rather than raising) when:

    * ``value`` is ``None`` (a missing metric never triggers an alert),
    * ``op`` is not a recognised operator,
    * the comparison itself raises a :class:`TypeError` (incompatible types,
      e.g. comparing a string field with ``<`` against a number).

    String equality / inequality (``==`` / ``!=``) is always safe and is the
    intended path for the ``recommendation`` field.
    """
    if value is None:
        return False

    func = _OPERATORS.get(op)
    if func is None:
        return False

    try:
        return bool(func(value, threshold))
    except TypeError:
        # Incompatible types (e.g. ordering a str against a number) -> skip.
        return False


# ---------------------------------------------------------------------------
# Message rendering
# ---------------------------------------------------------------------------
def _render_message(rule: AlertRule, metric: Any, value: Any) -> str:
    """Render the alert message for ``rule`` against ``metric``.

    Falls back to a sensible default message when ``rule.message`` is not set,
    and degrades gracefully if a template references an unknown placeholder.
    """
    context = {
        "symbol": getattr(metric, "symbol", ""),
        "name": getattr(metric, "name", ""),
        "field": rule.field,
        "value": value,
        "op": rule.op,
        "threshold": rule.threshold,
    }

    if rule.message:
        try:
            return rule.message.format(**context)
        except (KeyError, IndexError, ValueError):
            # Bad template -> fall through to the default below.
            pass

    return (
        f"[{rule.severity.upper()}] {context['symbol']}: "
        f"{rule.field}={value} {rule.op} {rule.threshold}"
    )


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------
def evaluate_rules(metrics_list: List[Any], rules: List[AlertRule]) -> List[Alert]:
    """Apply every rule in ``rules`` to every metric in ``metrics_list``.

    Parameters
    ----------
    metrics_list : List[FundMetrics]
        The funds to evaluate.
    rules : List[AlertRule]
        The rules to apply.

    Returns
    -------
    List[Alert]
        One :class:`Alert` per (metric, rule) pair whose condition is true.
        A pair is skipped silently when the field is missing (``None``) or
        the field does not exist on the metric.
    """
    alerts: List[Alert] = []

    for metric in metrics_list:
        for rule in rules:
            # Missing attribute -> treat like None and skip.
            value = getattr(metric, rule.field, None)
            if value is None:
                continue

            if safe_compare(value, rule.op, rule.threshold):
                alerts.append(
                    Alert(
                        symbol=getattr(metric, "symbol", ""),
                        name=getattr(metric, "name", ""),
                        field=rule.field,
                        rule=rule.describe(),
                        value=value,
                        severity=rule.severity,
                        message=_render_message(rule, metric, value),
                    )
                )

    return alerts


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------
def summarize_alerts(alerts: List[Alert]) -> Dict[str, int]:
    """Return counts of alerts grouped by severity.

    The returned dict always contains the canonical keys ``"info"``,
    ``"warning"`` and ``"critical"`` (zero-filled), plus any non-standard
    severities that appear in ``alerts``.
    """
    summary: Dict[str, int] = {"info": 0, "warning": 0, "critical": 0}
    for alert in alerts:
        summary[alert.severity] = summary.get(alert.severity, 0) + 1
    return summary


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------
DEFAULT_RULES: List[AlertRule] = [
    AlertRule(
        field="score",
        op="<",
        threshold=40,
        severity="warning",
        message="{symbol}: low composite score ({value} < {threshold}).",
    ),
    AlertRule(
        field="max_drawdown",
        op="<",
        threshold=-0.25,
        severity="critical",
        message="{symbol}: severe drawdown ({value} < {threshold}).",
    ),
    AlertRule(
        field="return_1y",
        op="<",
        threshold=0,
        severity="warning",
        message="{symbol}: negative 1Y return ({value}).",
    ),
    AlertRule(
        field="recommendation",
        op="==",
        threshold="Sell",
        severity="warning",
        message="{symbol}: recommendation is {value}.",
    ),
    AlertRule(
        field="sharpe_ratio",
        op="<",
        threshold=0,
        severity="warning",
        message="{symbol}: negative Sharpe ratio ({value}).",
    ),
]


# ---------------------------------------------------------------------------
# Optional JSON rule loading
# ---------------------------------------------------------------------------
def load_rules(path: str) -> List[AlertRule]:
    """Load a list of :class:`AlertRule` from a JSON file.

    The file must contain a JSON array of objects, each with the keys
    ``field``, ``op`` and ``threshold`` (and optionally ``severity`` and
    ``message``). Unknown keys are ignored.

    Parameters
    ----------
    path : str
        Path to the JSON file.

    Returns
    -------
    List[AlertRule]
    """
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, list):
        raise ValueError("Rules JSON must be a list of rule objects.")

    valid_keys = {f.name for f in dataclass_fields(AlertRule)}
    rules: List[AlertRule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each rule entry must be a JSON object.")
        kwargs = {k: v for k, v in entry.items() if k in valid_keys}
        rules.append(AlertRule(**kwargs))

    return rules
