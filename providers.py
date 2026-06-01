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

import json
import sys
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests

# Reuse the project's constants/headers where helpful
from analyze_polish_funds import FundAnalyzer, FundInfo

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

    @staticmethod
    def parse_label(payload: dict) -> str:
        """Extract the human-readable fund name from a quotation payload."""
        if isinstance(payload, dict):
            return str(payload.get("label") or "")
        return ""

    def get_fund_list(self, symbols) -> "list[FundInfo]":
        """
        Build a fund list for an explicit set of analizy.pl symbols.

        analizy.pl has no verified bulk "list all funds" endpoint, so discovery
        is driven by a caller-supplied symbol list: each symbol is fetched via
        the verified quotation endpoint and its real name (``label``) is read
        from the payload. Symbols that fail to fetch are skipped with a warning.

        Parameters
        ----------
        symbols : Iterable[str]
            analizy.pl fund symbols (e.g. ``["ING35", ...]``).

        Returns
        -------
        list[FundInfo]
            One entry per resolvable symbol, with the real fund name.
        """
        funds = []
        for symbol in symbols:
            payload = self._fetch_json(symbol)
            if payload is None:
                continue
            name = self.parse_label(payload) or symbol
            funds.append(FundInfo(symbol=symbol, name=name))
        return funds


class SymbolMapper:
    """
    Translate a fund's symbol between providers.

    Stooq and analizy.pl use different tickers for the same fund (e.g. a Stooq
    ``*.N`` code vs an analizy.pl code like ``ING35``). A mapping lets you keep
    one holdings/watch file and resolve the right symbol per provider.

    The mapping JSON maps a canonical key to per-provider symbols::

        {
          "GS Globalny Spolek Dyw": {"stooq": "1234.N", "analizy": "ING35"},
          "...": {"analizy": "ABC12"}
        }

    Resolution is also reversible: given any known provider symbol you can look
    up the symbol for another provider.
    """

    def __init__(self, mapping: Optional[Dict[str, Dict[str, str]]] = None):
        self.mapping: Dict[str, Dict[str, str]] = mapping or {}

    @classmethod
    def from_file(cls, path: str) -> "SymbolMapper":
        """Load a mapping from a JSON file (see class docstring for format)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Symbol map must be a JSON object")
        return cls(data)

    def resolve(self, symbol: str, provider: str) -> str:
        """
        Return the symbol to use for ``provider``.

        Accepts either a canonical key or any provider's symbol for the same
        fund. Falls back to the input symbol unchanged if no mapping is found
        (so unmapped symbols still work).
        """
        # Direct canonical-key hit
        entry = self.mapping.get(symbol)
        if entry and provider in entry:
            return entry[provider]

        # Reverse lookup: find the entry containing this symbol under any provider
        for providers_map in self.mapping.values():
            if symbol in providers_map.values() and provider in providers_map:
                return providers_map[provider]

        # Unmapped: use as-is
        return symbol
