"""
Load subreddit metadata into DuckDB.

Uses DuckDB's native read_json to read zstd-compressed NDJSON directly —
no Python line-by-line parsing needed. DuckDB handles decompression,
parsing, and column selection internally at C++ speed.

Usage:
    python -m src.ceo_reddit.discovery.load_subreddit_metadata

Idempotent: drops and recreates the table on each run.
"""

import logging
import sys
import time
from pathlib import Path

from src.ceo_reddit.utils.db import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

LOAD_SQL = """
    CREATE OR REPLACE TABLE subreddits AS
    SELECT
        display_name         AS subreddit_name,
        description,
        public_description,
        title,
        subscribers,
        advertiser_category,
        over18,
        created_utc,
        subreddit_type,
        lang,
        _meta.num_comments   AS num_comments,
        _meta.num_posts      AS num_posts,
        _meta.earliest_post_at     AS earliest_post_at,
        _meta.earliest_comment_at  AS earliest_comment_at
    FROM read_json(
        ?,
        format='newline_delimited',
        compression='zstd',
        ignore_errors=true
    )
"""


def load_into_duckdb(
    zst_path: Path,
    db_path: Path,
    memory_limit: str = "20GB",
    threads: int = 8,
) -> dict:
    """Load .zst NDJSON into DuckDB using native read_json."""
    con = get_connection(db_path, memory_limit, threads)

    log.info("Loading: %s", zst_path)
    log.info("DuckDB handles decompression + parsing natively")

    start_time = time.time()
    con.execute(LOAD_SQL, [str(zst_path)])
    elapsed = time.time() - start_time

    count = con.execute("SELECT count(*) FROM subreddits").fetchone()[0]

    stats = {
        "total_rows": count,
        "elapsed_seconds": elapsed,
        "rows_per_second": count / elapsed if elapsed > 0 else 0,
    }

    log.info("=" * 60)
    log.info("DONE")
    log.info("Total rows:  %s", f"{count:,}")
    log.info("Time:        %.1f min", elapsed / 60)
    log.info("Throughput:  %.0f rows/sec", stats["rows_per_second"])
    log.info("=" * 60)

    sample = con.execute(
        "SELECT subreddit_name, subscribers, advertiser_category "
        "FROM subreddits WHERE subscribers > 1000000 "
        "ORDER BY subscribers DESC LIMIT 10"
    ).fetchdf()
    log.info("Top 10 by subscribers:\n%s", sample.to_string())

    con.close()
    return stats


def main() -> None:
    """Entry point — reads paths from configs/settings.py."""
    from configs.settings import (
        DUCKDB_MEMORY_LIMIT,
        DUCKDB_THREADS,
        SUBREDDIT_METADATA_ZST,
        SUBREDDITS_DB,
    )

    if not SUBREDDIT_METADATA_ZST.exists():
        log.error("File not found: %s", SUBREDDIT_METADATA_ZST)
        sys.exit(1)

    load_into_duckdb(
        zst_path=SUBREDDIT_METADATA_ZST,
        db_path=SUBREDDITS_DB,
        memory_limit=DUCKDB_MEMORY_LIMIT,
        threads=DUCKDB_THREADS,
    )


if __name__ == "__main__":
    main()
