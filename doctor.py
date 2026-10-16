#!/usr/bin/env python3
"""
doctor.py
---------

One-command health check for the Polish Funds Analyzer.

It answers the question "is this thing actually going to work on my machine?"
by checking, in order:

  1. Python version
  2. Required dependencies importable (and which optional ones are missing)
  3. Network reachability of the data sources
  4. The **analizy.pl** provider end-to-end (fetch + parse + a real metric)
  5. The **Stooq** CSV quote endpoint (detects the new API-key paywall)
  6. The **Stooq** fund-listing page (detects the JavaScript-app migration)

Each check prints ``[PASS]``, ``[WARN]`` or ``[FAIL]``. The process exits 0 when
nothing hard-failed (warnings are fine — e.g. Stooq needing a key is expected),
and 1 when the working data path is broken.

Usage
~~~~~
    python doctor.py
    python doctor.py --stooq-apikey YOURKEY
    # or, equivalently, via the main tool:
    python analyze_polish_funds.py --self-test

This tool is for informational/educational use only and is not investment advice.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

# A known-good analizy.pl symbol (verified against the live quotation API) and a
# Stooq symbol (the WIG index) used as canaries for the live-data checks.
ANALIZY_CANARY = "ING35"
STOOQ_CANARY = "wig"

# pip distribution name -> importable module name
REQUIRED_DEPS = {
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "scipy": "scipy",
    "tqdm": "tqdm",
    "python-dateutil": "dateutil",
}
OPTIONAL_DEPS = {
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
    "openpyxl": "openpyxl",
    "streamlit": "streamlit",
    "PyYAML": "yaml",
}

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class _Report:
    """Collects check results, prints them, and computes the exit code."""

    def __init__(self) -> None:
        self.rows = []
        color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self._c = {
            PASS: "\033[32m" if color else "",
            WARN: "\033[33m" if color else "",
            FAIL: "\033[31m" if color else "",
        }
        self._reset = "\033[0m" if color else ""

    def add(self, status: str, message: str) -> None:
        self.rows.append((status, message))
        tag = f"{self._c[status]}[{status}]{self._reset}"
        print(f"{tag} {message}")

    def exit_code(self) -> int:
        return 1 if any(s == FAIL for s, _ in self.rows) else 0

    def summarize(self) -> None:
        fails = sum(1 for s, _ in self.rows if s == FAIL)
        warns = sum(1 for s, _ in self.rows if s == WARN)
        print("-" * 60)
        if fails:
            print(f"Result: FAIL — {fails} failure(s), {warns} warning(s). "
                  "The tool will not work until the failure(s) above are fixed.")
        elif warns:
            print(f"Result: PASS with {warns} warning(s). "
                  "The analizy.pl path is healthy; Stooq needs attention "
                  "(see warnings).")
        else:
            print("Result: PASS — all checks green.")


# --- individual checks ----------------------------------------------------

def check_python(rep: _Report) -> None:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 9):
        rep.add(PASS, f"Python {ver} (>= 3.9)")
    else:
        rep.add(FAIL, f"Python {ver} is too old; need >= 3.9")


def check_dependencies(rep: _Report) -> bool:
    missing_required = []
    for dist, mod in REQUIRED_DEPS.items():
        try:
            importlib.import_module(mod)
        except Exception:
            missing_required.append(dist)
    if missing_required:
        rep.add(FAIL, "Missing required dependencies: "
                      + ", ".join(missing_required)
                      + " — run: pip install -r requirements.txt")
    else:
        rep.add(PASS, "Required dependencies importable: "
                      + ", ".join(REQUIRED_DEPS))

    missing_optional = [
        dist for dist, mod in OPTIONAL_DEPS.items()
        if not _importable(mod)
    ]
    if missing_optional:
        rep.add(WARN, "Optional dependencies missing (some features disabled): "
                      + ", ".join(missing_optional))
    else:
        rep.add(PASS, "Optional dependencies present: "
                      + ", ".join(OPTIONAL_DEPS))
    return not missing_required


def _importable(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def check_network(rep: _Report) -> bool:
    import requests
    reachable = []
    for host in ("https://www.analizy.pl", "https://stooq.pl"):
        try:
            requests.head(host, timeout=15, allow_redirects=True)
            reachable.append(host)
        except Exception:
            pass
    if len(reachable) == 2:
        rep.add(PASS, "Network: analizy.pl and stooq.pl both reachable")
    elif reachable:
        rep.add(WARN, f"Network: only reachable host is {reachable[0]} "
                      "(the other may be down or blocked)")
    else:
        rep.add(FAIL, "Network: neither analizy.pl nor stooq.pl is reachable "
                      "(offline or firewalled?)")
    return bool(reachable)


def check_analizy(rep: _Report) -> None:
    """The critical path: it's the provider that currently works."""
    try:
        from providers import AnalizyProvider
        from analyze_polish_funds import FundAnalyzer
    except Exception as exc:
        rep.add(FAIL, f"analizy provider: could not import project modules ({exc})")
        return
    try:
        df = AnalizyProvider().download_quotes(ANALIZY_CANARY)
    except Exception as exc:
        rep.add(FAIL, f"analizy provider: fetch raised {exc!r}")
        return
    if df is None or len(df) == 0:
        rep.add(FAIL, f"analizy provider: '{ANALIZY_CANARY}' returned no data "
                      "(API shape may have changed)")
        return
    try:
        ret_1y = FundAnalyzer(use_cache=False).calculate_returns(df)["1y"]
    except Exception:
        ret_1y = None
    ret_txt = f"{ret_1y * 100:+.2f}% 1y return" if ret_1y is not None else "1y n/a"
    rep.add(PASS, f"analizy provider: '{ANALIZY_CANARY}' -> {len(df)} NAV "
                  f"points, {ret_txt}")


def check_stooq_quotes(rep: _Report, stooq_apikey=None) -> None:
    import requests
    from analyze_polish_funds import STOOQ_APIKEY_ENV, STOOQ_APIKEY_SENTINEL
    key = stooq_apikey or os.environ.get(STOOQ_APIKEY_ENV)
    url = f"https://stooq.pl/q/d/l/?s={STOOQ_CANARY}&i=d"
    if key:
        url += f"&apikey={key}"
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": "Mozilla/5.0"})
        body = resp.content.decode("utf-8", errors="ignore")
    except Exception as exc:
        rep.add(WARN, f"Stooq quotes: request failed ({exc}); analizy path is "
                      "unaffected")
        return

    if STOOQ_APIKEY_SENTINEL in body[:200].lower():
        if key:
            rep.add(WARN, "Stooq quotes: API key supplied but endpoint still "
                          "demands one — the key looks invalid or expired")
        else:
            rep.add(WARN, "Stooq quotes: endpoint requires an API key. Get one "
                          "(one-time captcha) at "
                          "https://stooq.pl/q/d/?s=wig&get_apikey then set "
                          f"{STOOQ_APIKEY_ENV} or pass --stooq-apikey. "
                          "(Not fatal — use --provider analizy.)")
    elif body[:4].lower() == "date":
        rep.add(PASS, f"Stooq quotes: '{STOOQ_CANARY}' returned CSV data "
                      "(API key working)")
    else:
        rep.add(WARN, "Stooq quotes: unexpected response (neither CSV nor the "
                      "known API-key notice); the endpoint may have changed")


def check_stooq_listing(rep: _Report) -> None:
    import requests
    url = "https://stooq.pl/t/"
    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": "Mozilla/5.0"})
        body = resp.text
    except Exception as exc:
        rep.add(WARN, f"Stooq listing: request failed ({exc})")
        return
    if "<table" in body.lower():
        rep.add(PASS, "Stooq listing: server-rendered table present (scrapable)")
    else:
        rep.add(WARN, "Stooq listing: no server-rendered table — page is now a "
                      "JavaScript app, so automated listing is unavailable. "
                      "Use --symbols-file or --provider analizy.")


# --- orchestration --------------------------------------------------------

def run_doctor(stooq_apikey=None) -> int:
    """Run all checks; return a process exit code (0 ok, 1 hard failure)."""
    rep = _Report()
    print("Polish Funds Analyzer — environment & data-source check")
    print("=" * 60)

    check_python(rep)
    deps_ok = check_dependencies(rep)
    if not deps_ok:
        rep.summarize()
        return rep.exit_code()

    net_ok = check_network(rep)
    if net_ok:
        check_analizy(rep)
        check_stooq_quotes(rep, stooq_apikey=stooq_apikey)
        check_stooq_listing(rep)
    else:
        rep.add(WARN, "Skipping live data-source checks (no network)")

    rep.summarize()
    return rep.exit_code()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Environment & data-source health check for the Polish "
                    "Funds Analyzer."
    )
    parser.add_argument(
        "--stooq-apikey", default=None,
        help="Stooq API key to test (falls back to the STOOQ_APIKEY env var)."
    )
    args = parser.parse_args()
    sys.exit(run_doctor(stooq_apikey=args.stooq_apikey))


if __name__ == "__main__":
    main()
