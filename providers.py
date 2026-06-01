"""
providers.py
------------

Pluggable data-source providers for fund price history, so the analyzer is not
hard-wired to a single site.

Every provider exposes ``download_quotes(symbol) -> Optional[pd.DataFrame]``
returning a DataFrame with the same schema the rest of the project expects:
columns ``Date, Open, High, Low, Close, Volume`` sorted ascending by date, with
invalid (non-positive) prices removed.

Providers
~~~~~~~~~
- :class:`StooqProvider` — wraps the existing Stooq CSV endpoint used by
  ``FundAnalyzer.download_quotes`` (kept as the default).
- :class:`AnalizyProvider` — Polish open-end funds (TFI) via the
  analizy.pl quotation JSON API. Funds report a single daily NAV, so OHLC
  columns are all set to that NAV and Volume is 0.

The analizy.pl JSON shape was verified against a real response, e.g.
``https://www.analizy.pl/api/quotation/fio/ING35``::

    {
      "id": "ING35", "label": "...", "currency": "PLN",
      "isDividend": false,
      "series": [
        {"id": "fund_ING35", "label": "Fundusz",
         "price": [{"date": "2009-11-23", "value": 100.0}, ...]},
        {"id": "fund_with_dividend_ING35", "label": "Fundusz z dywidendą",
         "price": [...]}            # populated only for distribution funds
      ]
    }

This is an undocumented endpoint; treat it as best-effort and subject to change,
and review analizy.pl's terms of use before heavy or commercial use.

This tool is for informational/educational use only and is not investment advice.
"""

from __future__ import annotations

import sys
from typing import Optional

import pandas as pd
import requests

# Reuse the project's constants/headers where helpful
from analyze_polish_funds import FundAnalyzer

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0 Safari/537.36"
    )
}

# Standard column order produced by every provider
_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


class DataProvider:
    """Abstract base class for a fund price-history source."""

    name: str = "base"

    def download_quotes(self, symbol: str) -> Optional[pd.DataFrame]:  # pragma: no cover
        raise NotImplementedError


class StooqProvider(DataProvider):
    """Default provider: delegates to the existing Stooq implementation."""

    name = "stooq"

    def __init__(self, analyzer: Optional[FundAnalyzer] = None,
                 use_cache: bool = True):
        self._analyzer = analyzer or FundAnalyzer(use_cache=use_cache)

    def download_quotes(self, symbol: str) -> Optional[pd.DataFrame]:
        return self._analyzer.download_quotes(symbol)


class AnalizyProvider(DataProvider):
    """
    Polish TFI funds via the analizy.pl quotation JSON API.

    Parameters
    ----------
    prefer_dividend : bool
        If True and a dividend-adjusted series is present and non-empty, use it
        instead of the plain NAV series (more accurate total return for
        distribution funds).
    fund_type : str
        Endpoint segment; "fio" for open-end funds (default).
    timeout : int
        HTTP timeout in seconds.
    """

    name = "analizy"
    BASE_URL = "https://www.analizy.pl/api/quotation/{fund_type}/{symbol}"

    def __init__(self, prefer_dividend: bool = False, fund_type: str = "fio",
                 timeout: int = 30, headers: Optional[dict] = None):
        self.prefer_dividend = prefer_dividend
        self.fund_type = fund_type
        self.timeout = timeout
        self.headers = headers or _DEFAULT_HEADERS

    # -- network ---------------------------------------------------------

    def _fetch_json(self, symbol: str) -> Optional[dict]:
        url = self.BASE_URL.format(fund_type=self.fund_type, symbol=symbol)
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"Warning: analizy.pl fetch failed for {symbol}: {exc}",
                  file=sys.stderr)
            return None

    # -- parsing (pure; unit-tested against a real captured payload) -----

    @staticmethod
    def _select_series(payload: dict, prefer_dividend: bool) -> Optional[list]:
        """Pick the price array from the payload's ``series`` list."""
        series = payload.get("series") or []
        plain = None
        dividend = None
        for s in series:
            sid = str(s.get("id", ""))
            label = str(s.get("label", "")).lower()
            prices = s.get("price") or []
            if sid.startswith("fund_with_dividend") or "dywidend" in label:
                dividend = prices
            elif sid.startswith("fund_") or label == "fundusz":
                plain = prices
        # Fallbacks: first series if naming differs
        if plain is None and series:
            plain = series[0].get("price") or []

        if prefer_dividend and dividend:
            return dividend
        return plain

    @classmethod
    def parse_payload(cls, payload: dict, prefer_dividend: bool = False
                      ) -> Optional[pd.DataFrame]:
        """
        Convert an analizy.pl quotation payload into the canonical DataFrame.

        NAV funds publish one value per day, so Open/High/Low/Close are all set
        to the NAV and Volume to 0. Returns None if no usable price points.
        """
        if not isinstance(payload, dict):
            return None
        prices = cls._select_series(payload, prefer_dividend)
        if not prices:
            return None

        records = []
        for point in prices:
            date = point.get("date")
            value = point.get("value")
            if date is None or value is None:
                continue
            records.append((date, value))

        if not records:
            return None

        df = pd.DataFrame(records, columns=["Date", "Close"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"])
        df = df[df["Close"] > 0]
        if df.empty:
            return None

        # NAV-only: replicate Close across OHLC, Volume unknown -> 0
        df["Open"] = df["Close"]
        df["High"] = df["Close"]
        df["Low"] = df["Close"]
        df["Volume"] = 0

        df = df[_COLUMNS].sort_values("Date").reset_index(drop=True)
        return df

    def download_quotes(self, symbol: str) -> Optional[pd.DataFrame]:
        payload = self._fetch_json(symbol)
        if payload is None:
            return None
        return self.parse_payload(payload, prefer_dividend=self.prefer_dividend)
