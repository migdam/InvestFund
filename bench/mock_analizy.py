"""
Offline stand-in for the analizy.pl quotation API, used by bench.py.

Serves ``/api/quotation/fio/<SYMBOL>`` with deterministic synthetic payloads in
the same JSON shape as the real endpoint (verified against a live ING35
response): a ``label`` plus a ``series`` list holding the plain NAV series and
an empty dividend-adjusted series.

The server models network cost so that request count and connection reuse
are measurable offline:

- ``connect_latency``: paid once per new TCP connection (stands in for the
  TCP + TLS handshake to the real host)
- ``request_latency``: paid on every request (round trip + server time)

These numbers are a model, not a measurement of analizy.pl.
"""

from __future__ import annotations

import json
import re
import threading
import time
import zlib
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

import numpy as np
import pandas as pd

# (symbol, number of daily NAV points). Lengths vary so the fixture exercises
# the metric branches gated on history length; the last three are edge cases.
_NORMAL = [(f"BENCH{i:02d}", 300 + (i * 997) % 3800) for i in range(37)]
UNIVERSE: List[tuple] = _NORMAL + [
    ("SHORT15", 15),       # < 20 rows: skipped by analyze_fund
    ("YOUNG120", 120),     # < 252 rows: Sharpe/Sortino/Calmar are None
    ("MISSING01", 0),      # unknown symbol: the server answers 404
]


def symbols() -> List[str]:
    """All symbols in the benchmark universe, in a fixed order."""
    return [sym for sym, _ in UNIVERSE]


def make_payload(symbol: str, n_points: int) -> dict:
    """Deterministic analizy.pl-shaped payload for one symbol."""
    rng = np.random.RandomState(zlib.crc32(symbol.encode()))
    drift = rng.uniform(-0.0002, 0.0006)
    vol = rng.uniform(0.003, 0.02)
    steps = rng.normal(drift, vol, n_points)
    values = np.round(100.0 * np.cumprod(1.0 + steps), 2)
    # Business days ending today: metrics are index-based, so they do not
    # depend on the calendar date (only the YTD return does).
    dates = pd.bdate_range(end=pd.Timestamp(date.today()), periods=n_points)
    return {
        "id": symbol,
        "label": f"Fundusz Testowy Spółek {symbol}",
        "currency": "PLN",
        "isRegular": True,
        "isDividend": False,
        "series": [
            {
                "id": f"fund_{symbol}",
                "label": "Fundusz",
                "currency": "PLN",
                "price": [
                    {"date": d.strftime("%Y-%m-%d"), "value": float(v)}
                    for d, v in zip(dates, values)
                ],
            },
            {
                "id": f"fund_with_dividend_{symbol}",
                "label": "Fundusz z dywidendą",
                "currency": "PLN",
                "price": [],
            },
        ],
    }


def build_payloads() -> Dict[str, bytes]:
    """Encoded payloads for every resolvable symbol in the universe."""
    return {
        sym: json.dumps(make_payload(sym, n)).encode()
        for sym, n in UNIVERSE
        if n > 0
    }


class Stats:
    """Thread-safe request/connection counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests = 0
        self.connections = 0

    def reset(self):
        with self._lock:
            self.requests = 0
            self.connections = 0

    def bump(self, field: str):
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)


class MockAnalizyServer:
    """Threaded local HTTP server serving the benchmark universe."""

    _PATH = re.compile(r"^/api/quotation/fio/([^/?]+)$")

    def __init__(self, connect_latency: float = 0.060,
                 request_latency: float = 0.040):
        self.stats = Stats()
        payloads = build_payloads()
        stats = self.stats
        path_re = self._PATH

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # allow keep-alive reuse

            def setup(self):
                super().setup()
                stats.bump("connections")
                time.sleep(connect_latency)

            def do_GET(self):
                stats.bump("requests")
                time.sleep(request_latency)
                match = path_re.match(self.path)
                body = payloads.get(match.group(1)) if match else None
                if body is None:
                    body = b'{"error": "not found"}'
                    self.send_response(404)
                else:
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep benchmark output clean
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    @property
    def url_template(self) -> str:
        """Value for AnalizyProvider.BASE_URL pointing at this server."""
        port = self._httpd.server_address[1]
        return f"http://127.0.0.1:{port}/api/quotation/{{fund_type}}/{{symbol}}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
