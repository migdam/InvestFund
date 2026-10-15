# Efficiency loop log

State for the loop described in `bench/EFFICIENCY_LOOP.md`. Each iteration
reads this file first and appends to it last.

- **Branch:** `claude/enhance-funds-analysis-017gvWUhpDKdUP1bNAL1w9vV` (PR #1)
- **Start commit:** `e5d49e1` (benchmark frozen, app code unchanged)
- **Iterations logged:** 1

## Summary

*Written at Finish.*

## Baseline

`bench/baseline.json`, recorded at `e5d49e1` in a cloud container (Linux
x86_64, 4 CPUs, Python 3.11). Compare against these numbers only on that kind
of machine; the loop itself always measures before and after back to back.

| metric | value | what it means |
|---|---|---|
| `cli_startup_s` | 2.22 s | `--help` in a fresh process (best of 7) |
| `e2e_cold_s` | 8.73 s | full analizy run, 40 symbols, empty cache (median of 3) |
| `e2e_cold_cpu_s` | 4.79 s | CPU time of that run |
| `e2e_cold_rss_mb` | 251 MB | peak memory of that run |
| `e2e_warm_s` | 7.43 s | same run again, cache populated |
| `parse_ms_per_fund` | 8.7 ms | JSON decode + `parse_payload` (best of 9) |
| `compute_ms_per_fund` | 7.0 ms | `analyze_fund` on parsed data (best of 9) |
| `requests_cold` | 79 | requests for 39 resolvable symbols + one 404 |
| `connections_cold` | 79 | new connections (no reuse at all) |
| `requests_warm` | 40 | requests when everything is cached |
| `requests_maxfunds5` | 45 | requests for a `--max-funds 5` run |

The mock charges 60 ms per new connection and 40 ms per request; real
analizy.pl costs will differ, but the direction of each change carries over.

## Backlog

Ordered by expected gain. Each item: evidence, idea, trap.

1. **Warm runs still use the network** (`requests_warm` 40, warm run 3.55 s
   after iteration 1). `fetch_funds` always downloads every symbol to learn
   its name, even when the analyzer's cache already holds its quotes; the cache
   stores only the DataFrame, not the name. Idea: cache the name together with
   the quotes and let the fetch step serve cached symbols without a request.
   Trap: names must come out exactly as before, and a symbol that is cached
   must still count as "resolved" for `--max-funds`.
2. **`--max-funds` still fetches every symbol** (`requests_maxfunds5` 40 for
   5 funds). Fetch in file order only until N symbols have resolved (batches
   of at most `--workers`). Trap: the option means "the first N symbols that
   resolve, in file order"; a too-short fund still counts toward N and is then
   skipped. Slicing the raw symbol list first fails `golden_maxfunds5.json`
   (verified).
3. **No connection reuse** (`connections_cold` 40, one per request). Each `requests.get` opens a
   new connection. Idea: reuse connections via `requests.Session`; one session
   per worker thread (`threading.local`) is the safe pattern, as `Session` is
   not documented as thread-safe. Keep concurrency at or below `--workers`.
4. **Slow startup (1.9–2.2 s, even for `--help`).** Module-level imports of
   `scipy.stats` (≈0.58 s cumulative, used only for skew, kurtosis and
   percentile ranks) and `matplotlib.pyplot` (≈0.51 s) plus `seaborn` (only
   needed with `--plots`). Idea: import them inside the functions that use
   them. Evidence: a validation run of the benchmark with lazy plotting imports
   alone measured startup −24%, cold run −8%, RSS −11% (verdict KEEP).
5. **Daily returns recomputed about six times per fund**: 225 `pct_change`
   calls for 38 funds; `calculate_calmar_ratio` recomputes the max drawdown;
   `calculate_statistics` (scipy skew/kurtosis) is about 28% of compute time.
   Idea: compute returns once per fund and pass them in. Trap: results must
   stay within the golden tolerance (1e-9 relative), so keep the same pandas
   and scipy operations, just do them once.
6. **`parse_payload` builds a list of tuples, then a DataFrame** (8.7 ms per
   fund). Build the columns directly. Lower priority: parse plus compute is
   about 15 ms per fund against about 100 ms of network per fund in the mock.

## Needs approval

Ideas that would change behavior, add dependencies or touch out-of-scope code.
Do not implement; the user decides.

- Faster JSON or DataFrame libraries (`orjson`, `polars`): new dependencies.
- A different cache format (e.g. Parquet instead of pickle): changes files on
  disk that users may already have.
- Making `--max-funds` count only funds with enough history: changes which
  funds are analyzed.
- Lower chart resolution (`dpi=300` today): changes output files.
- Stooq path, out of scope here: `download_quotes` retries immediately (no
  backoff) even on HTTP 4xx, sending requests that cannot succeed.

## Tried and rejected

*None yet.*

## Iterations

### Iteration 1 — 2026-10-15 — KEPT
Hypothesis: discovery fetched all 40 symbols one at a time (~4 s in the mock)
and the analysis then downloaded the 39 that resolved again. Fetching each
symbol once, in file order with at most `--workers` in flight, and reusing
those responses for the analysis should cut requests and connections 79 → 40,
`requests_maxfunds5` 45 → 40, and cold and warm run time by roughly 40–50%.
Change: `AnalizyProvider.fetch_funds` (one parallel pass, same listing rules
as `get_fund_list`, returns the parsed quotes too); `main()` uses it and feeds
the analysis from those quotes (`providers.py`, `analyze_polish_funds.py`).
Seven new checks in `test_providers.py`, including that concurrency never
exceeds `max_workers`.
Verdict: KEEP (improved: e2e_cold_s, e2e_warm_s, requests_cold, connections_cold, requests_maxfunds5)

| metric | before | after | change |
|---|---|---|---|
| `e2e_cold_s` | 7.92 s | 3.45 s | −56.4% |
| `e2e_warm_s` | 7.07 s | 3.55 s | −49.7% |
| `requests_cold` | 79 | 40 | −39 |
| `connections_cold` | 79 | 40 | −39 |
| `requests_maxfunds5` | 45 | 40 | −5 |

Golden outputs: PASS (both). Commit: `perf: fetch each analizy fund once, in parallel`
