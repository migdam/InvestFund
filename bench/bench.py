#!/usr/bin/env python3
"""
Offline efficiency benchmark for the analizy.pl path of analyze_polish_funds.

Everything runs locally against bench/mock_analizy.py, so results do not
depend on network access to analizy.pl and the third-party site is never hit.

Scenarios
---------
cli_startup_s         `analyze_polish_funds.py --help` in a fresh process
e2e_cold_*            full CLI run (--provider analizy --symbols-file ...) with
                      an empty cache: wall time, CPU time, peak RSS, requests,
                      and new connections seen by the mock server
e2e_warm_*            the same run again, reusing the cache from the cold run
requests_maxfunds5    requests made by a cold run with --max-funds 5
parse_ms_per_fund     in-process JSON decode + AnalizyProvider.parse_payload
compute_ms_per_fund   in-process FundAnalyzer.analyze_fund on parsed data

Correctness guard
-----------------
Every run checks that computed metrics (in process and in the CLI's CSV) still
match bench/golden.json. An optimization that changes any output fails.

Usage
-----
    python bench/bench.py --out before.json
    python bench/bench.py --out after.json --compare before.json   # KEEP/REVERT
    python bench/bench.py --golden-only                             # CI check
    python bench/bench.py --update-golden    # humans only, never the loop
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent
GOLDEN_PATH = BENCH_DIR / "golden.json"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BENCH_DIR))

import mock_analizy  # noqa: E402

# Date-dependent by design (it depends on today's year), so not comparable.
GOLDEN_SKIP_COLUMNS = {"return_ytd"}
TIME_METRICS = [
    "cli_startup_s", "e2e_cold_s", "e2e_cold_cpu_s", "e2e_cold_rss_mb",
    "e2e_warm_s", "parse_ms_per_fund", "compute_ms_per_fund",
]
COUNT_METRICS = [
    "requests_cold", "connections_cold", "requests_warm", "requests_maxfunds5",
]
MIN_SIGNIFICANT_CHANGE = 0.05  # 5%, or twice the observed noise if larger


# ---------------------------------------------------------------------------
# Golden-output comparison
# ---------------------------------------------------------------------------

def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _records_by_symbol(df) -> dict:
    records = json.loads(df.to_json(orient="records", double_precision=15))
    return {r["symbol"]: r for r in records}


def compare_to_golden(df, golden: list) -> list:
    """Return human-readable mismatches between a summary frame and golden."""
    problems = []
    current = _records_by_symbol(df)
    expected = {r["symbol"]: r for r in golden}
    if set(current) != set(expected):
        problems.append(
            f"fund set differs: missing={sorted(set(expected) - set(current))} "
            f"extra={sorted(set(current) - set(expected))}"
        )
    for symbol in sorted(set(current) & set(expected)):
        cur, exp = current[symbol], expected[symbol]
        cols = (set(cur) | set(exp)) - GOLDEN_SKIP_COLUMNS
        for col in sorted(cols):
            a, b = cur.get(col, "<absent>"), exp.get(col, "<absent>")
            if _is_missing(a) and _is_missing(b):
                continue
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                    and not isinstance(a, bool) and not isinstance(b, bool):
                if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
                    continue
            elif a == b:
                continue
            problems.append(f"{symbol}.{col}: got {a!r}, golden {b!r}")
    return problems


# ---------------------------------------------------------------------------
# In-process scenarios
# ---------------------------------------------------------------------------

def _quiet():
    return contextlib.redirect_stderr(io.StringIO())


def in_process_summary(payloads: dict):
    """Run the analysis pipeline in process (single worker, no cache)."""
    from analyze_polish_funds import FundAnalyzer, FundInfo
    from providers import AnalizyProvider

    parsed, funds = {}, []
    for sym, body in payloads.items():
        payload = json.loads(body)
        parsed[sym] = AnalizyProvider.parse_payload(payload)
        funds.append(FundInfo(symbol=sym, name=AnalizyProvider.parse_label(payload)))
    analyzer = FundAnalyzer(use_cache=False, quote_source=parsed.get)
    with _quiet():
        results = analyzer.analyze_funds(funds, max_workers=1)
    return analyzer.create_summary_dataframe(results)


def time_parse_and_compute(payloads: dict, repeats: int) -> dict:
    from analyze_polish_funds import FundAnalyzer, FundInfo
    from providers import AnalizyProvider

    n = len(payloads)
    parse_runs, compute_runs = [], []
    # One untimed warm-up pass, then enough passes for a robust median: these
    # scenarios are cheap and noisy, unlike the end-to-end runs.
    for i in range(1 + max(repeats, 7)):
        t0 = time.perf_counter()
        parsed = {s: AnalizyProvider.parse_payload(json.loads(b)) for s, b in payloads.items()}
        parse_ms = (time.perf_counter() - t0) * 1000 / n

        analyzer = FundAnalyzer(use_cache=False, quote_source=parsed.get)
        funds = [FundInfo(symbol=s, name=s) for s in payloads]
        t0 = time.perf_counter()
        with _quiet():
            for fund in funds:
                analyzer.analyze_fund(fund)
        compute_ms = (time.perf_counter() - t0) * 1000 / n
        if i > 0:
            parse_runs.append(parse_ms)
            compute_runs.append(compute_ms)
    return {
        "parse_ms_per_fund": _summary(parse_runs),
        "compute_ms_per_fund": _summary(compute_runs),
    }


# ---------------------------------------------------------------------------
# Subprocess scenarios
# ---------------------------------------------------------------------------

def _env() -> dict:
    env = dict(os.environ)
    for key in ("NO_PROXY", "no_proxy"):
        env[key] = ",".join(filter(None, [env.get(key, ""), "127.0.0.1", "localhost"]))
    env["MPLBACKEND"] = "Agg"
    return env


def time_cli_startup(repeats: int) -> dict:
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "analyze_polish_funds.py"), "--help"],
            cwd=REPO_ROOT, env=_env(), capture_output=True, check=True, timeout=120,
        )
        runs.append(time.perf_counter() - t0)
    return _summary(runs)


def run_cli(server, workdir: Path, symbols_file: Path, extra_args=()) -> dict:
    """One CLI run in `workdir` (its .fund_cache persists between calls)."""
    stats_path = workdir / "run_stats.json"
    log_path = workdir / "cli_stderr.log"
    cmd = [
        sys.executable, str(BENCH_DIR / "_run_cli.py"),
        server.url_template, str(stats_path), "--",
        "--provider", "analizy", "--symbols-file", str(symbols_file),
        "--output", str(workdir / "out"), *extra_args,
    ]
    server.stats.reset()
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=workdir, env=_env(), capture_output=True,
                          text=True, timeout=600)
    wall = time.perf_counter() - t0
    log_path.write_text(proc.stdout + proc.stderr)
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    return {
        "wall_s": wall,
        "cpu_s": stats.get("cpu_s"),
        "rss_mb": (stats.get("max_rss_kb") or 0) / 1024,
        "exit_code": stats.get("exit_code", proc.returncode),
        "requests": server.stats.requests,
        "connections": server.stats.connections,
        "csv": workdir / "out.csv",
        "log": log_path,
    }


def _check_csv(run: dict, golden: list, label: str) -> list:
    import pandas as pd

    if run["exit_code"] != 0 or not run["csv"].exists():
        tail = run["log"].read_text()[-1500:] if run["log"].exists() else ""
        return [f"{label}: CLI failed (exit {run['exit_code']}). stderr tail:\n{tail}"]
    return [f"{label}: {p}" for p in compare_to_golden(pd.read_csv(run["csv"]), golden)]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _summary(runs: list) -> dict:
    """Median plus a relative spread: IQR when there are enough runs, else range."""
    med = statistics.median(runs)
    if len(runs) >= 5:
        q1, _, q3 = statistics.quantiles(runs, n=4)
        spread = q3 - q1
    else:
        spread = max(runs) - min(runs)
    return {
        "median": med, "min": min(runs), "max": max(runs),
        "noise": spread / med if med else 0.0,
        "runs": runs,
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                               capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def _fmt(metric: str, value) -> str:
    if isinstance(value, dict):
        return f"{value['median']:.3f} (±{value['noise'] * 100:.0f}%)"
    return str(value)


def compare(before: dict, after: dict) -> int:
    """Print per-metric deltas and an overall KEEP/REVERT verdict."""
    improved, regressed = [], []
    print(f"\n{'metric':<22}{'before':>20}{'after':>20}{'change':>10}  verdict")
    for metric in TIME_METRICS + COUNT_METRICS:
        b, a = before["metrics"].get(metric), after["metrics"].get(metric)
        if b is None or a is None:
            continue
        if metric in COUNT_METRICS:
            delta = a - b
            change = f"{delta:+d}"
            verdict = "better" if delta < 0 else "WORSE" if delta > 0 else "same"
        else:
            bm, am = b["median"], a["median"]
            rel = (am - bm) / bm if bm else 0.0
            threshold = max(MIN_SIGNIFICANT_CHANGE, 2 * max(a["noise"], b["noise"]))
            change = f"{rel * 100:+.1f}%"
            verdict = ("better" if rel <= -threshold
                       else "WORSE" if rel >= threshold else "noise")
        if verdict == "better":
            improved.append(metric)
        elif verdict == "WORSE":
            regressed.append(metric)
        print(f"{metric:<22}{_fmt(metric, b):>20}{_fmt(metric, a):>20}{change:>10}  {verdict}")

    if not after.get("golden_ok"):
        decision = "REVERT (golden outputs changed)"
    elif regressed:
        decision = f"REVERT (regressed: {', '.join(regressed)})"
    elif not improved:
        decision = "REVERT (no significant improvement)"
    else:
        decision = f"KEEP (improved: {', '.join(improved)})"
    print(f"\nVERDICT: {decision}")
    return 0 if decision.startswith("KEEP") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--startup-repeats", type=int, default=5)
    parser.add_argument("--out", type=Path, help="write results JSON here")
    parser.add_argument("--compare", type=Path, help="earlier results JSON to compare against")
    parser.add_argument("--golden-only", action="store_true",
                        help="only check outputs against golden.json (used in CI)")
    parser.add_argument("--update-golden", action="store_true",
                        help="rewrite golden.json from the current code (humans only)")
    args = parser.parse_args()

    payloads = mock_analizy.build_payloads()

    if args.update_golden:
        df = in_process_summary(payloads)
        golden = sorted(json.loads(df.to_json(orient="records", double_precision=15)),
                        key=lambda r: r["symbol"])
        GOLDEN_PATH.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n")
        print(f"Wrote {len(golden)} golden records to {GOLDEN_PATH}")
    if not GOLDEN_PATH.exists():
        print("bench/golden.json is missing; run with --update-golden first.", file=sys.stderr)
        return 2
    golden = json.loads(GOLDEN_PATH.read_text())

    problems = [f"in-process: {p}" for p in compare_to_golden(in_process_summary(payloads), golden)]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        symbols_file = tmp / "symbols.txt"
        symbols_file.write_text("\n".join(mock_analizy.symbols()) + "\n")

        with mock_analizy.MockAnalizyServer() as server:
            if args.golden_only or args.update_golden:
                workdir = tmp / "golden_run"
                workdir.mkdir()
                problems += _check_csv(run_cli(server, workdir, symbols_file), golden, "cli")
                for p in problems[:20]:
                    print(f"GOLDEN MISMATCH {p}")
                print("golden: PASS" if not problems else f"golden: FAIL ({len(problems)} mismatches)")
                return 0 if not problems else 1

            print("Measuring CLI startup...", file=sys.stderr)
            metrics = {"cli_startup_s": time_cli_startup(args.startup_repeats)}

            cold, warm = [], []
            for i in range(args.repeats):
                print(f"End-to-end run {i + 1}/{args.repeats} (cold + warm)...", file=sys.stderr)
                workdir = tmp / f"e2e_{i}"
                workdir.mkdir()
                cold.append(run_cli(server, workdir, symbols_file))
                problems += _check_csv(cold[-1], golden, f"cli cold run {i + 1}")
                warm.append(run_cli(server, workdir, symbols_file))
                problems += _check_csv(warm[-1], golden, f"cli warm run {i + 1}")

            maxfunds_dir = tmp / "maxfunds"
            maxfunds_dir.mkdir()
            maxfunds = run_cli(server, maxfunds_dir, symbols_file, ["--max-funds", "5"])

        metrics.update({
            "e2e_cold_s": _summary([r["wall_s"] for r in cold]),
            "e2e_cold_cpu_s": _summary([r["cpu_s"] or 0.0 for r in cold]),
            "e2e_cold_rss_mb": _summary([r["rss_mb"] for r in cold]),
            "e2e_warm_s": _summary([r["wall_s"] for r in warm]),
            "requests_cold": max(r["requests"] for r in cold),
            "connections_cold": max(r["connections"] for r in cold),
            "requests_warm": max(r["requests"] for r in warm),
            "requests_maxfunds5": maxfunds["requests"],
        })
    metrics.update(time_parse_and_compute(payloads, args.repeats))

    result = {
        "meta": {
            "commit": _git_commit(),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} cpus",
            "universe": len(mock_analizy.UNIVERSE),
            "repeats": args.repeats,
            "latency_model": "60 ms per new connection + 40 ms per request",
        },
        "golden_ok": not problems,
        "golden_problems": problems[:20],
        "metrics": metrics,
    }

    print(f"\nCommit {result['meta']['commit']} · {result['meta']['machine']}")
    for metric in TIME_METRICS + COUNT_METRICS:
        print(f"  {metric:<22}{_fmt(metric, metrics[metric]):>20}")
    print("  golden outputs        " + ("PASS" if not problems else f"FAIL ({len(problems)})"))
    for p in problems[:10]:
        print(f"    {p}")

    if args.out:
        args.out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    if args.compare:
        return compare(json.loads(args.compare.read_text()), result)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
