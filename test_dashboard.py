#!/usr/bin/env python3
"""
Smoke tests for the Streamlit dashboard.

Uses Streamlit's AppTest harness to execute dashboard.py in a simulated
runtime and assert that the main views render without raising. These run
headless and need no network (the dashboard's Demo mode supplies synthetic
data), so they are safe for CI.
"""

import sys

from streamlit.testing.v1 import AppTest


def run() -> int:
    failures = 0

    # Default load -> Fund Screener with Demo mode on
    at = AppTest.from_file("dashboard.py", default_timeout=90).run()
    if at.exception:
        print(f"FAIL: Screener view raised: {at.exception}")
        failures += 1
    else:
        print(f"PASS: Screener view (metrics={len(at.metric)}, "
              f"dataframes={len(at.dataframe)})")

    # Interact with the minimum-score filter and rerun
    try:
        for slider in at.slider:
            if slider.label == "Minimum score":
                slider.set_value(50).run()
                break
        if at.exception:
            print(f"FAIL: Filter interaction raised: {at.exception}")
            failures += 1
        else:
            print("PASS: Filter interaction")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"FAIL: Filter interaction error: {exc}")
        failures += 1

    # Switch to the Portfolio Tracker view
    at2 = AppTest.from_file("dashboard.py", default_timeout=90).run()
    at2.sidebar.radio[0].set_value("Portfolio Tracker").run()
    if at2.exception:
        print(f"FAIL: Portfolio view raised: {at2.exception}")
        failures += 1
    else:
        print("PASS: Portfolio view")

    print()
    if failures:
        print(f"DASHBOARD SMOKE TESTS: {failures} failed")
        return 1
    print("DASHBOARD SMOKE TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
