#!/usr/bin/env python3
"""
Smoke tests for the dynamic workflow engine (workflows/engine.py).

Runs composed pipelines in demo mode (synthetic data, no network) and asserts
that steps chain correctly and produce output. Exits 0/1 for CI.
"""

import os
import sys
import tempfile

import workflows.engine as engine


def run() -> int:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name} {detail}")
            failures += 1

    # 1. All expected actions are registered
    expected = {"screen", "filter", "portfolio", "rebalance", "alert",
                "project_fees", "export"}
    missing = expected - set(engine.STEP_REGISTRY)
    if missing:
        print(f"FAIL: missing registered actions: {missing}")
        failures += 1
    else:
        print("PASS: all expected actions registered")

    # 2. End-to-end screen -> filter -> export in demo mode writes a CSV
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "wf_out")
        spec = {"name": "demo", "steps": [
            {"action": "screen", "params": {"max_funds": 15}},
            {"action": "filter", "params": {"min_score": 0}},
            {"action": "export", "params": {"format": ["csv"], "output": out}},
        ]}
        try:
            engine.run_workflow(spec, demo=True)
            if os.path.exists(out + ".csv"):
                print("PASS: screen->filter->export wrote CSV")
            else:
                print("FAIL: export produced no CSV")
                failures += 1
        except Exception as exc:  # pragma: no cover - defensive
            print(f"FAIL: workflow raised: {exc}")
            failures += 1

    # 3. The min_score filter actually filters, and correctly.
    #    Demo data is seeded (deterministic), so we can assert real properties
    #    on ctx.results["funds"] directly instead of a loose "<=" check.
    try:
        ctx_all = engine.run_workflow(
            {"steps": [{"action": "screen", "params": {"max_funds": 30}},
                       {"action": "filter", "params": {"min_score": 0}}]},
            demo=True,
        )
        all_df = ctx_all.results["funds"]

        # Choose a threshold from the actual data that keeps SOME but not ALL
        # rows, so the test can distinguish real filtering from a no-op.
        median_score = float(all_df["score"].median())
        ctx_mid = engine.run_workflow(
            {"steps": [{"action": "screen", "params": {"max_funds": 30}},
                       {"action": "filter",
                        "params": {"min_score": median_score}}]},
            demo=True,
        )
        mid_df = ctx_mid.results["funds"]

        if 0 < len(mid_df) < len(all_df):
            print(f"PASS: filter keeps a strict subset "
                  f"(all={len(all_df)}, >=median={len(mid_df)})")
        else:
            print(f"FAIL: filter did not produce a strict subset "
                  f"(all={len(all_df)}, mid={len(mid_df)})")
            failures += 1

        # Every surviving row must satisfy the predicate (catches a filter that
        # returns the wrong rows while still shrinking the count)
        if (mid_df["score"] >= median_score).all():
            print("PASS: all surviving rows satisfy score >= threshold")
        else:
            print("FAIL: a surviving row violates the score threshold")
            failures += 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"FAIL: filter-correctness check raised: {exc}")
        failures += 1

    # 4. Recommendation filter keeps only the requested categories
    try:
        ctx_buy = engine.run_workflow(
            {"steps": [{"action": "screen", "params": {"max_funds": 30}},
                       {"action": "filter",
                        "params": {"recommendation": ["Buy"]}}]},
            demo=True,
        )
        buy_df = ctx_buy.results["funds"]
        ok = buy_df.empty or (buy_df["recommendation"] == "Buy").all()
        check("recommendation filter keeps only Buy", ok)
    except Exception as exc:  # pragma: no cover - defensive
        check("recommendation filter keeps only Buy", False, str(exc))

    # 5. Unknown action raises ValueError (the engine's documented guard)
    try:
        engine.run_workflow({"steps": [{"action": "does_not_exist"}]}, demo=True)
        check("unknown action raises ValueError", False, "no error raised")
    except ValueError:
        check("unknown action raises ValueError", True)
    except Exception as exc:  # pragma: no cover
        check("unknown action raises ValueError", False,
              f"raised {type(exc).__name__}, not ValueError")

    # 6. load_and_run executes a JSON workflow spec from disk
    try:
        import json as _json
        import tempfile as _tf
        spec = {"steps": [{"action": "screen", "params": {"max_funds": 10}},
                          {"action": "filter", "params": {"min_score": 0}}]}
        with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            _json.dump(spec, fh)
            spec_path = fh.name
        ctx = engine.load_and_run(spec_path, demo=True)
        check("load_and_run runs a JSON spec",
              len(ctx.results["funds"]) == 10)
    except Exception as exc:  # pragma: no cover
        check("load_and_run runs a JSON spec", False, str(exc))

    print()
    if failures:
        print(f"WORKFLOW ENGINE TESTS: {failures} failed")
        return 1
    print("WORKFLOW ENGINE TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
