"""Runnable test suite for alerts.py.

Plain-python tests (no pytest required). Run with::

    python test_alerts.py

Prints ``PASS``/``FAIL`` lines and exits 0 on success, 1 on any failure.
Builds mock FundMetrics objects directly -- no network access required.
"""

import sys

from analyze_polish_funds import FundMetrics
from alerts import (
    Alert,
    AlertRule,
    DEFAULT_RULES,
    evaluate_rules,
    safe_compare,
    summarize_alerts,
)


# ---------------------------------------------------------------------------
# Tiny test harness
# ---------------------------------------------------------------------------
_RESULTS = {"pass": 0, "fail": 0}


def check(name: str, condition: bool) -> None:
    """Record and print the result of a single assertion."""
    if condition:
        _RESULTS["pass"] += 1
        print(f"PASS: {name}")
    else:
        _RESULTS["fail"] += 1
        print(f"FAIL: {name}")


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def make_bad_fund() -> FundMetrics:
    """An obviously bad fund that should trip most DEFAULT_RULES."""
    return FundMetrics(
        symbol="BAD",
        name="Terrible Fund",
        return_1y=-0.15,
        sharpe_ratio=-0.5,
        max_drawdown=-0.40,
        recommendation="Sell",
        score=12.0,
    )


def make_great_fund() -> FundMetrics:
    """An excellent fund that should trip none of the DEFAULT_RULES."""
    return FundMetrics(
        symbol="GOOD",
        name="Stellar Fund",
        return_1y=0.22,
        sharpe_ratio=1.8,
        max_drawdown=-0.08,
        recommendation="Buy",
        score=88.0,
    )


# ---------------------------------------------------------------------------
# Operator coverage
# ---------------------------------------------------------------------------
def test_operators() -> None:
    fm = FundMetrics(symbol="OP", name="Op Fund", score=50.0)

    check("op < fires", len(evaluate_rules([fm], [AlertRule("score", "<", 60)])) == 1)
    check("op < no fire", len(evaluate_rules([fm], [AlertRule("score", "<", 40)])) == 0)

    check("op <= fires (equal)", len(evaluate_rules([fm], [AlertRule("score", "<=", 50)])) == 1)
    check("op > fires", len(evaluate_rules([fm], [AlertRule("score", ">", 40)])) == 1)
    check("op > no fire", len(evaluate_rules([fm], [AlertRule("score", ">", 60)])) == 0)
    check("op >= fires (equal)", len(evaluate_rules([fm], [AlertRule("score", ">=", 50)])) == 1)
    check("op == fires", len(evaluate_rules([fm], [AlertRule("score", "==", 50)])) == 1)
    check("op == no fire", len(evaluate_rules([fm], [AlertRule("score", "==", 51)])) == 0)
    check("op != fires", len(evaluate_rules([fm], [AlertRule("score", "!=", 51)])) == 1)
    check("op != no fire", len(evaluate_rules([fm], [AlertRule("score", "!=", 50)])) == 0)


def test_invalid_operator_raises() -> None:
    raised = False
    try:
        AlertRule("score", "><", 10)
    except ValueError:
        raised = True
    check("invalid operator raises ValueError", raised)


# ---------------------------------------------------------------------------
# None handling
# ---------------------------------------------------------------------------
def test_none_skipped() -> None:
    # sharpe_ratio defaults to None when not provided.
    fm = FundMetrics(symbol="NONE", name="No Sharpe", score=50.0)
    check("sharpe_ratio is None on fixture", fm.sharpe_ratio is None)

    alerts = evaluate_rules([fm], [AlertRule("sharpe_ratio", "<", 0)])
    check("None field value is skipped", len(alerts) == 0)

    # safe_compare itself must return False for None, not raise.
    check("safe_compare None returns False", safe_compare(None, "<", 0) is False)


def test_missing_field_skipped() -> None:
    fm = FundMetrics(symbol="MISS", name="Missing Field", score=50.0)
    alerts = evaluate_rules([fm], [AlertRule("does_not_exist", "<", 0)])
    check("missing attribute is skipped", len(alerts) == 0)


# ---------------------------------------------------------------------------
# String rule (recommendation)
# ---------------------------------------------------------------------------
def test_recommendation_string_rule() -> None:
    sell = FundMetrics(symbol="S", name="Sell Fund", recommendation="Sell")
    hold = FundMetrics(symbol="H", name="Hold Fund", recommendation="Hold")
    rule = AlertRule("recommendation", "==", "Sell")

    fired = evaluate_rules([sell], [rule])
    check("recommendation==Sell fires", len(fired) == 1)
    check("recommendation==Sell not fired for Hold", len(evaluate_rules([hold], [rule])) == 0)


def test_string_vs_numeric_no_crash() -> None:
    # Ordering a string against a number must not crash; it should skip.
    fm = FundMetrics(symbol="X", name="X", recommendation="Sell")
    alerts = evaluate_rules([fm], [AlertRule("recommendation", "<", 5)])
    check("string < number does not crash and skips", len(alerts) == 0)
    check("safe_compare type mismatch returns False",
          safe_compare("Sell", "<", 5) is False)


# ---------------------------------------------------------------------------
# DEFAULT_RULES behaviour
# ---------------------------------------------------------------------------
def test_default_rules_flag_bad_fund() -> None:
    alerts = evaluate_rules([make_bad_fund()], DEFAULT_RULES)
    fired_fields = {a.field for a in alerts}
    check("bad fund flagged on score", "score" in fired_fields)
    check("bad fund flagged on max_drawdown", "max_drawdown" in fired_fields)
    check("bad fund flagged on return_1y", "return_1y" in fired_fields)
    check("bad fund flagged on recommendation", "recommendation" in fired_fields)
    check("bad fund flagged on sharpe_ratio", "sharpe_ratio" in fired_fields)
    check("bad fund trips all 5 default rules", len(alerts) == 5)


def test_default_rules_leave_great_fund() -> None:
    alerts = evaluate_rules([make_great_fund()], DEFAULT_RULES)
    check("great fund trips no default rules", len(alerts) == 0)


# ---------------------------------------------------------------------------
# summarize_alerts
# ---------------------------------------------------------------------------
def test_summarize() -> None:
    alerts = evaluate_rules([make_bad_fund()], DEFAULT_RULES)
    summary = summarize_alerts(alerts)
    # bad fund: 4 warnings (score, return_1y, recommendation, sharpe) + 1 critical (drawdown).
    check("summary critical count == 1", summary["critical"] == 1)
    check("summary warning count == 4", summary["warning"] == 4)
    check("summary info count == 0", summary["info"] == 0)
    check("summary keys present", set(summary) >= {"info", "warning", "critical"})

    empty = summarize_alerts([])
    check("empty summary zero-filled", empty == {"info": 0, "warning": 0, "critical": 0})


# ---------------------------------------------------------------------------
# Message templating
# ---------------------------------------------------------------------------
def test_message_templating() -> None:
    fm = FundMetrics(symbol="TMPL", name="Template Fund", score=10.0)
    rule = AlertRule(
        "score", "<", 40,
        severity="warning",
        message="{symbol} scored {value}",
    )
    alerts = evaluate_rules([fm], [rule])
    check("template rule fired once", len(alerts) == 1)
    msg = alerts[0].message
    check("template filled {symbol}", "TMPL" in msg)
    check("template filled {value}", "10.0" in msg)
    check("exact templated message", msg == "TMPL scored 10.0")


def test_default_message_when_none() -> None:
    fm = FundMetrics(symbol="DEF", name="Default Msg", score=10.0)
    alerts = evaluate_rules([fm], [AlertRule("score", "<", 40)])
    check("default message present", len(alerts) == 1 and "DEF" in alerts[0].message)


def test_alert_record_shape() -> None:
    fm = FundMetrics(symbol="REC", name="Record Fund", score=5.0)
    alert = evaluate_rules([fm], [AlertRule("score", "<", 40)])[0]
    check("alert is Alert instance", isinstance(alert, Alert))
    check("alert symbol", alert.symbol == "REC")
    check("alert name", alert.name == "Record Fund")
    check("alert field", alert.field == "score")
    check("alert rule text", alert.rule == "score < 40")
    check("alert value", alert.value == 5.0)
    check("alert severity", alert.severity == "warning")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_operators,
        test_invalid_operator_raises,
        test_none_skipped,
        test_missing_field_skipped,
        test_recommendation_string_rule,
        test_string_vs_numeric_no_crash,
        test_default_rules_flag_bad_fund,
        test_default_rules_leave_great_fund,
        test_summarize,
        test_message_templating,
        test_default_message_when_none,
        test_alert_record_shape,
    ]
    for test in tests:
        test()

    print("-" * 50)
    print(f"TOTAL: {_RESULTS['pass']} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
