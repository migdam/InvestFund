#!/usr/bin/env python3
"""
Tests for providers.py.

The AnalizyProvider parsing is verified against a fixture captured from a REAL
analizy.pl response (https://www.analizy.pl/api/quotation/fio/ING35) — trimmed
to a few points but with the exact structure (plain + empty dividend series).
No network is used; parse_payload is pure.
"""

import sys

import pandas as pd

from providers import AnalizyProvider, StooqProvider, DataProvider

# --- Real-shape fixture (structure verified against live ING35 response) -----
REAL_SHAPE_PAYLOAD = {
    "id": "ING35",
    "label": "Goldman Sachs Globalny Spółek Dywidendowych",
    "currency": "PLN",
    "isRegular": True,
    "isDividend": False,
    "periods": [{"period": "1M", "label": "1M",
                 "start": "2026-04-28", "end": "2026-05-28"}],
    "events": [],
    "dividends": [],
    "series": [
        {
            "id": "fund_ING35",
            "label": "Fundusz",
            "currency": "PLN",
            "price": [
                {"date": "2009-11-23", "value": 100.0},
                {"date": "2009-11-24", "value": 100.0},
                {"date": "2009-11-25", "value": 100.08},
                {"date": "2009-11-26", "value": 99.46},
                {"date": "2026-05-28", "value": 483.39},
            ],
        },
        {
            "id": "fund_with_dividend_ING35",
            "label": "Fundusz z dywidendą",
            "currency": "PLN",
            "price": [],  # empty for accumulating funds (as in the real response)
        },
    ],
}

# A distribution-style payload where the dividend series IS populated
DIVIDEND_PAYLOAD = {
    "id": "ABC",
    "label": "Some Distribution Fund",
    "currency": "PLN",
    "series": [
        {"id": "fund_ABC", "label": "Fundusz",
         "price": [{"date": "2020-01-02", "value": 50.0},
                   {"date": "2020-01-03", "value": 50.5}]},
        {"id": "fund_with_dividend_ABC", "label": "Fundusz z dywidendą",
         "price": [{"date": "2020-01-02", "value": 50.0},
                   {"date": "2020-01-03", "value": 51.0}]},
    ],
}

CANONICAL_COLS = ["Date", "Open", "High", "Low", "Close", "Volume"]


def run() -> int:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name} {detail}")
            failures += 1

    # 1. Parses the real-shape payload into the canonical schema
    df = AnalizyProvider.parse_payload(REAL_SHAPE_PAYLOAD)
    check("parse returns DataFrame", isinstance(df, pd.DataFrame))
    check("canonical columns", list(df.columns) == CANONICAL_COLS,
          f"got {list(df.columns)}")
    check("row count matches non-empty points", len(df) == 5, f"len={len(df)}")

    # 2. Dtypes / values
    check("Date is datetime", pd.api.types.is_datetime64_any_dtype(df["Date"]))
    check("ascending by date", df["Date"].is_monotonic_increasing)
    check("OHLC mirror Close",
          bool((df["Open"] == df["Close"]).all()
               and (df["High"] == df["Close"]).all()
               and (df["Low"] == df["Close"]).all()))
    check("last Close is 483.39", abs(df["Close"].iloc[-1] - 483.39) < 1e-9)
    check("first Close is 100.0", abs(df["Close"].iloc[0] - 100.0) < 1e-9)
    check("Volume zero-filled", bool((df["Volume"] == 0).all()))

    # 3. Default ignores empty dividend series (falls back to plain)
    df_default = AnalizyProvider.parse_payload(REAL_SHAPE_PAYLOAD,
                                               prefer_dividend=True)
    check("prefer_dividend falls back when dividend series empty",
          df_default is not None and len(df_default) == 5)

    # 4. prefer_dividend uses dividend series when populated
    df_plain = AnalizyProvider.parse_payload(DIVIDEND_PAYLOAD,
                                             prefer_dividend=False)
    df_div = AnalizyProvider.parse_payload(DIVIDEND_PAYLOAD,
                                           prefer_dividend=True)
    check("plain series chosen by default",
          abs(df_plain["Close"].iloc[-1] - 50.5) < 1e-9)
    check("dividend series chosen when preferred",
          abs(df_div["Close"].iloc[-1] - 51.0) < 1e-9)

    # 5. Robustness: bad/empty inputs return None, never raise
    check("None payload -> None", AnalizyProvider.parse_payload(None) is None)
    check("empty dict -> None", AnalizyProvider.parse_payload({}) is None)
    check("no series -> None",
          AnalizyProvider.parse_payload({"id": "x"}) is None)
    check("empty price list -> None",
          AnalizyProvider.parse_payload(
              {"series": [{"id": "fund_x", "label": "Fundusz", "price": []}]}
          ) is None)

    # 6. Skips malformed points (missing date/value) without crashing
    messy = {"series": [{"id": "fund_x", "label": "Fundusz", "price": [
        {"date": "2020-01-02", "value": 10.0},
        {"date": None, "value": 11.0},
        {"date": "2020-01-03", "value": None},
        {"date": "2020-01-06", "value": -5.0},   # non-positive -> dropped
        {"date": "2020-01-07", "value": 12.0},
    ]}]}
    df_messy = AnalizyProvider.parse_payload(messy)
    check("malformed/invalid points dropped", df_messy is not None
          and len(df_messy) == 2,
          f"len={None if df_messy is None else len(df_messy)}")

    # 7. Result is compatible with FundAnalyzer's return-metric math
    try:
        from analyze_polish_funds import FundAnalyzer
        analyzer = FundAnalyzer(use_cache=False)
        rets = analyzer.calculate_returns(df)  # should not raise on real schema
        check("FundAnalyzer.calculate_returns accepts provider output",
              isinstance(rets, dict))
    except Exception as exc:  # pragma: no cover
        check("FundAnalyzer.calculate_returns accepts provider output",
              False, str(exc))

    # 8. Type/contract sanity
    check("AnalizyProvider is a DataProvider",
          issubclass(AnalizyProvider, DataProvider))
    check("StooqProvider is a DataProvider",
          issubclass(StooqProvider, DataProvider))
    check("providers expose a name",
          AnalizyProvider().name == "analizy"
          and StooqProvider().name == "stooq")

    print()
    if failures:
        print(f"PROVIDER TESTS: {failures} failed")
        return 1
    print("PROVIDER TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
