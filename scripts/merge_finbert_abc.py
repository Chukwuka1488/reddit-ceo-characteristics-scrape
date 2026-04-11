"""Merge CEO-year FinBERT scores with ABC (Compustat) firm metadata.

ABC.csv is a firm-level universe (one row per ticker, fyear = entry year),
so we join on ticker alone and attach gvkey / cusip / conm to each
(execid, ticker, year) finbert row.
"""

from pathlib import Path
import pandas as pd

HOME = Path.home()
FINBERT_CSV = HOME / "Downloads" / "ceo_year_finbert_scores.csv"
ABC_CSV = HOME / "Downloads" / "ABC.csv"
OUT_CSV = HOME / "Downloads" / "ceo_year_finbert_abc_merged.csv"


def load_abc(path: Path) -> pd.DataFrame:
    # ABC has a duplicated 'indfmt' column header; pandas renames the second to 'indfmt.1'.
    df = pd.read_csv(
        path,
        dtype={"gvkey": str, "cusip": str, "tic": str, "conm": str, "fyear": "Int64"},
    )
    # Drop the duplicated indfmt and other columns we don't need for the link.
    keep = ["gvkey", "cusip", "conm", "tic", "fyear", "costat", "curcd"]
    df = df[keep].rename(columns={"fyear": "abc_entry_fyear", "conm": "abc_conm"})
    # Drop rows with null ticker (23 in current file) — unusable as a join key.
    df = df.dropna(subset=["tic"])
    # Enforce 1 row per ticker. If duplicates exist, keep the earliest entry year.
    df = df.sort_values(["tic", "abc_entry_fyear"]).drop_duplicates("tic", keep="first")
    return df


def load_finbert(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    assert not df.duplicated(["execid", "ticker_matched", "year"]).any()
    return df


def merge(finbert: pd.DataFrame, abc: pd.DataFrame) -> pd.DataFrame:
    merged = finbert.merge(
        abc,
        how="left",
        left_on="ticker_matched",
        right_on="tic",
        validate="many_to_one",
    )
    merged = merged.drop(columns=["tic"])
    return merged


def report(finbert: pd.DataFrame, abc: pd.DataFrame, merged: pd.DataFrame) -> None:
    matched = merged["gvkey"].notna().sum()
    total = len(merged)
    print(f"FinBERT rows:        {len(finbert):,}")
    print(f"ABC firms (unique):  {len(abc):,}")
    print(f"Merged rows:         {total:,}")
    print(f"Matched to gvkey:    {matched:,} ({matched/total:.1%})")
    print(f"Unmatched rows:      {total - matched:,}")
    unmatched_tics = merged.loc[merged["gvkey"].isna(), "ticker_matched"].unique()
    if len(unmatched_tics):
        print(f"Unmatched tickers:   {sorted(unmatched_tics)[:20]}")


def main() -> None:
    abc = load_abc(ABC_CSV)
    finbert = load_finbert(FINBERT_CSV)
    merged = merge(finbert, abc)
    report(finbert, abc, merged)
    merged.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
