# Efficiency loop log

State for the loop described in `bench/EFFICIENCY_LOOP.md`. Each iteration
reads this file first and appends to it last.

- **Branch:** `claude/enhance-funds-analysis-017gvWUhpDKdUP1bNAL1w9vV` (PR #1)
- **Start commit:** `e5d49e1` (benchmark frozen, app code unchanged)
- **Iterations logged:** 4

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

1. **Slow startup (1.8–2.2 s, even for `--help`).** Module-level imports of
   `scipy.stats` (≈0.58 s cumulative, used only for skew, kurtosis and
   percentile ranks) and `matplotlib.pyplot` (≈0.51 s) plus `seaborn` (only
   needed with `--plots`). Idea: import them inside the functions that use
   them. Evidence: a validation run of the benchmark with lazy plotting imports
   alone measured startup −24%, cold run −8%, RSS −11% (verdict KEEP).
2. **Daily returns recomputed about six times per fund**: 225 `pct_change`
   calls for 38 funds; `calculate_calmar_ratio` recomputes the max drawdown;
   `calculate_statistics` (scipy skew/kurtosis) is about 28% of compute time.
   Idea: compute returns once per fund and pass them in. Trap: results must
   stay within the golden tolerance (1e-9 relative), so keep the same pandas
   and scipy operations, just do them once.
3. **`parse_payload` builds a list of tuples, then a DataFrame** (8.7 ms per
   fund). Build the columns directly. Lower priority: parse plus compute is
   about 15 ms per fund against about 100 ms of network per fund in the mock.
4. **Warm runs read each cache file twice**: `fetch_funds` loads the pickle to
   get the name, then `download_quotes` loads it again for the analysis
   (39 extra loads per warm run). Not measured yet; likely small.

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

### Iteration 2 — 2026-10-15 — KEPT
Hypothesis: a warm run downloaded all 40 symbols only to learn the names of 39
funds whose quotes were already cached. Storing the name with the cached quotes
(`df.attrs`, which survives the pickle cache) and listing cached funds without
a request should cut `requests_warm` 40 → 1 (only the uncached 404 symbol is
asked again) and `e2e_warm_s` by about 10–15%. This also matches the README's
documented caching ("fund list cached for 1 day", "work offline if the cache
is fresh"), which the analizy path did not honor.
Change: `FundAnalyzer.cached_quotes` (read-only cache lookup; `download_quotes`
now uses it), `fetch_funds(..., cached=...)` serves named cache entries and
stamps the name on fetched quotes; `main()` passes the analyzer's cache
(`analyze_polish_funds.py`, `providers.py`). Seven new checks in
`test_providers.py`, including a round trip through the on-disk cache.
Edge case, by design: a fund that stops resolving within the 1-day cache
lifetime is now still listed from cache, as its cached quotes already were.
Cache files written before this change carry no name, so they are fetched once
more until they expire.
Verdict: KEEP (improved: requests_warm)

| metric | before | after | change |
|---|---|---|---|
| `requests_warm` | 40 | 1 | −39 |
| `e2e_warm_s` | 4.06 s | 3.04 s | −25.1%, classed as noise (±14% spread) |

Golden outputs: PASS (both). Commit: `perf: list cached analizy funds without a request`

### Iteration 3 — 2026-10-15 — KEPT
Hypothesis: `--max-funds 5` fetched all 40 symbols and then kept the first 5
that resolved. Fetching in file order only until N symbols have resolved (a
batch of N, then one more batch per failure) should cut `requests_maxfunds5`
40 → 6 (the first five include the 404, so one extra symbol is needed) with
identical output, and leave the other scenarios unchanged (40 symbols is below
the default `--max-funds` of 50).
Change: `fetch_funds(..., limit=N)` fetches the shortest prefix of the symbol
list that holds N resolved symbols, so it lists exactly what a full fetch would
list first; cached funds count toward N without a request. `main()` passes
`--max-funds` and says so on the console (`providers.py`,
`analyze_polish_funds.py`). Five new checks in `test_providers.py`.
Note: `--max-funds` defaults to 50, so a plain run on more than 50 symbols now
also stops once 50 have resolved (same mechanism; not exercised by the
40-symbol benchmark).
Verdict: KEEP (improved: requests_maxfunds5)

| metric | before | after | change |
|---|---|---|---|
| `requests_maxfunds5` | 40 | 6 | −34 |

Golden outputs: PASS (both; `--max-funds 5` still yields the same 4 funds).
Commit: `perf: stop fetching once --max-funds symbols have resolved`

### Iteration 4 — 2026-10-15 — KEPT
Hypothesis: every request opened a new connection (`connections_cold` 40),
paying the handshake each time. Reusing one keep-alive connection per worker
thread (a `requests.Session` per thread; `Session` is not documented as
thread-safe) should cut `connections_cold` 40 → at most 10 with requests
unchanged. Only ~3 handshakes per worker are saved (~0.2 s in the mock), so
the run time should stay within noise; on real HTTPS each saved handshake is
worth more.
Change: `AnalizyProvider` keeps a thread-local `requests.Session` and
`_fetch_json` uses it (`providers.py`). Four new checks in `test_providers.py`
make real HTTP round trips against the local mock (one connection per thread,
errors still return None); reverting to `requests.get` fails them (checked).
Verdict: KEEP (improved: connections_cold)

| metric | before | after | change |
|---|---|---|---|
| `connections_cold` | 40 | 10 | −30 |

Golden outputs: PASS (both). Commit: `perf: reuse one keep-alive connection per worker thread`
