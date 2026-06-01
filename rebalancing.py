"""
rebalancing.py
--------------

Self-contained portfolio *rebalancing* engine that complements
``analyze_polish_funds.py``.

Given a set of valued portfolio positions (``PortfolioPosition`` objects, as
produced by :meth:`FundAnalyzer.analyze_portfolio`) and a set of *target
weights*, this module computes the trades required to move the current
allocation towards the target allocation.

Key concepts
~~~~~~~~~~~~
- **Total investable**: the sum of the current value of all priced positions
  plus any uninvested ``cash``. Targets are applied against this total.
- **Drift**: ``current_weight - target_weight`` for each symbol. A positive
  drift means the position is *over*-weight (a candidate to SELL); a negative
  drift means it is *under*-weight (a candidate to BUY).
- **No-trade band** (``drift_threshold``): if a symbol's absolute drift is
  below this threshold, it is left untouched ("HOLD"). This avoids churning
  the portfolio for tiny deviations.

This module is for informational and educational purposes only and does not
constitute professional investment advice.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# Reuse the real dataclasses / analyzer from the existing module so callers
# pass genuine PortfolioPosition objects. analyze_portfolio returns these.
from analyze_polish_funds import FundAnalyzer, Holding, PortfolioPosition


# Number of decimal places to round computed share quantities to. Most funds
# are quoted/transacted with reasonable fractional precision, so 4 dp keeps
# the math faithful without exposing floating-point noise.
SHARES_DECIMALS = 4

# Tolerance for the "weights must sum to ~1.0" validation.
WEIGHT_SUM_MIN = 0.99
WEIGHT_SUM_MAX = 1.01


@dataclass
class RebalanceOrder:
    """A single rebalancing instruction for one symbol.

    Attributes
    ----------
    symbol : str
        Ticker the order applies to.
    current_value : float
        Current market value of the holding (0.0 if not held or unpriced).
    current_weight : float
        Current share of total investable value (0.0 if not held/unpriced).
    target_weight : float
        Desired share of total investable value.
    drift : float
        ``current_weight - target_weight``. Positive => over-weight.
    action : str
        One of ``"BUY"``, ``"SELL"`` or ``"HOLD"``.
    trade_value : float
        Cash value to trade. Positive => buy, negative => sell, 0 => hold.
    shares_to_trade : float or None
        ``trade_value / current_price`` rounded to ``SHARES_DECIMALS``, or
        ``None`` when no current price is known for the symbol.
    """

    symbol: str
    current_value: float
    current_weight: float
    target_weight: float
    drift: float
    action: str
    trade_value: float
    shares_to_trade: Optional[float] = None


def _validate_target_weights(target_weights: Dict[str, Optional[float]]) -> Dict[str, float]:
    """Validate and normalize a target-weight mapping.

    ``None`` values are ignored (treated as "no explicit target"). The
    remaining weights must sum to within ``[WEIGHT_SUM_MIN, WEIGHT_SUM_MAX]``.

    Parameters
    ----------
    target_weights : dict
        Mapping ``{symbol: weight}``. Weights may be ``None``.

    Returns
    -------
    dict
        A cleaned ``{symbol: float}`` mapping (None entries dropped).

    Raises
    ------
    ValueError
        If the (non-None) weights do not sum to ~1.0.
    """
    cleaned: Dict[str, float] = {
        sym: float(w) for sym, w in target_weights.items() if w is not None
    }
    total = sum(cleaned.values())
    if not (WEIGHT_SUM_MIN <= total <= WEIGHT_SUM_MAX):
        raise ValueError(
            f"Target weights must sum to ~1.0 (within "
            f"[{WEIGHT_SUM_MIN}, {WEIGHT_SUM_MAX}]); got {total:.6f}."
        )
    return cleaned


def compute_rebalance(
    positions: List[PortfolioPosition],
    target_weights: Dict[str, Optional[float]],
    drift_threshold: float = 0.0,
    cash: float = 0.0,
) -> List[RebalanceOrder]:
    """Compute the trades needed to move a portfolio toward target weights.

    Parameters
    ----------
    positions : List[PortfolioPosition]
        Current valued positions (as returned by
        :meth:`FundAnalyzer.analyze_portfolio`). Positions without a
        ``current_value`` are treated as unpriced and contribute nothing to
        the investable total, but still appear in the result (with action
        ``HOLD`` and ``shares_to_trade=None``) unless they also have a target.
    target_weights : dict
        Mapping ``{symbol: weight}`` whose non-None values must sum to ~1.0.
        A symbol present in ``positions`` but absent from ``target_weights``
        is treated as having a target weight of 0.0 (i.e. sell it all). A
        symbol present in ``target_weights`` but not held is a candidate BUY.
    drift_threshold : float, optional
        No-trade band. If ``abs(drift) < drift_threshold`` the symbol is left
        as ``HOLD`` with ``trade_value=0``. Default 0.0 (always trade).
    cash : float, optional
        Uninvested cash to add to the investable total. Default 0.0.

    Returns
    -------
    List[RebalanceOrder]
        One order per symbol in the union of held and targeted symbols,
        ordered by descending absolute drift (largest deviations first).
    """
    cleaned_targets = _validate_target_weights(target_weights)

    # Map symbol -> position for quick lookup. If duplicate symbols are passed
    # the last one wins (defensive; analyze_portfolio yields one per holding).
    pos_by_symbol: Dict[str, PortfolioPosition] = {p.symbol: p for p in positions}

    # Investable base = priced position values + cash.
    invested_value = sum(
        p.current_value for p in positions if p.current_value is not None
    )
    total_investable = invested_value + cash

    # Union of held symbols and target symbols, preserving a stable order
    # (held first in input order, then any target-only symbols).
    symbols: List[str] = []
    seen = set()
    for p in positions:
        if p.symbol not in seen:
            symbols.append(p.symbol)
            seen.add(p.symbol)
    for sym in cleaned_targets:
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)

    orders: List[RebalanceOrder] = []
    for sym in symbols:
        pos = pos_by_symbol.get(sym)
        current_value = (
            pos.current_value if pos is not None and pos.current_value is not None else 0.0
        )
        current_weight = (
            (current_value / total_investable) if total_investable > 0 else 0.0
        )
        # A held symbol absent from targets => target 0.0 (full sell).
        target_weight = cleaned_targets.get(sym, 0.0)
        target_value = target_weight * total_investable
        drift = current_weight - target_weight
        trade_value = target_value - current_value

        # Apply the no-trade band.
        if abs(drift) < drift_threshold:
            action = "HOLD"
            trade_value = 0.0
        elif trade_value > 0:
            action = "BUY"
        elif trade_value < 0:
            action = "SELL"
        else:
            action = "HOLD"

        # Shares only when a current price is known.
        shares_to_trade: Optional[float] = None
        current_price = pos.current_price if pos is not None else None
        if current_price is not None and current_price > 0:
            shares_to_trade = round(trade_value / current_price, SHARES_DECIMALS)

        orders.append(
            RebalanceOrder(
                symbol=sym,
                current_value=current_value,
                current_weight=current_weight,
                target_weight=target_weight,
                drift=drift,
                action=action,
                trade_value=trade_value,
                shares_to_trade=shares_to_trade,
            )
        )

    # Largest absolute drifts first for an actionable, readable order list.
    orders.sort(key=lambda o: abs(o.drift), reverse=True)
    return orders


def summarize_rebalance(orders: List[RebalanceOrder]) -> Dict[str, float]:
    """Aggregate a list of rebalance orders into headline totals.

    Parameters
    ----------
    orders : List[RebalanceOrder]
        Orders produced by :func:`compute_rebalance`.

    Returns
    -------
    dict
        Keys: ``total_buy`` (sum of positive trade values),
        ``total_sell`` (absolute sum of negative trade values, reported as a
        positive number), ``net_cash_needed`` (``total_buy - total_sell``;
        positive means cash must be added, negative means cash is freed) and
        ``num_trades`` (count of non-HOLD orders).
    """
    total_buy = sum(o.trade_value for o in orders if o.trade_value > 0)
    total_sell = -sum(o.trade_value for o in orders if o.trade_value < 0)
    num_trades = sum(1 for o in orders if o.action != "HOLD")
    return {
        "total_buy": total_buy,
        "total_sell": total_sell,
        "net_cash_needed": total_buy - total_sell,
        "num_trades": num_trades,
    }


def rebalance_from_holdings(
    analyzer: FundAnalyzer,
    holdings: List[Holding],
    target_weights: Dict[str, Optional[float]],
    **kwargs,
) -> List[RebalanceOrder]:
    """Value ``holdings`` via the analyzer, then compute the rebalance.

    Convenience wrapper that calls :meth:`FundAnalyzer.analyze_portfolio`
    (which fetches prices) and feeds the resulting positions into
    :func:`compute_rebalance`.

    Parameters
    ----------
    analyzer : FundAnalyzer
        An initialized analyzer (used purely for ``analyze_portfolio``).
    holdings : List[Holding]
        Holdings to value and rebalance.
    target_weights : dict
        Mapping ``{symbol: weight}`` passed through to
        :func:`compute_rebalance`.
    **kwargs
        Forwarded to :func:`compute_rebalance` (e.g. ``drift_threshold``,
        ``cash``).

    Returns
    -------
    List[RebalanceOrder]
    """
    positions, _summary = analyzer.analyze_portfolio(holdings)
    return compute_rebalance(positions, target_weights, **kwargs)
