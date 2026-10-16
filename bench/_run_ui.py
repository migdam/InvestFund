"""
Run the dashboard's live screening once in a fresh process, through Streamlit's
AppTest harness, pointed at the mock analizy.pl server. Used by bench.py.

Usage:
    python bench/_run_ui.py BASE_URL STATS_OUT SYMBOLS_FILE OUT_CSV

BASE_URL replaces providers.AnalizyProvider.BASE_URL, which is the single
injection point the benchmark relies on. The dashboard is loaded with its
defaults (which fetch nothing), given SYMBOLS_FILE's symbols with Max funds 0,
and then Run analysis is clicked: `run_s` times that rerun, from the click
until the page has been rebuilt. The results table goes to OUT_CSV for the
golden check.
"""

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    base_url, stats_out, symbols_file, out_csv = sys.argv[1:]

    sys.path.insert(0, str(REPO_ROOT))
    import providers
    from streamlit.testing.v1 import AppTest

    providers.AnalizyProvider.BASE_URL = base_url

    at = AppTest.from_file(str(REPO_ROOT / "dashboard.py"), default_timeout=600).run()
    at.text_area(key="symbols_analizy").set_value(Path(symbols_file).read_text())
    at.number_input(key="max_funds").set_value(0)
    button = at.button(key="run_screen").click()
    t0 = time.perf_counter()
    button.run()
    run_s = time.perf_counter() - t0

    errors = [str(e.value) for e in at.exception] + [e.value for e in at.error]
    try:
        df = at.session_state["screen_df"]
    except KeyError:
        df = None
    ok = not errors and df is not None and not df.empty
    if ok:
        df.to_csv(out_csv, index=False)
    for message in errors:
        print(message, file=sys.stderr)
    Path(stats_out).write_text(json.dumps({"exit_code": 0 if ok else 1, "run_s": run_s}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
