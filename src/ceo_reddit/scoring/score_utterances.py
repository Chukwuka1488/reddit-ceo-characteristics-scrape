"""Layer 2 Pass 1 (transcripts): Dictionary-based trait scoring for CEO utterances.

Mirror of ``dictionary_scorer.py`` but for the CEO-side input. Imports the
dictionary loaders, tokenizer, and ``score_text`` from the Reddit scorer so
both sides of the self-presentation discrepancy use IDENTICAL scoring logic
— any divergence here would silently break the construct.

Output: per-utterance scored parquet plus a per-(execid, year, quarter,
section) aggregate CSV ready to join against the Reddit crowd scores.
"""

import logging
import time

import pandas as pd

from configs.settings import (
    CEO_QUARTER_DICT_SCORES_CSV,
    CEO_UTTERANCES_DICT_SCORED_PARQUET,
    CEO_UTTERANCES_PARQUET,
    REPORTS_DIR,
)
from src.ceo_reddit.scoring.dictionary_scorer import (
    _load_integrity_words,
    _load_lm_words,
    _load_narcissism_words,
    _tokenize,
    score_text,
)

logger = logging.getLogger(__name__)


def run() -> None:
    """Score every CEO utterance with all three dictionaries; write outputs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Loading dictionaries...")
    lm_words = _load_lm_words()
    integrity_words = _load_integrity_words()
    narcissism_words = _load_narcissism_words()
    for key, words in lm_words.items():
        logger.info("  %s: %d words", key, len(words))
    for key, words in integrity_words.items():
        logger.info("  %s: %d words", key, len(words))
    logger.info("  narcissism: %d words", len(narcissism_words))

    logger.info("Loading utterances from %s", CEO_UTTERANCES_PARQUET)
    df = pd.read_parquet(CEO_UTTERANCES_PARQUET)
    logger.info("Loaded %d utterances", len(df))

    valid = (df["text"].str.len() >= 10) & df["text"].notna()
    dropped = (~valid).sum()
    df = df[valid].copy()
    if dropped:
        logger.info("Dropped %d utterances shorter than 10 chars", dropped)

    logger.info("Scoring %d utterances...", len(df))
    start = time.time()
    score_rows: list[dict] = []
    for i, text in enumerate(df["text"].values):
        tokens = _tokenize(str(text))
        score_rows.append(score_text(tokens, lm_words, integrity_words, narcissism_words))
        if (i + 1) % 50_000 == 0:
            rate = (i + 1) / (time.time() - start)
            logger.info("  %dk scored, %.0f rows/sec", (i + 1) // 1000, rate)

    elapsed = time.time() - start
    logger.info(
        "Scoring complete: %d rows in %.1fs (%.0f rows/sec)",
        len(df), elapsed, len(df) / elapsed,
    )

    scores_df = pd.DataFrame(score_rows, index=df.index)
    df = pd.concat([df, scores_df], axis=1)

    CEO_UTTERANCES_DICT_SCORED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(
        CEO_UTTERANCES_DICT_SCORED_PARQUET,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )
    logger.info(
        "Saved scored utterances: %s (%.1f MB)",
        CEO_UTTERANCES_DICT_SCORED_PARQUET,
        CEO_UTTERANCES_DICT_SCORED_PARQUET.stat().st_size / 1024 / 1024,
    )

    logger.info("=== Per-utterance score summary ===")
    for col in ("lm_positive", "lm_negative", "lm_uncertainty",
                "lm_net_sentiment", "lm_overconfidence",
                "integrity_all", "integrity_norm", "narcissism", "narcissism_norm"):
        if col in df.columns:
            logger.info(
                "  %s: mean=%.4f, median=%.4f, max=%s",
                col, df[col].mean(), df[col].median(), df[col].max(),
            )

    logger.info("Computing per-(execid, year, quarter, section) aggregates...")
    agg = (
        df.groupby(
            ["execid", "ceo_full_name", "symbol", "company_name", "year", "quarter", "section"],
            sort=False,
        )
        .agg(
            n_utterances=("text", "count"),
            total_words=("word_count", "sum"),
            lm_positive_sum=("lm_positive", "sum"),
            lm_negative_sum=("lm_negative", "sum"),
            lm_uncertainty_sum=("lm_uncertainty", "sum"),
            lm_strong_modal_sum=("lm_strong_modal", "sum"),
            lm_weak_modal_sum=("lm_weak_modal", "sum"),
            lm_net_sentiment_mean=("lm_net_sentiment", "mean"),
            lm_overconfidence_mean=("lm_overconfidence", "mean"),
            integrity_all_sum=("integrity_all", "sum"),
            integrity_norm_mean=("integrity_norm", "mean"),
            narcissism_sum=("narcissism", "sum"),
            narcissism_norm_mean=("narcissism_norm", "mean"),
        )
        .reset_index()
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    agg.to_csv(CEO_QUARTER_DICT_SCORES_CSV, index=False)
    logger.info(
        "Saved CEO-quarter-section aggregates: %s (%d rows)",
        CEO_QUARTER_DICT_SCORES_CSV, len(agg),
    )

    logger.info(
        "Aggregate counts by section: %s",
        agg["section"].value_counts().to_dict(),
    )


if __name__ == "__main__":
    run()
