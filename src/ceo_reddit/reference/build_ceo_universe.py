"""Step 0A: Build CEO Universe Table from ExecuComp S&P 1500 data.

Filters to S&P 500 CEOs, cleans name suffixes, and deduplicates to one
row per CEO with company and tenure information.
"""

import logging

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from configs.settings import CEO_UNIVERSE_PARQUET, SNP1500_XLS

logger = logging.getLogger(__name__)


def clean_last_name(name: str) -> str:
    """Strip credential suffixes from a last name.

    ExecuComp stores suffixes after commas (e.g., 'Wood, CPA', 'Bourla, D.V.M., Ph.D').
    The lname field is sometimes truncated, leaving partial suffixes. Safest approach:
    split on first comma and keep only the name portion.
    """
    if not isinstance(name, str) or "," not in name:
        return name
    cleaned = name.split(",", 1)[0].strip()
    return cleaned if cleaned else name


def clean_full_name(full_name: str, clean_lname: str, original_lname: str) -> str:
    """Rebuild full name using the cleaned last name."""
    if not isinstance(full_name, str):
        return full_name
    if original_lname != clean_lname and isinstance(original_lname, str):
        # Find where the suffix portion starts in the full name
        idx = full_name.find(", ")
        if idx >= 0:
            return full_name[:idx]
    return full_name


def build_ceo_universe() -> pd.DataFrame:
    """Build the CEO universe table from ExecuComp S&P 1500 data."""
    logger.info("Reading %s", SNP1500_XLS)
    df = pd.read_excel(SNP1500_XLS)
    logger.info("Loaded %d rows, %d columns", len(df), len(df.columns))

    # Filter to S&P 500 CEOs — use ceoann (CEO in that annual record)
    # instead of pceo (current CEO only) to capture historical CEOs
    df = df[(df["spcode"] == "SP") & (df["ceoann"] == "CEO")].copy()
    logger.info("S&P 500 CEO-year rows: %d", len(df))

    # Select and rename relevant columns
    df = df.rename(columns={
        "execid": "execid",
        "ticker": "ticker",
        "coname": "company",
        "exec_fname": "first_name",
        "exec_mname": "middle_name",
        "exec_lname": "last_name",
        "exec_fullname": "full_name",
        "gender": "gender",
        "becameceo": "ceo_start_date",
        "leftofc": "ceo_end_date",
        "year": "year",
    })[["execid", "ticker", "company", "first_name", "middle_name",
        "last_name", "full_name", "gender", "ceo_start_date", "ceo_end_date", "year"]]

    df["execid"] = df["execid"].astype("int64")

    # Clean name suffixes
    df["last_name_clean"] = df["last_name"].apply(clean_last_name)
    df["full_name_clean"] = df.apply(
        lambda r: clean_full_name(r["full_name"], r["last_name_clean"], r["last_name"]),
        axis=1,
    )

    # Deduplicate: one row per CEO-company pair (handles CEOs who moved companies)
    df = df.sort_values("year", ascending=False)
    agg = df.groupby(["execid", "company"], sort=False).agg(
        first_name=("first_name", "first"),
        middle_name=("middle_name", "first"),
        last_name=("last_name_clean", "first"),
        full_name=("full_name_clean", "first"),
        gender=("gender", "first"),
        ceo_start_date=("ceo_start_date", "first"),
        ceo_end_date=("ceo_end_date", "first"),
        ticker=("ticker", "first"),
        first_year_in_data=("year", "min"),
        last_year_in_data=("year", "max"),
    ).reset_index()

    agg = agg.sort_values(["last_name", "first_name", "first_year_in_data"]).reset_index(drop=True)

    logger.info("Deduplicated to %d unique CEOs", len(agg))
    return agg


def main() -> None:
    """Build and write the CEO universe table."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ceo_df = build_ceo_universe()

    CEO_UNIVERSE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(ceo_df)
    pq.write_table(table, CEO_UNIVERSE_PARQUET)
    logger.info("Wrote %d CEOs to %s", len(ceo_df), CEO_UNIVERSE_PARQUET)

    logger.info(
        "Companies: %d | Year range: %d-%d",
        ceo_df["company"].nunique(),
        ceo_df["first_year_in_data"].min(),
        ceo_df["last_year_in_data"].max(),
    )


if __name__ == "__main__":
    main()
