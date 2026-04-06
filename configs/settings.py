from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Data paths
DATA_DIR = PROJECT_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"
DISCOVERY_DIR = DATA_DIR / "discovery"
RAW_DIR = DATA_DIR / "raw"
FILTERED_DIR = DATA_DIR / "filtered"
FILTERED_CLEAN_PARQUET = DATA_DIR / "filtered_clean" / "ceo_mentions_clean.parquet"
REPORTS_DIR = DATA_DIR / "reports"

# Subreddit metadata
SUBREDDIT_METADATA_ZST = (
    DISCOVERY_DIR
    / "subreddit_metadata_raw"
    / "reddit"
    / "subreddits"
    / "subreddits_2025-01.zst"
)
SUBREDDITS_DB = DISCOVERY_DIR / "subreddits.duckdb"

# DuckDB settings
DUCKDB_MEMORY_LIMIT = "20GB"
DUCKDB_THREADS = 8

# Reference data
SNP1500_XLS = DISCOVERY_DIR / "snp1500.xls"
CEO_UNIVERSE_PARQUET = REFERENCE_DIR / "ceo_universe.parquet"
SEARCH_PATTERNS_PARQUET = REFERENCE_DIR / "search_patterns.parquet"

# Raw subreddit data
RAW_SUBREDDITS_DIR = RAW_DIR / "reddit" / "subreddits25"

# Filtering
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
FILTER_BATCH_SIZE = 10_000

# Processing
BATCH_SIZE = 10_000
