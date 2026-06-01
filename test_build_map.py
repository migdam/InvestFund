#!/usr/bin/env python3
"""
Tests for build_map.py — the offline name-matching core that proposes a
symbol_map.json. No network: fetch_pairs is not exercised here.
"""

import sys

from build_map import (
    normalize_name,
    match_score,
    build_mapping,
    proposals_to_map,
    MatchProposal,
)


def run() -> int:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name} {detail}")
            failures += 1

    # --- normalize_name ----------------------------------------------------
    check("strips diacritics",
          normalize_name("Globalny Spółek Dywidendowych")
          == "globalny spolek dywidendowych")
    check("drops stopwords and punctuation",
          normalize_name("Fundusz Inwestycyjny Akcji (FIO)") == "akcji")
    check("empty -> empty", normalize_name("") == "")
    check("collapses whitespace and case",
          normalize_name("  PKO   AKCJI  ") == "pko akcji")

    # --- match_score -------------------------------------------------------
    check("identical names score 1.0",
          match_score("PKO Akcji", "PKO Akcji") == 1.0)
    check("word reorder still high",
          match_score("Akcji Globalny", "Globalny Akcji") > 0.9)
    check("unrelated names score low",
          match_score("PKO Akcji Polskie", "Investor Obligacji USA") < 0.3)
    check("empty vs name -> 0", match_score("", "PKO Akcji") == 0.0)
    check("score within [0,1]",
          0.0 <= match_score("GS Globalny Spolek", "Goldman Globalny Spolki") <= 1.0)

    # --- build_mapping -----------------------------------------------------
    stooq = [
        ("1234.N", "Goldman Sachs Globalny Spolek Dywidendowych"),
        ("5678.N", "PKO Obligacji Skarbowych"),
        ("9999.N", "Some Unrelated Equity Fund"),
    ]
    analizy = [
        ("ING35", "Goldman Sachs Globalny Spółek Dywidendowych"),  # ~ 1234.N
        ("PKO11", "PKO Obligacji Skarbowych"),                     # ~ 5678.N
        ("XYZ01", "Totally Different Bond Fund"),                  # no match
    ]
    proposals = build_mapping(stooq, analizy, threshold=0.6)

    by_analizy = {p.analizy: p for p in proposals if p.analizy}
    check("ING35 matched to 1234.N",
          by_analizy["ING35"].stooq == "1234.N" and by_analizy["ING35"].confident)
    check("PKO11 matched to 5678.N",
          by_analizy["PKO11"].stooq == "5678.N" and by_analizy["PKO11"].confident)
    check("XYZ01 left unmatched (analizy-only)",
          by_analizy["XYZ01"].stooq is None and not by_analizy["XYZ01"].confident)

    # Unmatched Stooq fund (9999.N) should still surface
    stooq_only = [p for p in proposals if p.stooq == "9999.N"]
    check("unmatched Stooq fund surfaced",
          len(stooq_only) == 1 and stooq_only[0].analizy is None)

    # Greedy: a Stooq fund isn't reused for two analizy funds
    used = [p.stooq for p in proposals if p.stooq]
    check("no Stooq symbol reused", len(used) == len(set(used)))

    # --- proposals_to_map --------------------------------------------------
    full = proposals_to_map(proposals)
    check("map includes confident pair with both providers",
          any(e.get("stooq") == "1234.N" and e.get("analizy") == "ING35"
              for e in full.values()))

    confident = proposals_to_map(proposals, confident_only=True)
    check("confident_only keeps only two-provider matches",
          all("stooq" in e and "analizy" in e for e in confident.values())
          and len(confident) == 2)

    # --- collision handling ------------------------------------------------
    dup = [
        MatchProposal("Same Name", "1.N", "A1", 0.9, True),
        MatchProposal("Same Name", "2.N", "A2", 0.9, True),
    ]
    dmap = proposals_to_map(dup)
    check("canonical-key collision avoided", len(dmap) == 2)

    # --- threshold behavior ------------------------------------------------
    loose = build_mapping(stooq, analizy, threshold=0.99)
    confident_loose = [p for p in loose if p.confident]
    check("high threshold reduces confident matches",
          len(confident_loose) <= 2)

    print()
    if failures:
        print(f"BUILD-MAP TESTS: {failures} failed")
        return 1
    print("BUILD-MAP TESTS: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
