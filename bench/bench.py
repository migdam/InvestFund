#!/usr/bin/env python3
"""
Offline efficiency benchmark for the analizy.pl path of analyze_polish_funds
and of the dashboard, which screens funds with the same code.

Everything runs locally against bench/mock_analizy.py, so results do not
depend on network access to analizy.pl and the third-party site is never hit.

Scenarios
---------
cli_startup_s         `analyze_polish_funds.py --help` in a fresh process
e2e_cold_*            full CLI run (--provider analizy --symbols-file ...) with
                      an empty cache: wall time, CPU time, peak RSS, requests,
                      and new connections seen by the mock server
e2e_warm_*            the same run again, reusing the cache from the cold run
requests_maxfunds5    requests made by a cold run with --max-funds 5 (its output
                      is checked against bench/golden_maxfunds5.json)
ui_cold_s             the dashboard's live screening of the same symbols (Max
                      funds 0, empty cache) through Streamlit's AppTest in a
                      fresh process: time from clicking Run analysis until the
                      page is rebuilt (excludes loading Streamlit itself)
ui_requests_cold      requests made by that dashboard run
parse_ms_per_fund     in-process JSON decode + AnalizyProvider.parse_payload
compute_ms_per_fund   in-process FundAnalyzer.analyze_fund on parsed data

Correctness guard
-----------------
Every run checks that computed metrics (in process, in the CLI's CSV and in
the dashboard's results table) still match bench/golden.json. An optimization
that changes any output fails.

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
GOLDEN_MAXFUNDS_PATH = BENCH_DIR / "golden_maxfunds5.json"
# --max-funds N analyzes the first N symbols that resolve, in file order. A 404
# and a too-short fund sit among the first five to pin those semantics down.
MAXFUNDS_EARLY = ["BENCH00", "MISSING01", "SHORT15"]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BENCH_DIR))

import mock_analizy  # noqa: E402

# Date-dependent by design (it depends on today's year), so not comparable.
GOLDEN_SKIP_COLUMNS = {"return_ytd"}
TIME_METRICS = [
    "cli_startup_s", "e2e_cold_s", "e2e_cold_cpu_s", "e2e_cold_rss_mb",
    "e2e_warm_s", "ui_cold_s", "parse_ms_per_fund", "compute_ms_per_fund",
]
COUNT_METRICS = [
    "requests_cold", "connections_cold", "requests_warm", "requests_maxfunds5",
    "ui_requests_cold",
]
# Cheap, repeatable scenarios are compared on their fastest run (noise only
# adds time, so best-of-N is stable while medians drift with machine load);
# the end-to-end runs are compared on their median.
BEST_OF_METRICS = {"cli_startup_s", "parse_ms_per_fund", "compute_ms_per_fund"}
# A timing change counts only beyond this floor (or twice the noise if larger).
MIN_SIGNIFICANT_CHANGE = {"best_of": 0.15, "median": 0.05}


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
    if golden and list(df.columns) != list(golden[0]):
        problems.append(f"column order differs: got {list(df.columns)}, golden {list(golden[0])}")
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
    for i in range(1 + max(repeats, 9)):
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
        "parse_ms_per_fund": _summary(parse_runs, best_of=True),
        "compute_ms_per_fund": _summary(compute_runs, best_of=True),
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
    return _summary(runs, best_of=True)


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


def run_ui(server, workdir: Path, symbols_file: Path) -> dict:
    """One dashboard screening run in a fresh process, started in `workdir`."""
    stats_path = workdir / "ui_stats.json"
    log_path = workdir / "ui_stderr.log"
    csv_path = workdir / "ui.csv"
    cmd = [
        sys.executable, str(BENCH_DIR / "_run_ui.py"),
        server.url_template, str(stats_path), str(symbols_file), str(csv_path),
    ]
    server.stats.reset()
    proc = subprocess.run(cmd, cwd=workdir, env=_env(), capture_output=True,
                          text=True, timeout=600)
    log_path.write_text(proc.stdout + proc.stderr)
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    return {
        "wall_s": stats.get("run_s"),
        "exit_code": stats.get("exit_code", proc.returncode),
        "requests": server.stats.requests,
        "csv": csv_path,
        "log": log_path,
    }


def _check_csv(run: dict, golden: list, label: str) -> list:
    import pandas as pd

    if run["exit_code"] != 0 or not run["csv"].exists():
        tail = run["log"].read_text()[-1500:] if run["log"].exists() else ""
        return [f"{label}: CLI failed (exit {run['exit_code']}). stderr tail:\n{tail}"]
    df = pd.read_csv(run["csv"])
    found = compare_to_golden(df, golden)
    if "score" in df.columns and not df["score"].is_monotonic_decreasing:
        found.append("rows are not sorted by score, highest first")
    return [f"{label}: {p}" for p in found]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _summary(runs: list, best_of: bool = False) -> dict:
    """
    Headline value plus a relative noise estimate.

    best_of: value is the fastest run; noise is the gap to the second fastest
    (a loose lower envelope means the minimum itself is unreliable).
    Otherwise: value is the median; noise is the IQR (>= 5 runs) or the range.
    """
    ordered = sorted(runs)
    med = statistics.median(runs)
    if best_of:
        value = ordered[0]
        spread = ordered[1] - ordered[0] if len(ordered) > 1 else 0.0
    else:
        value = med
        if len(runs) >= 5:
            q1, _, q3 = statistics.quantiles(runs, n=4)
            spread = q3 - q1
        else:
            spread = ordered[-1] - ordered[0]
    return {
        "value": value, "stat": "best_of" if best_of else "median",
        "median": med, "min": ordered[0], "max": ordered[-1],
        "noise": spread / value if value else 0.0,
        "runs": runs,
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
                               capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def _fmt(metric: str, value) -> str:
    if isinstance(value, dict):
        tag = "best" if value.get("stat") == "best_of" else "med"
        return f"{value['value']:.3f} {tag} ±{value['noise'] * 100:.0f}%"
    return str(value)


def compare(before: dict, after: dict) -> int:
    """Print per-metric deltas and an overall KEEP/REVERT verdict."""
    improved, regressed = [], []
    print(f"\n{'metric':<22}{'before':>22}{'after':>22}{'change':>10}  verdict")
    for metric in TIME_METRICS + COUNT_METRICS:
        b, a = before["metrics"].get(metric), after["metrics"].get(metric)
        if b is None or a is None:
            continue
        if metric in COUNT_METRICS:
            delta = a - b
            change = f"{delta:+d}"
            verdict = "better" if delta < 0 else "WORSE" if delta > 0 else "same"
        else:
            bm, am = b["value"], a["value"]
            rel = (am - bm) / bm if bm else 0.0
            floor = MIN_SIGNIFICANT_CHANGE[a.get("stat", "median")]
            threshold = max(floor, 2 * max(a["noise"], b["noise"]))
            change = f"{rel * 100:+.1f}%"
            verdict = ("better" if rel <= -threshold
                       else "WORSE" if rel >= threshold else "noise")
        if verdict == "better":
            improved.append(metric)
        elif verdict == "WORSE":
            regressed.append(metric)
        print(f"{metric:<22}{_fmt(metric, b):>22}{_fmt(metric, a):>22}{change:>10}  {verdict}")

    # Best-of microbenchmarks still drift ~10% between runs with machine state,
    # so a decision that rests only on them must be re-measured (CONFIRM)
    # rather than trusted from a single before/after pair.
    def micro_only(metrics):
        return all(m in BEST_OF_METRICS for m in metrics)

    if not after.get("golden_ok"):
        decision = "REVERT (golden outputs changed)"
    elif regressed and not micro_only(regressed):
        decision = f"REVERT (regressed: {', '.join(regressed)})"
    elif regressed:
        decision = (f"CONFIRM (only noisy microbenchmarks regressed: {', '.join(regressed)}; "
                    "re-measure before and after once, then follow the new verdict)")
    elif not improved:
        decision = "REVERT (no significant improvement)"
    elif micro_only(improved):
        decision = (f"CONFIRM (only noisy microbenchmarks improved: {', '.join(improved)}; "
                    "re-measure before and after once, then follow the new verdict)")
    else:
        decision = f"KEEP (improved: {', '.join(improved)})"
    print(f"\nVERDICT: {decision}")
    if decision.startswith("KEEP"):
        return 0
    return 3 if decision.startswith("CONFIRM") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--startup-repeats", type=int, default=7)
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
        maxfunds_file = tmp / "symbols_maxfunds.txt"
        maxfunds_file.write_text("\n".join(
            MAXFUNDS_EARLY + [s for s in mock_analizy.symbols() if s not in MAXFUNDS_EARLY]
        ) + "\n")
        maxfunds_args = ["--max-funds", "5"]

        with mock_analizy.MockAnalizyServer() as server:
            if args.update_golden:
                import pandas as pd
                workdir = tmp / "golden_maxfunds"
                workdir.mkdir()
                run = run_cli(server, workdir, maxfunds_file, maxfunds_args)
                if run["exit_code"] != 0 or not run["csv"].exists():
                    print(run["log"].read_text()[-1500:], file=sys.stderr)
                    return 2
                records = sorted(
                    json.loads(pd.read_csv(run["csv"]).to_json(orient="records", double_precision=15)),
                    key=lambda r: r["symbol"],
                )
                GOLDEN_MAXFUNDS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n")
                print(f"Wrote {len(records)} golden records to {GOLDEN_MAXFUNDS_PATH}")
            if not GOLDEN_MAXFUNDS_PATH.exists():
                print("bench/golden_maxfunds5.json is missing; run with --update-golden first.",
                      file=sys.stderr)
                return 2
            golden_maxfunds = json.loads(GOLDEN_MAXFUNDS_PATH.read_text())

            if args.golden_only or args.update_golden:
                workdir = tmp / "golden_run"
                workdir.mkdir()
                problems += _check_csv(run_cli(server, workdir, symbols_file), golden, "cli")
                workdir = tmp / "golden_maxfunds_check"
                workdir.mkdir()
                problems += _check_csv(run_cli(server, workdir, maxfunds_file, maxfunds_args),
                                       golden_maxfunds, "cli --max-funds 5")
                workdir = tmp / "golden_ui"
                workdir.mkdir()
                problems += _check_csv(run_ui(server, workdir, symbols_file), golden, "dashboard")
                for p in problems[:20]:
                    print(f"GOLDEN MISMATCH {p}")
                print("golden: PASS" if not problems else f"golden: FAIL ({len(problems)} mismatches)")
                return 0 if not problems else 1

            print("Measuring CLI startup...", file=sys.stderr)
            metrics = {"cli_startup_s": time_cli_startup(args.startup_repeats)}

            cold, warm, ui = [], [], []
            for i in range(args.repeats):
                print(f"End-to-end run {i + 1}/{args.repeats} (cold + warm + dashboard)...",
                      file=sys.stderr)
                workdir = tmp / f"e2e_{i}"
                workdir.mkdir()
                cold.append(run_cli(server, workdir, symbols_file))
                problems += _check_csv(cold[-1], golden, f"cli cold run {i + 1}")
                warm.append(run_cli(server, workdir, symbols_file))
                problems += _check_csv(warm[-1], golden, f"cli warm run {i + 1}")
                workdir = tmp / f"ui_{i}"
                workdir.mkdir()
                ui.append(run_ui(server, workdir, symbols_file))
                problems += _check_csv(ui[-1], golden, f"dashboard run {i + 1}")

            maxfunds_dir = tmp / "maxfunds"
            maxfunds_dir.mkdir()
            maxfunds = run_cli(server, maxfunds_dir, maxfunds_file, maxfunds_args)
            problems += _check_csv(maxfunds, golden_maxfunds, "cli --max-funds 5")

        metrics.update({
            "e2e_cold_s": _summary([r["wall_s"] for r in cold]),
            "e2e_cold_cpu_s": _summary([r["cpu_s"] or 0.0 for r in cold]),
            "e2e_cold_rss_mb": _summary([r["rss_mb"] for r in cold]),
            "e2e_warm_s": _summary([r["wall_s"] for r in warm]),
            "ui_cold_s": _summary([r["wall_s"] or 0.0 for r in ui]),
            "requests_cold": max(r["requests"] for r in cold),
            "connections_cold": max(r["connections"] for r in cold),
            "requests_warm": max(r["requests"] for r in warm),
            "requests_maxfunds5": maxfunds["requests"],
            "ui_requests_cold": max(r["requests"] for r in ui),
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
        print(f"  {metric:<22}{_fmt(metric, metrics[metric]):>22}")
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
