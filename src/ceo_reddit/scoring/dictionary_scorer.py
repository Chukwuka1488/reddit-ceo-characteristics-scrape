"""Layer 2 Pass 1: Dictionary-based trait scoring for Reddit CEO mentions.

Scores each comment using three dictionaries:
- Loughran-McDonald (overconfidence): positive/negative/uncertainty word counts
- Hennig Integrity: integrity-related word counts by category
- Narcissism: narcissism-related word counts

Produces per-comment scores and per-CEO-year aggregates.
"""

import logging
import re
import time
from pathlib import Path

import pandas as pd

from configs.settings import (
    DISCOVERY_DIR,
    FILTERED_CLEAN_PARQUET,
    REFERENCE_DIR,
    REPORTS_DIR,
)

logger = logging.getLogger(__name__)

# Dictionary file paths
LM_DICT_PATH = REFERENCE_DIR / "Loughran-McDonald_MasterDictionary_1993-2025.csv"
INTEGRITY_DICT_PATH = DISCOVERY_DIR / "CEO_Integrity_Dictionary.csv"
NARCISSISM_DICT_PATH = DISCOVERY_DIR / "CEO_Narcissism_Dictionary.csv"

# Output paths
SCORED_OUTPUT = REFERENCE_DIR / "ceo_mentions_dict_scored.parquet"


def _load_lm_words() -> dict[str, set[str]]:
    """Load Loughran-McDonald sentiment word sets."""
    df = pd.read_csv(LM_DICT_PATH)
    return {
        "lm_positive": set(df[df["Positive"] > 0]["Word"].str.lower()),
        "lm_negative": set(df[df["Negative"] > 0]["Word"].str.lower()),
        "lm_uncertainty": set(df[df["Uncertainty"] > 0]["Word"].str.lower()),
        "lm_strong_modal": set(df[df["Strong_Modal"] > 0]["Word"].str.lower()),
        "lm_weak_modal": set(df[df["Weak_Modal"] > 0]["Word"].str.lower()),
    }


def _load_integrity_words() -> dict[str, set[str]]:
    """Load Hennig integrity dictionary by category."""
    df = pd.read_csv(INTEGRITY_DICT_PATH)
    categories = df["Integrity_Category"].unique()
    word_sets = {}
    for cat in categories:
        key = f"integrity_{cat.lower()}"
        word_sets[key] = set(df[df["Integrity_Category"] == cat]["Word"].str.lower())
    # Also a combined set
    word_sets["integrity_all"] = set(df["Word"].str.lower())
    return word_sets


def _load_narcissism_words() -> set[str]:
    """Load narcissism dictionary words."""
    df = pd.read_csv(NARCISSISM_DICT_PATH)
    return set(df["Word"].str.lower())


# Pre-compile tokenizer: split on non-alpha characters
_TOKENIZE = re.compile(r"[a-z]+")


def _tokenize(text: str) -> list[str]:
    """Tokenize text to lowercase words."""
    return _TOKENIZE.findall(text.lower())


def score_text(
    tokens: list[str],
    lm_words: dict[str, set[str]],
    integrity_words: dict[str, set[str]],
    narcissism_words: set[str],
) -> dict[str, int | float]:
    """Score a tokenized comment against all dictionaries.

    Returns dict of raw counts and normalized scores.
    """
    word_count = len(tokens)
    if word_count == 0:
        return {
            "word_count": 0,
            "lm_positive": 0, "lm_negative": 0, "lm_uncertainty": 0,
            "lm_strong_modal": 0, "lm_weak_modal": 0,
            "lm_net_sentiment": 0.0, "lm_overconfidence": 0.0,
            "integrity_all": 0, "narcissism": 0,
            "integrity_norm": 0.0, "narcissism_norm": 0.0,
        }

    token_set_counts: dict[str, int] = {}

    # Count LM words
    for key, word_set in lm_words.items():
        token_set_counts[key] = sum(1 for t in tokens if t in word_set)

    # Count integrity words
    for key, word_set in integrity_words.items():
        token_set_counts[key] = sum(1 for t in tokens if t in word_set)

    # Count narcissism words
    token_set_counts["narcissism"] = sum(1 for t in tokens if t in narcissism_words)

    # Derived scores (normalized by word count)
    pos = token_set_counts["lm_positive"]
    neg = token_set_counts["lm_negative"]
    strong = token_set_counts["lm_strong_modal"]
    unc = token_set_counts["lm_uncertainty"]

    # Net sentiment: (positive - negative) / word_count
    net_sentiment = (pos - neg) / word_count

    # Overconfidence proxy: (positive + strong_modal - uncertainty) / word_count
    # High positive tone + strong modals - uncertainty = overconfident language
    overconfidence = (pos + strong - unc) / word_count

    scores = {
        "word_count": word_count,
        **token_set_counts,
        "lm_net_sentiment": round(net_sentiment, 6),
        "lm_overconfidence": round(overconfidence, 6),
        "integrity_norm": round(token_set_counts["integrity_all"] / word_count, 6),
        "narcissism_norm": round(token_set_counts["narcissism"] / word_count, 6),
    }
    return scores


def run_dictionary_scoring() -> None:
    """Score all clean CEO mentions with dictionary methods."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load dictionaries
    logger.info("Loading dictionaries...")
    lm_words = _load_lm_words()
    integrity_words = _load_integrity_words()
    narcissism_words = _load_narcissism_words()

    for key, words in lm_words.items():
        logger.info("  %s: %d words", key, len(words))
    for key, words in integrity_words.items():
        logger.info("  %s: %d words", key, len(words))
    logger.info("  narcissism: %d words", len(narcissism_words))

    # Load clean mentions
    logger.info("Loading clean mentions from %s", FILTERED_CLEAN_PARQUET)
    df = pd.read_parquet(FILTERED_CLEAN_PARQUET)
    logger.info("Loaded %d rows", len(df))

    # Exclude deleted/very short text
    valid_mask = (
        ~df["full_text"].isin(["[deleted]", "[removed]", ""])
        & (df["full_text"].str.len() >= 10)
        & ~df["author"].isin(["[deleted]", "[removed]"])
    )
    df = df[valid_mask].copy()
    logger.info("After quality filter: %d rows", len(df))

    # Score each comment
    logger.info("Scoring %d comments...", len(df))
    start = time.time()

    score_cols = []
    for i, text in enumerate(df["full_text"].values):
        tokens = _tokenize(str(text))
        scores = score_text(tokens, lm_words, integrity_words, narcissism_words)
        score_cols.append(scores)

        if (i + 1) % 100_000 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            logger.info("  %dk scored, %.0f rows/sec", (i + 1) // 1000, rate)

    elapsed = time.time() - start
    logger.info("Scoring complete: %d rows in %.1fs (%.0f rows/sec)",
                len(df), elapsed, len(df) / elapsed)

    # Merge scores into dataframe
    scores_df = pd.DataFrame(score_cols)
    for col in scores_df.columns:
        df[col] = scores_df[col].values

    # Save scored output
    SCORED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SCORED_OUTPUT, engine="fastparquet", compression="zstd", index=False)
    logger.info("Saved scored output: %s (%.1f MB)",
                SCORED_OUTPUT, SCORED_OUTPUT.stat().st_size / 1024 / 1024)

    # Print summary stats
    logger.info("=== SCORING SUMMARY ===")
    logger.info("Rows scored: %d", len(df))
    for col in ["lm_positive", "lm_negative", "lm_uncertainty",
                "lm_net_sentiment", "lm_overconfidence",
                "integrity_all", "narcissism"]:
        if col in df.columns:
            logger.info("  %s: mean=%.4f, median=%.4f, max=%s",
                        col, df[col].mean(), df[col].median(), df[col].max())

    # CEO-year aggregates
    logger.info("Computing CEO-year aggregates...")
    agg_cols = {
        "comment_id": "count",
        "word_count": "sum",
        "lm_positive": "sum",
        "lm_negative": "sum",
        "lm_uncertainty": "sum",
        "lm_strong_modal": "sum",
        "lm_net_sentiment": "mean",
        "lm_overconfidence": "mean",
        "integrity_all": "sum",
        "integrity_norm": "mean",
        "narcissism": "sum",
        "narcissism_norm": "mean",
    }
    ceo_year = (
        df.groupby(["execid", "ceo_matched", "company_matched", "ticker_matched", "year"])
        .agg(**{f"{k}_{'count' if v == 'count' else v}": (k, v) for k, v in agg_cols.items()})
        .reset_index()
    )
    ceo_year.columns = [c.replace("_count_count", "_mention_count")
                         .replace("_sum_sum", "_sum")
                         .replace("_mean_mean", "_mean")
                         for c in ceo_year.columns]

    agg_path = REPORTS_DIR / "ceo_year_dict_scores.csv"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ceo_year.to_csv(agg_path, index=False)
    logger.info("Saved CEO-year aggregates: %s (%d rows)", agg_path, len(ceo_year))


if __name__ == "__main__":
    run_dictionary_scoring()
