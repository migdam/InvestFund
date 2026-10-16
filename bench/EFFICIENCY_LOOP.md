# Efficiency loop

Instructions for an agent that improves this app's efficiency one verified
change at a time. Each run of the loop performs **one iteration** and keeps its
state in `bench/LOG.md`, so it survives context compaction and fresh containers.

## Start it

In Claude Code (terminal or a cloud session), from the repository root:

```
/loop Run the next iteration of bench/EFFICIENCY_LOOP.md
```

Without an interval the agent paces itself. With one (e.g. `/loop 15m …`), use
an interval longer than an iteration (5–10 minutes). In a fresh environment run
`pip install -r requirements.txt` first. No access to analizy.pl is needed:
everything is measured against a local mock of its API.

## Goal

Make the analizy.pl screening path (`--provider analizy --symbols-file …`, and
the dashboard's live screening, which runs the same `screen_funds`) cheaper —
fewer requests and connections, less wall time, CPU, memory and startup time —
**without changing any output**. Progress is whatever
`bench/bench.py` measures, nothing else. "Most efficient in the world" is not
a claim this loop can check, so it never makes it: it optimizes this benchmark
until the gains run out and reports raw numbers.

## Rules

Breaking a rule is never the way forward: if one blocks progress, stop and
report why (see Finish).

1. **Outputs are frozen.** A change is only kept if the benchmark reports
   `golden outputs PASS`. Never touch `bench/golden.json` and never run
   `bench.py --update-golden`. A change that "fixes" a number is a behavior
   change: propose it under *Needs approval* in the log instead.
2. **The benchmark is frozen.** Do not edit anything in `bench/` except
   `bench/LOG.md`. If you believe the benchmark is wrong or is blocking a
   genuinely good change, stop and explain.
3. **Tests stay green and meaningful.** All offline suites must pass after the
   change (command in step 5). Never delete, skip or loosen a test or an
   assertion. Adding tests is welcome.
4. **User-facing behavior is frozen:** CLI flags and defaults, output files,
   columns and formats, chart resolution, report contents. Console progress
   messages may change only if they stay accurate.
5. **Be gentle with real servers.** Never raise the default `--workers` (10),
   never put more simultaneous requests on an external host than `--workers`,
   never add retries that send extra requests, never shorten cache lifetimes.
   Prefer removing requests over parallelizing them.
6. **Every analizy.pl request goes through `providers.AnalizyProvider.BASE_URL`.**
   It is the benchmark's injection point.
7. **One idea per iteration**, the smallest diff that tests it. No new
   dependencies: list such ideas under *Needs approval*.
8. **Only optimize what the benchmark exercises:** CLI startup, symbol
   discovery, download, parsing, metrics, CSV export on the analizy path, and
   the dashboard's live analizy.pl screening run (`ui_cold_s`; the user added
   this scenario on 2026-10-16). Stooq (needs an API key), the dashboard's
   other views and Demo mode, plots, portfolio, correlation and the
   HTML/Excel/JSON exporters are out of scope, because their effect cannot be
   measured or golden-checked here.
9. **The verdict decides.** Never keep a change the benchmark did not mark
   KEEP. You may still revert a KEEP you judge unsafe.

## One iteration

**0. Orient**

```
git status --porcelain     # must print nothing — otherwise stop: never commit someone else's changes
git branch --show-current  # must be the branch named in bench/LOG.md
git pull --ff-only
```

Read `bench/LOG.md`: past iterations, the backlog, and ideas already tried.

**1. Check the stop conditions** (below). If one holds, go to *Finish*.

**2. Measure before**, on the clean HEAD:

```
mkdir -p bench/.runs
python bench/bench.py --out bench/.runs/before.json
```

If `golden outputs` fails on a clean HEAD, stop: something is already broken.

**3. Choose one idea:** the top backlog item, unless the numbers or a profile
point to something bigger. Useful probes:

```
python -X importtime analyze_polish_funds.py --help 2>&1 >/dev/null | sort -t'|' -k2 -n | tail -15
python - <<'PY'
import cProfile, json, pstats, sys
sys.path[:0] = [".", "bench"]
import mock_analizy
from providers import AnalizyProvider
from analyze_polish_funds import FundAnalyzer, FundInfo
payloads = mock_analizy.build_payloads()
parsed = {s: AnalizyProvider.parse_payload(json.loads(b)) for s, b in payloads.items()}
analyzer = FundAnalyzer(use_cache=False, quote_source=parsed.get)
cProfile.run("[analyzer.analyze_fund(FundInfo(s, s)) for s in parsed]", "bench/.runs/prof")
pstats.Stats("bench/.runs/prof").sort_stats("cumtime").print_stats(15)
PY
```

Write the hypothesis down before editing: *"X costs about Y (evidence);
changing Z should move metric M by about N%."*

**4. Implement** the smallest change that tests the hypothesis.

**5. Check correctness:**

```
for t in test_with_mocks test_code_quality test_dashboard test_rebalancing test_alerts \
         test_metrics_advanced test_workflow test_providers test_build_map; do
  python $t.py > /dev/null 2>&1 || echo "FAIL $t"
done
ruff check --select=E9,F63,F7,F82,F401,F841 --target-version=py310 .
```

Fix failures within the same idea, or revert (7b). `test_analyzer.py` calls the
real analizy.pl: do not run it every iteration — at most once at *Finish*, and
only where analizy.pl is reachable.

**6. Measure after and follow the verdict:**

```
python bench/bench.py --out bench/.runs/after.json --compare bench/.runs/before.json
```

- `KEEP` → 7a.
- `REVERT` → 7b.
- `CONFIRM` (the decision rests only on noisy microbenchmarks) → re-measure
  both sides once, then follow the new verdict; a second `CONFIRM` counts as
  `REVERT`:

  ```
  git stash push --include-untracked -m efficiency-loop
  python bench/bench.py --out bench/.runs/before.json
  git stash pop
  python bench/bench.py --out bench/.runs/after.json --compare bench/.runs/before.json
  ```

**7a. Keep.** Add the log entry (format below) and commit code and log
together. Subject `perf: <what changed>`; the body gives the hypothesis and
before → after for each metric that moved, copied from the compare output.
Push with `git push origin HEAD` (on network errors retry after 2, 4, 8, 16 s).

**7b. Revert.** `git reset --hard HEAD && git clean -fd` (safe: step 0 started
from a clean tree; never add `-x`). Then add the log entry with the numbers and
the reason, commit only `bench/LOG.md`, and push. Failed ideas must be logged
so they are not retried.

**8. Continue.** Self-paced, schedule the next iteration about a minute out —
there is nothing external to wait for. If a stop condition now holds, go to
*Finish*.

## Stop conditions

- three iterations in a row ended in REVERT;
- the backlog is empty and a fresh profile shows nothing worth at least 5% of
  `e2e_cold_s` or `ui_cold_s`, or 15% of `cli_startup_s`;
- 15 iterations have been logged;
- progress would require breaking a rule;
- tests or the golden check fail on a clean HEAD.

## Finish

1. Measure the starting point and the current HEAD on the same machine (the
   numbers in `bench/baseline.json` come from a different machine):

   ```
   git worktree add bench/.runs/start <start commit from bench/LOG.md>
   (cd bench/.runs/start && python bench/bench.py --out ../start.json)
   git worktree remove --force bench/.runs/start
   python bench/bench.py --out bench/.runs/final.json --compare bench/.runs/start.json
   ```

2. Write a summary at the top of `bench/LOG.md`: start → final for every
   metric, the kept changes (commit list), notable reverted ideas, the
   *Needs approval* list, and why the loop stopped.
3. If analizy.pl is reachable, run `python test_analyzer.py` once as a live
   check and record the result.
4. Commit, push, end the loop, and tell the user in plain words what improved,
   by how much, and what was not verified.

## Log entry format

Append to the *Iterations* section of `bench/LOG.md`, then update the backlog
(remove the item, add new ideas, move dead ends to *Tried and rejected*):

```
### Iteration N — YYYY-MM-DD — KEPT | REVERTED
Hypothesis: …
Change: … (files)
Verdict: <the VERDICT line>
| metric | before | after | change |     ← only metrics that moved
Commit: <sha> | reverted
```
