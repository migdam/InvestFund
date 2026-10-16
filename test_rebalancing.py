"""
Runnable test suite for rebalancing.py.

Uses mock PortfolioPosition objects constructed directly (no network, no
price source). Prints PASS/FAIL lines and exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys

from analyze_polish_funds import PortfolioPosition
from rebalancing import (
    RebalanceOrder,
    compute_rebalance,
    summarize_rebalance,
)

_FAILURES: list[str] = []
_TOL = 1e-6


def _pos(symbol, shares, price, value):
    """Build a minimal PortfolioPosition for testing."""
    return PortfolioPosition(
        symbol=symbol,
        name=symbol,
        shares=shares,
        current_price=price,
        current_value=value,
        cost_basis=0.0,
    )


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        msg = f"FAIL: {name}" + (f" -- {detail}" if detail else "")
        print(msg)
        _FAILURES.append(name)


def approx(a: float, b: float, tol: float = _TOL) -> bool:
    return abs(a - b) <= tol


def order_by_symbol(orders, symbol) -> RebalanceOrder:
    for o in orders:
        if o.symbol == symbol:
            return o
    raise KeyError(symbol)


# ---------------------------------------------------------------------------
# Test: weights validation
# ---------------------------------------------------------------------------
def test_weights_validation():
    positions = [_pos("A", 10, 10.0, 100.0)]
    # Sum too low.
    try:
        compute_rebalance(positions, {"A": 0.5})
        check("validation rejects sum 0.5", False, "no ValueError raised")
    except ValueError:
        check("validation rejects sum 0.5", True)
    # Sum too high.
    try:
        compute_rebalance(positions, {"A": 0.6, "B": 0.6})
        check("validation rejects sum 1.2", False, "no ValueError raised")
    except ValueError:
        check("validation rejects sum 1.2", True)
    # Valid sum (with a None ignored).
    try:
        compute_rebalance(positions, {"A": 1.0, "B": None})
        check("validation accepts sum 1.0 with None", True)
    except ValueError as e:
        check("validation accepts sum 1.0 with None", False, str(e))
    # Edge of band.
    try:
        compute_rebalance(positions, {"A": 0.99})
        check("validation accepts sum 0.99", True)
    except ValueError as e:
        check("validation accepts sum 0.99", False, str(e))


# ---------------------------------------------------------------------------
# Test: basic rebalance math (60/40 -> 50/50)
# ---------------------------------------------------------------------------
def test_basic_rebalance():
    # A: 60 shares @ 1.0 = 60; B: 40 shares @ 1.0 = 40; total = 100.
    positions = [
        _pos("A", 60, 1.0, 60.0),
        _pos("B", 40, 1.0, 40.0),
    ]
    orders = compute_rebalance(positions, {"A": 0.5, "B": 0.5})
    a = order_by_symbol(orders, "A")
    b = order_by_symbol(orders, "B")

    check("A current_weight 0.6", approx(a.current_weight, 0.6))
    check("B current_weight 0.4", approx(b.current_weight, 0.4))
    check("A drift +0.1", approx(a.drift, 0.1))
    check("B drift -0.1", approx(b.drift, -0.1))
    # Target value 50 each: A sells 10, B buys 10.
    check("A trade_value -10", approx(a.trade_value, -10.0))
    check("B trade_value +10", approx(b.trade_value, 10.0))
    check("A action SELL", a.action == "SELL")
    check("B action BUY", b.action == "BUY")
    # Shares: price 1.0 -> shares == trade_value.
    check("A shares_to_trade -10", approx(a.shares_to_trade, -10.0))
    check("B shares_to_trade +10", approx(b.shares_to_trade, 10.0))


# ---------------------------------------------------------------------------
# Test: no-trade band suppresses small drift
# ---------------------------------------------------------------------------
def test_no_trade_band():
    # A: 52, B: 48, total 100 -> drift 0.02 / -0.02 vs 50/50.
    positions = [
        _pos("A", 52, 1.0, 52.0),
        _pos("B", 48, 1.0, 48.0),
    ]
    orders = compute_rebalance(
        positions, {"A": 0.5, "B": 0.5}, drift_threshold=0.05
    )
    a = order_by_symbol(orders, "A")
    b = order_by_symbol(orders, "B")
    check("band: A HOLD", a.action == "HOLD")
    check("band: B HOLD", b.action == "HOLD")
    check("band: A trade_value 0", approx(a.trade_value, 0.0))
    check("band: A shares_to_trade 0", approx(a.shares_to_trade, 0.0))

    # Below-threshold but with a threshold small enough to still trade.
    orders2 = compute_rebalance(
        positions, {"A": 0.5, "B": 0.5}, drift_threshold=0.01
    )
    a2 = order_by_symbol(orders2, "A")
    check("band: A trades when drift >= threshold", a2.action == "SELL")
    check("band: A trade_value -2", approx(a2.trade_value, -2.0))


# ---------------------------------------------------------------------------
# Test: target-only symbol produces a BUY
# ---------------------------------------------------------------------------
def test_target_only_buy():
    positions = [_pos("A", 100, 1.0, 100.0)]
    # New symbol C never held; A 0.5, C 0.5.
    orders = compute_rebalance(positions, {"A": 0.5, "C": 0.5})
    c = order_by_symbol(orders, "C")
    check("target-only C action BUY", c.action == "BUY")
    check("target-only C current_value 0", approx(c.current_value, 0.0))
    check("target-only C trade_value +50", approx(c.trade_value, 50.0))
    # No price known for C -> shares None.
    check("target-only C shares None", c.shares_to_trade is None)


# ---------------------------------------------------------------------------
# Test: held symbol absent from targets -> full SELL
# ---------------------------------------------------------------------------
def test_full_sell():
    positions = [
        _pos("A", 50, 1.0, 50.0),
        _pos("B", 50, 1.0, 50.0),
    ]
    # B absent from targets -> target weight 0 -> sell all.
    orders = compute_rebalance(positions, {"A": 1.0})
    b = order_by_symbol(orders, "B")
    check("full sell: B action SELL", b.action == "SELL")
    check("full sell: B target_weight 0", approx(b.target_weight, 0.0))
    check("full sell: B trade_value -50", approx(b.trade_value, -50.0))
    check("full sell: B shares_to_trade -50", approx(b.shares_to_trade, -50.0))
    a = order_by_symbol(orders, "A")
    check("full sell: A buys to 100", approx(a.trade_value, 50.0))


# ---------------------------------------------------------------------------
# Test: cash deployment
# ---------------------------------------------------------------------------
def test_cash():
    positions = [
        _pos("A", 50, 1.0, 50.0),
        _pos("B", 50, 1.0, 50.0),
    ]
    # Add 100 cash -> total investable 200, target 50/50 -> 100 each.
    orders = compute_rebalance(positions, {"A": 0.5, "B": 0.5}, cash=100.0)
    a = order_by_symbol(orders, "A")
    b = order_by_symbol(orders, "B")
    check("cash: A buys +50", approx(a.trade_value, 50.0))
    check("cash: B buys +50", approx(b.trade_value, 50.0))


# ---------------------------------------------------------------------------
# Test: unpriced position contributes nothing / no share count
# ---------------------------------------------------------------------------
def test_unpriced():
    positions = [
        _pos("A", 100, 1.0, 100.0),
        _pos("U", 5, None, None),  # unpriced
    ]
    orders = compute_rebalance(positions, {"A": 1.0})
    u = order_by_symbol(orders, "U")
    a = order_by_symbol(orders, "A")
    check("unpriced: U current_value 0", approx(u.current_value, 0.0))
    check("unpriced: U shares None", u.shares_to_trade is None)
    # Total investable is only A's 100, already at target.
    check("unpriced: A HOLD", a.action == "HOLD")


# ---------------------------------------------------------------------------
# Test: empty positions
# ---------------------------------------------------------------------------
def test_empty():
    orders = compute_rebalance([], {"A": 1.0})
    a = order_by_symbol(orders, "A")
    check("empty: A current_value 0", approx(a.current_value, 0.0))
    check("empty: A trade_value 0", approx(a.trade_value, 0.0))
    check("empty: A action HOLD", a.action == "HOLD")
    summary = summarize_rebalance(orders)
    check("empty: num_trades 0", summary["num_trades"] == 0)


# ---------------------------------------------------------------------------
# Test: summarize_rebalance totals
# ---------------------------------------------------------------------------
def test_summarize():
    positions = [
        _pos("A", 60, 1.0, 60.0),
        _pos("B", 40, 1.0, 40.0),
    ]
    # A 0.3, B 0.3, C 0.4 -> total 100.
    # A target 30 -> sell 30; B target 30 -> sell 10; C target 40 -> buy 40.
    orders = compute_rebalance(positions, {"A": 0.3, "B": 0.3, "C": 0.4})
    summary = summarize_rebalance(orders)
    check("summary total_buy 40", approx(summary["total_buy"], 40.0))
    check("summary total_sell 40", approx(summary["total_sell"], 40.0))
    check("summary net_cash_needed 0", approx(summary["net_cash_needed"], 0.0))
    check("summary num_trades 3", summary["num_trades"] == 3)


def main() -> int:
    test_weights_validation()
    test_basic_rebalance()
    test_no_trade_band()
    test_target_only_buy()
    test_full_sell()
    test_cash()
    test_unpriced()
    test_empty()
    test_summarize()

    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} test(s) FAILED: {', '.join(_FAILURES)}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
