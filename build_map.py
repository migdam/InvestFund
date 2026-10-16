"""
build_map.py
------------

Helper to populate ``symbol_map.json`` semi-automatically by matching fund
*names* across data providers.

Stooq and analizy.pl use different tickers for the same fund, but both expose a
human-readable name. This utility:

1. Collects ``(symbol, name)`` pairs from each side (Stooq's fund list, and an
   analizy.pl symbol list resolved via the verified quotation endpoint).
2. Fuzzy-matches names to propose ``{canonical: {stooq, analizy}}`` entries.
3. Writes a draft ``symbol_map.json`` for you to review.

The matching core (:func:`normalize_name`, :func:`match_score`,
:func:`build_mapping`) is pure and unit-tested offline. Only :func:`fetch_pairs`
touches the network.

Usage::

    # Propose a map from a Stooq run + an analizy symbols file
    python build_map.py --analizy-symbols sample_symbols_analizy.txt \\
        --output symbol_map.draft.json

Review the draft before renaming it to ``symbol_map.json`` — fuzzy matching can
be wrong, so low-confidence matches are flagged.

For informational/educational use only; not investment advice.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Tokens that add no discriminating value when comparing Polish fund names
_STOPWORDS = {
    "fundusz", "funduszy", "inwestycyjny", "inwestycyjnych", "otwarty",
    "subfundusz", "sfio", "fio", "tfi", "the", "fund",
}

# Confidence threshold below which a proposed match is flagged for review
DEFAULT_THRESHOLD = 0.60


@dataclass
class MatchProposal:
    """A proposed cross-provider match for one fund."""
    canonical: str
    stooq: Optional[str]
    analizy: Optional[str]
    score: float
    confident: bool


def normalize_name(name: str) -> str:
    """
    Normalize a fund name for comparison.

    Lowercases, strips Polish diacritics, removes punctuation and common
    non-discriminating words, and collapses whitespace.
    """
    if not name:
        return ""
    # Strip diacritics (ł handled explicitly; NFKD drops most accents)
    name = name.replace("ł", "l").replace("Ł", "L")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    # Replace any non-alphanumeric with spaces
    name = re.sub(r"[^a-z0-9]+", " ", name)
    tokens = [t for t in name.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def match_score(name_a: str, name_b: str) -> float:
    """
    Similarity score in [0, 1] between two fund names after normalization.

    Combines a token-overlap (Jaccard) score with a sequence-ratio score so
    that both word reordering and minor spelling differences are tolerated.
    """
    na, nb = normalize_name(name_a), normalize_name(name_b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    tokens_a, tokens_b = set(na.split()), set(nb.split())
    inter = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(inter) / len(union) if union else 0.0

    # Compare token-sorted strings so word order doesn't penalize the match
    sorted_a = " ".join(sorted(na.split()))
    sorted_b = " ".join(sorted(nb.split()))
    seq = SequenceMatcher(None, sorted_a, sorted_b).ratio()

    # Weight token overlap a bit higher; it's more robust to word order
    return 0.6 * jaccard + 0.4 * seq


def build_mapping(
    stooq_pairs: List[Tuple[str, str]],
    analizy_pairs: List[Tuple[str, str]],
    threshold: float = DEFAULT_THRESHOLD,
) -> List[MatchProposal]:
    """
    Propose cross-provider matches from two lists of ``(symbol, name)`` pairs.

    Greedy best-match: each analizy fund is paired with its highest-scoring
    unused Stooq fund. Stooq funds with no good match still appear (analizy=None)
    so nothing is silently dropped.

    Parameters
    ----------
    stooq_pairs, analizy_pairs : list of (symbol, name)
    threshold : float
        Scores at or above this are marked ``confident``.

    Returns
    -------
    list[MatchProposal]
        Sorted by descending score.
    """
    used_stooq = set()
    proposals: List[MatchProposal] = []

    # Match each analizy fund to the best remaining Stooq fund
    for a_sym, a_name in analizy_pairs:
        best_idx = -1
        best_score = 0.0
        for i, (s_sym, s_name) in enumerate(stooq_pairs):
            if i in used_stooq:
                continue
            score = match_score(a_name, s_name)
            if score > best_score:
                best_score, best_idx = score, i

        if best_idx >= 0 and best_score >= threshold:
            used_stooq.add(best_idx)
            s_sym, s_name = stooq_pairs[best_idx]
            proposals.append(MatchProposal(
                canonical=a_name or s_name,
                stooq=s_sym, analizy=a_sym,
                score=round(best_score, 3), confident=True,
            ))
        else:
            # No confident Stooq counterpart; keep analizy-only entry
            proposals.append(MatchProposal(
                canonical=a_name or a_sym,
                stooq=None, analizy=a_sym,
                score=round(best_score, 3), confident=False,
            ))

    # Surface unmatched Stooq funds too (so the user can map them manually)
    for i, (s_sym, s_name) in enumerate(stooq_pairs):
        if i not in used_stooq:
            proposals.append(MatchProposal(
                canonical=s_name or s_sym,
                stooq=s_sym, analizy=None,
                score=0.0, confident=False,
            ))

    proposals.sort(key=lambda p: p.score, reverse=True)
    return proposals


def proposals_to_map(proposals: List[MatchProposal],
                     confident_only: bool = False) -> Dict[str, Dict[str, str]]:
    """
    Convert proposals into the ``symbol_map.json`` structure.

    Parameters
    ----------
    confident_only : bool
        If True, include only matches that pair both providers confidently.
    """
    mapping: Dict[str, Dict[str, str]] = {}
    for p in proposals:
        if confident_only and not (p.confident and p.stooq and p.analizy):
            continue
        entry = {}
        if p.stooq:
            entry["stooq"] = p.stooq
        if p.analizy:
            entry["analizy"] = p.analizy
        if not entry:
            continue
        # Avoid canonical-key collisions by suffixing when needed
        key = p.canonical or (p.stooq or p.analizy)
        if key in mapping:
            key = f"{key} ({p.analizy or p.stooq})"
        mapping[key] = entry
    return mapping


# ---------------------------------------------------------------------------
# Network layer (exercised by the user; kept thin and separate from the logic)
# ---------------------------------------------------------------------------

def fetch_pairs(analizy_symbols: List[str],
                max_stooq: int = 0,
                use_cache: bool = True
                ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Fetch ``(symbol, name)`` pairs from Stooq and analizy.pl.

    Parameters
    ----------
    analizy_symbols : list[str]
        analizy.pl symbols to resolve (names come from the quotation API).
    max_stooq : int
        Limit the Stooq fund list (0 = all). Stooq's list can be large.
    use_cache : bool
        Reuse the analyzer cache.

    Returns
    -------
    (stooq_pairs, analizy_pairs)
    """
    from analyze_polish_funds import FundAnalyzer
    from providers import AnalizyProvider

    analyzer = FundAnalyzer(use_cache=use_cache)
    stooq_funds = analyzer.get_fund_list()
    if max_stooq > 0:
        stooq_funds = stooq_funds[:max_stooq]
    stooq_pairs = [(f.symbol, f.name) for f in stooq_funds]

    analizy_funds = AnalizyProvider().get_fund_list(analizy_symbols)
    analizy_pairs = [(f.symbol, f.name) for f in analizy_funds]

    return stooq_pairs, analizy_pairs


def _load_symbols(path: str) -> List[str]:
    """Load analizy symbols from a JSON array or one-per-line text file."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        return [str(s).strip() for s in json.loads(text) if str(s).strip()]
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Propose a symbol_map.json by matching fund names across "
                    "Stooq and analizy.pl."
    )
    parser.add_argument(
        "--analizy-symbols", required=True,
        help="File of analizy.pl symbols (one per line or JSON array)."
    )
    parser.add_argument(
        "--max-stooq", type=int, default=0,
        help="Limit Stooq funds considered (0 = all; can be large)."
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Match confidence threshold (default {DEFAULT_THRESHOLD})."
    )
    parser.add_argument(
        "--confident-only", action="store_true",
        help="Write only confident two-provider matches."
    )
    parser.add_argument(
        "--output", default="symbol_map.draft.json",
        help="Where to write the draft map (default: symbol_map.draft.json)."
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Disable the analyzer cache."
    )
    args = parser.parse_args(argv)

    symbols = _load_symbols(args.analizy_symbols)
    if not symbols:
        print("No analizy symbols loaded.", file=sys.stderr)
        return 1

    print(f"Fetching names for {len(symbols)} analizy symbols and the Stooq "
          f"list…", file=sys.stderr)
    stooq_pairs, analizy_pairs = fetch_pairs(
        symbols, max_stooq=args.max_stooq, use_cache=not args.no_cache
    )
    print(f"Stooq funds: {len(stooq_pairs)}, analizy funds: {len(analizy_pairs)}",
          file=sys.stderr)

    proposals = build_mapping(stooq_pairs, analizy_pairs, threshold=args.threshold)
    mapping = proposals_to_map(proposals, confident_only=args.confident_only)

    Path(args.output).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    confident = sum(1 for p in proposals if p.confident and p.stooq and p.analizy)
    print(f"Wrote {len(mapping)} entries to {args.output} "
          f"({confident} confident two-provider matches).", file=sys.stderr)
    print("Review the draft, fix any low-confidence rows, then rename to "
          "symbol_map.json.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
