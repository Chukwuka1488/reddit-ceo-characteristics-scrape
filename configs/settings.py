from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Data paths
DATA_DIR = PROJECT_ROOT / "data"
INPUTS_DIR = DATA_DIR / "inputs"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DIR = DATA_DIR / "raw"
FILTERED_DIR = DATA_DIR / "filtered"
FILTERED_CLEAN_PARQUET = DATA_DIR / "filtered_clean" / "ceo_mentions_clean.parquet"
REPORTS_DIR = DATA_DIR / "reports"

# Subreddit metadata (input)
SUBREDDIT_METADATA_ZST = (
    INPUTS_DIR
    / "subreddit_metadata_raw"
    / "reddit"
    / "subreddits"
    / "subreddits_2025-01.zst"
)
SUBREDDITS_DB = PROCESSED_DIR / "subreddits.duckdb"

# DuckDB settings
DUCKDB_MEMORY_LIMIT = "20GB"
DUCKDB_THREADS = 8

# Inputs (uploaded/sourced from outside the pipeline)
SNP1500_XLS = INPUTS_DIR / "snp1500.xls"
LM_DICT_PATH = INPUTS_DIR / "Loughran-McDonald_MasterDictionary_1993-2025.csv"
INTEGRITY_DICT_PATH = INPUTS_DIR / "CEO_Integrity_Dictionary.csv"
NARCISSISM_DICT_PATH = INPUTS_DIR / "CEO_Narcissism_Dictionary.csv"
EARNINGS_TRANSCRIPTS_PARQUET = INPUTS_DIR / "earnings_transcripts.parquet"

# Processed (built by the pipeline)
CEO_UNIVERSE_PARQUET = PROCESSED_DIR / "ceo_universe.parquet"
SEARCH_PATTERNS_PARQUET = PROCESSED_DIR / "search_patterns.parquet"
CANDIDATE_SUBREDDITS_CSV = PROCESSED_DIR / "candidate_subreddits.csv"
CEO_MENTIONS_DICT_SCORED_PARQUET = PROCESSED_DIR / "ceo_mentions_dict_scored.parquet"
CEO_UTTERANCES_PARQUET = PROCESSED_DIR / "ceo_utterances.parquet"
CEO_UTTERANCES_DICT_SCORED_PARQUET = PROCESSED_DIR / "ceo_utterances_dict_scored.parquet"
TRANSCRIPT_EXTRACTION_REPORT = REPORTS_DIR / "transcript_extraction_report.json"
CEO_QUARTER_DICT_SCORES_CSV = REPORTS_DIR / "ceo_quarter_dict_scores.csv"

# Raw subreddit data
RAW_SUBREDDITS_DIR = RAW_DIR / "reddit" / "subreddits25"

# Filtering
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
FILTER_BATCH_SIZE = 10_000

# Processing
BATCH_SIZE = 10_000
