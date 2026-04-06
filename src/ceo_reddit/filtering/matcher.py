"""CEO name pattern matcher using Aho-Corasick for fast multi-pattern matching.

Builds an Aho-Corasick automaton from all search patterns, enabling O(n)
matching against thousands of patterns simultaneously.
"""

import logging

import ahocorasick
import pandas as pd

from configs.settings import CEO_UNIVERSE_PARQUET, SEARCH_PATTERNS_PARQUET

logger = logging.getLogger(__name__)


class CEOMatcher:
    """Matches text against CEO name patterns using Aho-Corasick."""

    def __init__(self) -> None:
        patterns_df = pd.read_parquet(SEARCH_PATTERNS_PARQUET)
        ceo_df = pd.read_parquet(CEO_UNIVERSE_PARQUET)

        # Build lookup: execid → CEO info
        self._ceo_lookup: dict[int, dict] = {}
        for _, row in ceo_df.iterrows():
            self._ceo_lookup[row["execid"]] = {
                "full_name": row["full_name"],
                "company": row["company"],
                "ticker": row["ticker"],
            }

        # Build Aho-Corasick automaton with lowercased patterns
        self._automaton = ahocorasick.Automaton()
        # Map: lowered_literal → list of (execid, pattern_type, original_literal)
        self._pattern_meta: dict[str, list[tuple[int, str, str]]] = {}

        for _, row in patterns_df.iterrows():
            literal = row["literal"]
            key = literal.lower()
            execid = row["execid"]
            pattern_type = row["pattern_type"]

            if key not in self._pattern_meta:
                self._pattern_meta[key] = []
                self._automaton.add_word(key, key)
            self._pattern_meta[key].append((execid, pattern_type, literal))

        self._automaton.make_automaton()

        logger.info(
            "Built Aho-Corasick automaton: %d unique patterns for %d CEOs",
            len(self._pattern_meta),
            len(ceo_df),
        )

    def match(self, text: str) -> list[dict] | None:
        """Match text against all CEO patterns.

        Returns list of match dicts, or None if no match.
        Each dict has: execid, full_name, company, ticker, pattern_type, match_variant.
        """
        text_lower = text.lower()
        results = []
        seen_execids = set()

        for end_idx, key in self._automaton.iter(text_lower):
            start_idx = end_idx - len(key) + 1

            # Word boundary check: character before start and after end
            # must be non-alphanumeric (or string boundary)
            if start_idx > 0 and text_lower[start_idx - 1].isalnum():
                continue
            if end_idx + 1 < len(text_lower) and text_lower[end_idx + 1].isalnum():
                continue

            for execid, pattern_type, literal in self._pattern_meta[key]:
                if execid not in seen_execids:
                    ceo = self._ceo_lookup.get(execid, {})
                    results.append({
                        "execid": execid,
                        "full_name": ceo.get("full_name", ""),
                        "company": ceo.get("company", ""),
                        "ticker": ceo.get("ticker", ""),
                        "pattern_type": pattern_type,
                        "match_variant": literal,
                    })
                    seen_execids.add(execid)

        return results if results else None
