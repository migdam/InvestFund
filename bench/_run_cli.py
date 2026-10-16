"""
Run analyze_polish_funds' real CLI in a fresh process, pointed at the mock
analizy.pl server, and record resource usage. Used by bench.py.

Usage:
    python bench/_run_cli.py BASE_URL STATS_OUT -- <analyze_polish_funds args>

BASE_URL replaces providers.AnalizyProvider.BASE_URL, which is the single
injection point the benchmark relies on.
"""

import json
import resource
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    base_url, stats_out, sep, *cli_args = sys.argv[1:]
    assert sep == "--", "usage: _run_cli.py BASE_URL STATS_OUT -- <cli args>"

    sys.path.insert(0, str(REPO_ROOT))
    import analyze_polish_funds
    import providers

    providers.AnalizyProvider.BASE_URL = base_url
    sys.argv = ["analyze_polish_funds.py", *cli_args]

    exit_code = 0
    try:
        analyze_polish_funds.main()
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        Path(stats_out).write_text(json.dumps({
            "exit_code": exit_code,
            "max_rss_kb": usage.ru_maxrss,
            "cpu_s": usage.ru_utime + usage.ru_stime,
        }))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
