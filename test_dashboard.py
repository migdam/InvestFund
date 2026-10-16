#!/usr/bin/env python3
"""
Tests for the Streamlit dashboard.

Uses Streamlit's AppTest harness to execute dashboard.py in a simulated
runtime. Live data comes from bench/mock_analizy.py, a local stand-in for the
analizy.pl API reached through ``providers.AnalizyProvider.BASE_URL`` (the
benchmark's injection point), so no test touches the network and all are safe
for CI. Each scenario that counts requests runs in a fresh temporary directory,
so the on-disk quote cache starts empty.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st
from streamlit.proto.TextInput_pb2 import TextInput
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent
APP = str(REPO / "dashboard.py")
sys.path[:0] = [str(REPO / "bench"), str(REPO)]

import mock_analizy  # noqa: E402
import providers  # noqa: E402
from analyze_polish_funds import load_symbols_file  # noqa: E402
from bench import (GOLDEN_MAXFUNDS_PATH, GOLDEN_PATH, MAXFUNDS_EARLY,  # noqa: E402
                   compare_to_golden)


def run() -> int:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name} {detail}")
            failures += 1

    golden = json.loads(GOLDEN_PATH.read_text())
    golden_maxfunds = json.loads(GOLDEN_MAXFUNDS_PATH.read_text())
    universe = mock_analizy.symbols()
    last_nav = {sym: mock_analizy.make_payload(sym, n)["series"][0]["price"][-1]["value"]
                for sym, n in mock_analizy.UNIVERSE if n > 0}
    os.environ["NO_PROXY"] = ",".join(
        filter(None, [os.environ.get("NO_PROXY", ""), "127.0.0.1", "localhost"]))
    original_url = providers.AnalizyProvider.BASE_URL

    with mock_analizy.MockAnalizyServer(connect_latency=0, request_latency=0) as server, \
            tempfile.TemporaryDirectory() as tmp:
        providers.AnalizyProvider.BASE_URL = server.url_template
        cwd_count = 0

        def fresh_cwd():
            nonlocal cwd_count
            cwd_count += 1
            path = Path(tmp) / f"run{cwd_count}"
            path.mkdir()
            os.chdir(path)

        def dashboard():
            server.stats.reset()
            return AppTest.from_file(APP, default_timeout=120).run()

        def run_live(at, symbols, max_funds=0):
            at.text_area(key="symbols_analizy").set_value("\n".join(symbols))
            at.number_input(key="max_funds").set_value(max_funds)
            server.stats.reset()
            return at.button(key="run_screen").click().run()

        def problems(at):
            return [str(e.value) for e in at.exception] + [e.value for e in at.error]

        try:
            # 1. Default load: analizy.pl with the verified symbols, nothing fetched yet
            fresh_cwd()
            at = dashboard()
            check("default load renders", not problems(at), problems(at))
            check("analizy.pl is the default source", at.radio(key="source").value == "analizy")
            verified = load_symbols_file(str(REPO / "test_symbols_analizy.txt"))
            check("symbols box starts with the verified analizy.pl symbols",
                  at.text_area(key="symbols_analizy").value.split() == verified)
            check("live data waits for Run analysis",
                  server.stats.requests == 0 and any("Run analysis" in i.value for i in at.info),
                  f"requests={server.stats.requests}")

            # 2. Live run over the benchmark universe gives the CLI's results
            run_live(at, universe)
            df = at.session_state["screen_df"]
            check("live run renders", not problems(at), problems(at))
            check("live run requests each symbol once", server.stats.requests == len(universe),
                  f"requests={server.stats.requests}")
            mismatches = compare_to_golden(df, golden)
            check("live results match bench/golden.json", not mismatches, mismatches[:5])
            check("results sorted by score, highest first", df["score"].is_monotonic_decreasing)
            check("table and fund count shown",
                  len(at.dataframe) == 1 and at.metric[0].value == str(len(golden)))
            check("caption names the live source",
                  any(c.value == "Live data from analizy.pl." for c in at.caption))
            warnings = [w.value for w in at.warning]
            check("symbols without results are named",
                  len(warnings) == 1 and "MISSING01" in warnings[0] and "SHORT15" in warnings[0]
                  and "BENCH00" not in warnings[0], warnings)

            # 3. A new session reuses the disk cache: only the 404 symbol is asked again
            at = dashboard()
            run_live(at, universe)
            check("warm run requests only the uncached symbol", server.stats.requests == 1,
                  f"requests={server.stats.requests}")
            check("warm run gives the same results",
                  not compare_to_golden(at.session_state["screen_df"], golden))

            # 4. Max funds has the CLI's --max-funds semantics
            fresh_cwd()
            at = dashboard()
            order = MAXFUNDS_EARLY + [s for s in universe if s not in MAXFUNDS_EARLY]
            run_live(at, order, max_funds=5)
            mismatches = compare_to_golden(at.session_state["screen_df"], golden_maxfunds)
            check("max funds 5 matches bench/golden_maxfunds5.json", not mismatches, mismatches[:5])
            check("max funds 5 stops after 6 requests", server.stats.requests == 6,
                  f"requests={server.stats.requests}")
            warnings = [w.value for w in at.warning]
            check("max funds: only requested symbols are reported missing",
                  len(warnings) == 1 and "MISSING01" in warnings[0] and "SHORT15" in warnings[0]
                  and "BENCH39" not in warnings[0] and "YOUNG120" not in warnings[0], warnings)
            check("max funds cut is explained",
                  any("Max funds is 5" in c.value for c in at.caption))

            # 5. Duplicates are fetched once; a fully failed run explains itself
            fresh_cwd()
            at = dashboard()
            run_live(at, ["BENCH05", "BENCH05", "MISSING01"])
            check("duplicate symbols are fetched once", server.stats.requests == 2,
                  f"requests={server.stats.requests}")
            check("duplicate symbols are listed once",
                  list(at.session_state["screen_df"]["symbol"]) == ["BENCH05"])
            run_live(at, ["MISSING01"])
            check("no results: warning plus info, no crash",
                  not problems(at) and any("MISSING01" in w.value for w in at.warning)
                  and any("No results" in i.value for i in at.info), problems(at))
            at.text_area(key="symbols_analizy").set_value("# only a comment\n").run()
            server.stats.reset()
            at.button(key="run_screen").click().run()
            check("empty symbols box: asks for symbols, no request",
                  server.stats.requests == 0
                  and any("at least one" in w.value for w in at.warning))

            # 6. Uploading a symbols file fills the box (byte-order mark dropped)
            at = dashboard()
            uploader = at.sidebar.file_uploader(key="symbols_file_analizy")
            uploader.set_value(("mine.txt", "﻿# my funds\nBENCH05\nBENCH06\n".encode(),
                                "text/plain")).run()
            check("uploaded symbols fill the box",
                  at.text_area(key="symbols_analizy").value == "BENCH05\nBENCH06",
                  repr(at.text_area(key="symbols_analizy").value))
            at.sidebar.file_uploader(key="symbols_file_analizy").set_value(
                ("list.json", b'["BENCH07", "BENCH08"]', "application/json")).run()
            check("a JSON symbols list works too",
                  at.text_area(key="symbols_analizy").value == "BENCH07\nBENCH08")
            at.sidebar.file_uploader(key="symbols_file_analizy").set_value(
                ("bad.json", b'["BENCH09",', "application/json")).run()
            check("an unreadable file is reported and leaves the box alone",
                  any("bad.json" in e.value for e in at.error)
                  and at.text_area(key="symbols_analizy").value == "BENCH07\nBENCH08")

            # 7. Results stay labelled after settings change
            at = dashboard()
            run_live(at, ["BENCH05"])
            check("no stale-results note right after a run",
                  not any("Settings changed" in i.value for i in at.info))
            at.text_area(key="symbols_analizy").set_value("BENCH06").run()
            check("changed settings ask for a new run",
                  any("Settings changed" in i.value for i in at.info))

            # 8. Demo source: generated at once, no requests; filters work
            at = dashboard()
            at.radio(key="source").set_value("demo").run()
            df = at.session_state["screen_df"]
            check("demo data appears without Run analysis or requests",
                  len(df) == 30 and server.stats.requests == 0 and not problems(at),
                  f"rows={len(df)} requests={server.stats.requests}")
            check("demo data is labelled",
                  any("synthetic demo data" in c.value for c in at.caption))
            for slider in at.slider:
                if slider.label == "Minimum score":
                    slider.set_value(50).run()
                    break
            shown = [s.value for s in at.subheader if s.value.startswith("Results")]
            check("minimum-score filter narrows the table",
                  not problems(at) and shown == [f"Results ({int((df['score'] >= 50).sum())})"],
                  shown)

            # 9. Stooq source: masked API key box, empty symbols box, nothing fetched
            saved_key = os.environ.pop("STOOQ_APIKEY", None)
            try:
                at = dashboard()
                at.radio(key="source").set_value("stooq").run()
                key_box = at.text_input(key="stooq_apikey")
                check("Stooq asks for an API key in a password field",
                      key_box.proto.type == TextInput.PASSWORD)
                check("missing Stooq key is pointed out",
                      any("No API key set" in c.value for c in at.sidebar.caption))
                check("Stooq symbols box starts empty",
                      at.text_area(key="symbols_stooq").value == "")
                check("switching sources fetches nothing", server.stats.requests == 0)
            finally:
                if saved_key is not None:
                    os.environ["STOOQ_APIKEY"] = saved_key

            # 10. Portfolio: priced from analizy.pl with one parallel prefetch
            fresh_cwd()
            st.cache_data.clear()
            at = dashboard()
            at.sidebar.radio[0].set_value("Portfolio Tracker").run()
            check("portfolio view renders", not problems(at), problems(at))
            check("analizy.pl is the default price source",
                  at.radio(key="pf_source").value == "analizy")
            # Two lots of a fund and of an unknown symbol: valuing holdings one
            # by one would request the unknown symbol twice.
            holdings = [
                {"symbol": "BENCH03", "shares": 10, "cost_basis": 90, "ter": 0.015},
                {"symbol": "BENCH04", "shares": 5, "cost_basis": 110},
                {"symbol": "MISSING01", "shares": 1, "cost_basis": 10},
                {"symbol": "BENCH03", "shares": 2, "cost_basis": 95, "ter": 0.015},
                {"symbol": "MISSING01", "shares": 3, "cost_basis": 12},
            ]
            expected_value = 12 * last_nav["BENCH03"] + 5 * last_nav["BENCH04"]
            server.stats.reset()
            at.file_uploader[0].set_value(
                ("holdings.json", json.dumps({"holdings": holdings}).encode(),
                 "application/json")).run()
            metrics = {m.label: m.value for m in at.metric}
            check("portfolio is valued from the quotes",
                  not problems(at) and metrics.get("Total value") == f"{expected_value:,.0f}",
                  f"{metrics} expected {expected_value:,.0f} {problems(at)}")
            check("each holding's symbol is requested once", server.stats.requests == 3,
                  f"requests={server.stats.requests}")
            check("unpriced holdings are named once",
                  [w.value.count("MISSING01") for w in at.warning] == [1],
                  [w.value for w in at.warning])
            for slider in at.slider:
                if slider.label == "Projection horizon (years)":
                    slider.set_value(20).run()
                    break
            check("moving a slider fetches nothing", server.stats.requests == 3,
                  f"requests={server.stats.requests}")
            csv = "symbol,shares,cost_basis,ter\n" + "".join(
                f"{h['symbol']},{h['shares']},{h['cost_basis']},{h.get('ter', '')}\n"
                for h in holdings)
            server.stats.reset()
            at.file_uploader[0].set_value(("holdings.csv", csv.encode(), "text/csv")).run()
            metrics = {m.label: m.value for m in at.metric}
            check("CSV holdings give the same value",
                  metrics.get("Total value") == f"{expected_value:,.0f}", metrics)
            check("cached holdings are not requested again", server.stats.requests == 1,
                  f"requests={server.stats.requests}")
            check("the upload leaves no file behind", not list(Path.cwd().glob(".portfolio*")))
        finally:
            providers.AnalizyProvider.BASE_URL = original_url
            os.chdir(REPO)

    print()
    if failures:
        print(f"DASHBOARD TESTS: {failures} failed")
        return 1
    print("DASHBOARD TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
