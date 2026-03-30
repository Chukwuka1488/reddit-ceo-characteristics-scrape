"""Step 0B: Generate CEO name search patterns for Reddit comment matching.

Produces regex patterns and literal search strings for each CEO, used by
Step 3 to filter Reddit comments.
"""

import logging
import re

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from configs.settings import CEO_UNIVERSE_PARQUET, SEARCH_PATTERNS_PARQUET

logger = logging.getLogger(__name__)

# Common company name suffixes to strip for cleaner patterns
COMPANY_SUFFIXES = re.compile(
    r"\s*\b(Inc\.?|Corp\.?|Co\.?|Ltd\.?|PLC|GROUP|HOLDINGS?|ENTERPRISES?|"
    r"INTERNATIONAL|TECHNOLOGIES|TECHNOLOGY|TECHNOLOGI|"
    r"\(THE\)|THE)\s*$",
    re.IGNORECASE,
)


def clean_company_name(name: str) -> str:
    """Strip common suffixes for a shorter, more recognizable company name."""
    cleaned = COMPANY_SUFFIXES.sub("", name).strip()
    # Title-case for readability
    return cleaned.title() if cleaned else name.title()


def build_name_variants(row: pd.Series) -> list[dict]:
    """Generate search pattern variants for one CEO."""
    execid = row["execid"]
    first = row["first_name"]
    last = row["last_name"]
    full = row["full_name"]
    middle = row["middle_name"]
    company_raw = row["company"]
    company_clean = clean_company_name(company_raw)

    variants = []

    def add(pattern_type: str, literal: str):
        # Build a case-insensitive regex that matches word boundaries
        escaped = re.escape(literal)
        regex = rf"\b{escaped}\b"
        variants.append({
            "execid": execid,
            "pattern_type": pattern_type,
            "literal": literal,
            "regex": regex,
        })

    # 1. Full name as-is (e.g., "Warren E. Buffett")
    if isinstance(full, str) and full.strip():
        add("full_name", full.strip())

    # 2. First Last (e.g., "Warren Buffett") — skip if same as full_name
    if isinstance(first, str) and isinstance(last, str):
        first_last = f"{first.strip()} {last.strip()}"
        if first_last != full:
            add("first_last", first_last)

    # 3. Last, First (reversed — sometimes used in formal contexts)
    if isinstance(first, str) and isinstance(last, str):
        add("last_first", f"{last.strip()}, {first.strip()}")

    # 4. "CEO of {Company}" (e.g., "CEO of Berkshire Hathaway")
    add("ceo_of_company", f"CEO of {company_clean}")

    # 5. "{Company} CEO" (e.g., "Berkshire Hathaway CEO")
    add("company_ceo", f"{company_clean} CEO")

    return variants


def build_search_patterns() -> pd.DataFrame:
    """Build search patterns for all CEOs."""
    logger.info("Reading %s", CEO_UNIVERSE_PARQUET)
    ceo_df = pd.read_parquet(CEO_UNIVERSE_PARQUET)
    logger.info("Loaded %d CEOs", len(ceo_df))

    all_variants = []
    for _, row in ceo_df.iterrows():
        all_variants.extend(build_name_variants(row))

    patterns_df = pd.DataFrame(all_variants)
    logger.info(
        "Generated %d patterns for %d CEOs (avg %.1f per CEO)",
        len(patterns_df),
        ceo_df["execid"].nunique(),
        len(patterns_df) / ceo_df["execid"].nunique(),
    )
    return patterns_df


def main() -> None:
    """Build and write search patterns."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    patterns_df = build_search_patterns()

    SEARCH_PATTERNS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(patterns_df)
    pq.write_table(table, SEARCH_PATTERNS_PARQUET)
    logger.info("Wrote %d patterns to %s", len(patterns_df), SEARCH_PATTERNS_PARQUET)

    # Show distribution
    type_counts = patterns_df["pattern_type"].value_counts()
    for ptype, count in type_counts.items():
        logger.info("  %s: %d", ptype, count)


if __name__ == "__main__":
    main()
