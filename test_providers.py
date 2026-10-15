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

    # 9. SymbolMapper: canonical key, reverse lookup, passthrough
    from providers import SymbolMapper
    mapper = SymbolMapper({
        "GS Globalny": {"stooq": "1234.N", "analizy": "ING35"},
        "Bond Fund": {"analizy": "ABC12"},
    })
    check("map by canonical key -> analizy",
          mapper.resolve("GS Globalny", "analizy") == "ING35")
    check("map by canonical key -> stooq",
          mapper.resolve("GS Globalny", "stooq") == "1234.N")
    check("reverse lookup: stooq symbol -> analizy",
          mapper.resolve("1234.N", "analizy") == "ING35")
    check("reverse lookup: analizy symbol -> stooq",
          mapper.resolve("ING35", "stooq") == "1234.N")
    check("unmapped symbol passes through unchanged",
          mapper.resolve("UNKNOWN.N", "analizy") == "UNKNOWN.N")
    check("missing provider in entry -> passthrough",
          mapper.resolve("Bond Fund", "stooq") == "Bond Fund")
    check("empty mapper passes everything through",
          SymbolMapper().resolve("ING35", "stooq") == "ING35")

    # 10. SymbolMapper.from_file round-trips
    import json as _json
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        _json.dump({"X": {"stooq": "9.N", "analizy": "QQ1"}}, fh)
        map_path = fh.name
    loaded = SymbolMapper.from_file(map_path)
    check("from_file resolves correctly",
          loaded.resolve("X", "analizy") == "QQ1")

    # 11. parse_label reads the fund name from a payload
    check("parse_label reads label",
          AnalizyProvider.parse_label(REAL_SHAPE_PAYLOAD)
          == "Goldman Sachs Globalny Spółek Dywidendowych")
    check("parse_label handles missing label",
          AnalizyProvider.parse_label({}) == "")

    # 12. get_fund_list resolves names via the (stubbed) quotation endpoint
    prov = AnalizyProvider()
    # Stub network so the test stays offline
    prov._fetch_json = lambda sym: (
        REAL_SHAPE_PAYLOAD if sym == "ING35" else None
    )
    funds = prov.get_fund_list(["ING35", "MISSING"])
    check("get_fund_list skips unresolved symbols", len(funds) == 1)
    check("get_fund_list uses real name",
          funds[0].symbol == "ING35"
          and funds[0].name == "Goldman Sachs Globalny Spółek Dywidendowych")

    # 13. fetch_funds: same listing rules as get_fund_list, plus parsed quotes,
    #     one fetch per symbol, input order kept, concurrency capped.
    import threading
    import time as _time

    empty_series = {"label": "Pusty", "series": [
        {"id": "fund_EMPTY", "label": "Fundusz", "price": []}]}
    responses = {"ING35": REAL_SHAPE_PAYLOAD, "DIV": DIVIDEND_PAYLOAD,
                 "EMPTY": empty_series}
    calls, in_flight, peak = [], [0], [0]
    lock = threading.Lock()

    def stub_fetch(sym):
        with lock:
            calls.append(sym)
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        _time.sleep(0.02)
        with lock:
            in_flight[0] -= 1
        return responses.get(sym)

    prov = AnalizyProvider()
    prov._fetch_json = stub_fetch
    order = ["DIV", "MISSING", "ING35", "EMPTY"]
    funds, quotes = prov.fetch_funds(order, max_workers=2)
    check("fetch_funds lists resolved symbols in input order",
          [f.symbol for f in funds] == ["DIV", "ING35", "EMPTY"],
          f"got {[f.symbol for f in funds]}")
    check("fetch_funds names funds by label",
          [f.name for f in funds] == ["Some Distribution Fund",
                                      "Goldman Sachs Globalny Spółek Dywidendowych",
                                      "Pusty"])
    check("fetch_funds fetches each symbol exactly once",
          sorted(calls) == sorted(order), f"calls={calls}")
    check("fetch_funds returns parsed quotes",
          abs(quotes["ING35"]["Close"].iloc[-1] - 483.39) < 1e-9
          and abs(quotes["DIV"]["Close"].iloc[-1] - 50.5) < 1e-9)
    check("fetch_funds keeps a listed symbol with no prices as None",
          "EMPTY" in quotes and quotes["EMPTY"] is None)
    check("fetch_funds omits unresolved symbols from quotes", "MISSING" not in quotes)
    check("fetch_funds never exceeds max_workers in flight",
          1 <= peak[0] <= 2, f"peak={peak[0]}")
    check("fetched quotes record the fund name",
          quotes["ING35"].attrs.get("name") == "Goldman Sachs Globalny Spółek Dywidendowych")

    # 14. fetch_funds with a cache: named entries are served without a request,
    #     unnamed (older) entries are fetched, and names survive the disk cache.
    import tempfile
    from pathlib import Path as _Path
    from analyze_polish_funds import FundAnalyzer, _NamedSource

    named = AnalizyProvider.parse_payload(REAL_SHAPE_PAYLOAD)
    named.attrs["name"] = "Cached Name"
    unnamed = AnalizyProvider.parse_payload(DIVIDEND_PAYLOAD)
    cache = {"ING35": named, "DIV": unnamed}
    calls.clear()
    funds, quotes = prov.fetch_funds(["ING35", "DIV", "MISSING"], max_workers=2,
                                     cached=cache.get)
    check("cached entry with a name needs no request", "ING35" not in calls,
          f"calls={calls}")
    check("cached entry without a name is fetched", "DIV" in calls)
    check("names come from the cache or the payload",
          [(f.symbol, f.name) for f in funds]
          == [("ING35", "Cached Name"), ("DIV", "Some Distribution Fund")])

    with tempfile.TemporaryDirectory() as tmp:
        source = _NamedSource(lambda s: quotes.get(s), "analizy")
        writer = FundAnalyzer(use_cache=True, cache_dir=_Path(tmp), quote_source=source)
        writer.download_quotes("DIV")  # cache miss: stores the quotes
        reader = FundAnalyzer(use_cache=True, cache_dir=_Path(tmp), quote_source=source)
        hit = reader.cached_quotes("DIV")
        check("cached_quotes returns stored quotes with their name",
              hit is not None and hit.attrs.get("name") == "Some Distribution Fund")
        check("cached_quotes returns None for an uncached symbol",
              reader.cached_quotes("NOPE") is None)
        no_cache = FundAnalyzer(use_cache=False, cache_dir=_Path(tmp), quote_source=source)
        check("cached_quotes returns None when caching is off",
              no_cache.cached_quotes("DIV") is None)

    # 15. fetch_funds(limit=N): fetch in order only until N symbols resolve,
    #     listing exactly what a full fetch would list first.
    order = ["DIV", "MISSING", "ING35", "EMPTY"]
    full, _ = prov.fetch_funds(order, max_workers=2)
    calls.clear()
    limited, limited_quotes = prov.fetch_funds(order, max_workers=2, limit=2)
    check("limit stops fetching once enough symbols resolved",
          sorted(calls) == ["DIV", "ING35", "MISSING"], f"calls={calls}")
    check("limit lists the same first funds as a full fetch",
          [(f.symbol, f.name) for f in limited]
          == [(f.symbol, f.name) for f in full[:2]])
    check("limit returns quotes only for listed funds",
          sorted(limited_quotes) == ["DIV", "ING35"])
    calls.clear()
    over, _ = prov.fetch_funds(order, max_workers=2, limit=10)
    check("limit above the resolvable count fetches everything",
          len(over) == 3 and sorted(calls) == sorted(order))
    calls.clear()
    named_div = AnalizyProvider.parse_payload(DIVIDEND_PAYLOAD)
    named_div.attrs["name"] = "Cached DIV"
    from_cache, _ = prov.fetch_funds(order, max_workers=2, limit=1,
                                     cached={"DIV": named_div}.get)
    check("a cached fund counts toward the limit without a request",
          calls == [] and [f.symbol for f in from_cache] == ["DIV"], f"calls={calls}")

    # 16. Real HTTP round trips against the local mock server: each thread
    #     keeps one keep-alive connection, and errors still return None.
    sys.path.insert(0, str(_Path(__file__).resolve().parent / "bench"))
    import mock_analizy

    with mock_analizy.MockAnalizyServer(connect_latency=0, request_latency=0) as server:
        live = AnalizyProvider()
        live.BASE_URL = server.url_template
        payloads = [live._fetch_json(s) for s in ("BENCH00", "BENCH01", "BENCH02")]
        check("live fetch returns payloads", all(isinstance(p, dict) for p in payloads))
        check("one thread reuses a single connection",
              server.stats.requests == 3 and server.stats.connections == 1,
              f"requests={server.stats.requests} connections={server.stats.connections}")
        server.stats.reset()
        worker = threading.Thread(target=live._fetch_json, args=("BENCH03",))
        worker.start()
        worker.join()
        check("another thread opens its own connection",
              server.stats.requests == 1 and server.stats.connections == 1,
              f"requests={server.stats.requests} connections={server.stats.connections}")
        check("an unknown symbol still returns None",
              live._fetch_json("MISSING01") is None)

    print()
    if failures:
        print(f"PROVIDER TESTS: {failures} failed")
        return 1
    print("PROVIDER TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
