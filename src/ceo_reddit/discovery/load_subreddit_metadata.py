"""
Load subreddit metadata into DuckDB.

Streams the Academic Torrents subreddit metadata .zst file, parses each
NDJSON line, and batch-inserts into a DuckDB table. Designed for the
22M-record subreddits_2025-01.zst file.

Usage:
    python -m src.ceo_reddit.discovery.load_subreddit_metadata

Idempotent: drops and recreates the table on each run.
"""

import logging
import sys
import time
from pathlib import Path

from src.ceo_reddit.discovery.parse_subreddit import extract_record
from src.ceo_reddit.utils.db import get_connection
from src.ceo_reddit.utils.streaming import stream_zst_lines

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS subreddits (
        subreddit_name       VARCHAR,
        description          VARCHAR,
        public_description   VARCHAR,
        title                VARCHAR,
        subscribers          BIGINT,
        advertiser_category  VARCHAR,
        over18               BOOLEAN,
        created_utc          BIGINT,
        subreddit_type       VARCHAR,
        lang                 VARCHAR,
        num_comments         BIGINT,
        num_posts            BIGINT,
        earliest_post_at     BIGINT,
        earliest_comment_at  BIGINT
    )
"""

INSERT_SQL = """
    INSERT INTO subreddits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def load_into_duckdb(
    zst_path: Path,
    db_path: Path,
    batch_size: int = 10_000,
    memory_limit: str = "20GB",
    threads: int = 8,
) -> dict:
    """
    Stream .zst into DuckDB in batches.

    Args:
        zst_path: Path to the zstd-compressed NDJSON file.
        db_path: Path to the DuckDB database file.
        batch_size: Rows per batch insert.
        memory_limit: DuckDB memory limit.
        threads: DuckDB thread count.

    Returns:
        Dict with total_rows, skipped, elapsed_seconds, rows_per_second.
    """
    con = get_connection(db_path, memory_limit, threads)

    con.execute("DROP TABLE IF EXISTS subreddits")
    con.execute(CREATE_TABLE_SQL)

    log.info("Streaming: %s", zst_path)
    log.info("Batch size: %s", f"{batch_size:,}")

    start_time = time.time()
    total_rows = 0
    skipped = 0
    batch: list[tuple] = []

    for line in stream_zst_lines(zst_path):
        record = extract_record(line)
        if record is None:
            skipped += 1
            continue

        batch.append(record)

        if len(batch) >= batch_size:
            con.executemany(INSERT_SQL, batch)
            total_rows += len(batch)
            batch.clear()

            elapsed = time.time() - start_time
            rate = total_rows / elapsed if elapsed > 0 else 0
            log.info(
                "rows=%s | skipped=%s | rate=%.0f/s | elapsed=%.1fs",
                f"{total_rows:,}",
                f"{skipped:,}",
                rate,
                elapsed,
            )

    if batch:
        con.executemany(INSERT_SQL, batch)
        total_rows += len(batch)

    elapsed = time.time() - start_time
    stats = {
        "total_rows": total_rows,
        "skipped": skipped,
        "elapsed_seconds": elapsed,
        "rows_per_second": total_rows / elapsed if elapsed > 0 else 0,
    }

    log.info("=" * 60)
    log.info("DONE")
    log.info("Total rows:  %s", f"{stats['total_rows']:,}")
    log.info("Skipped:     %s", f"{stats['skipped']:,}")
    log.info("Time:        %.1f min", elapsed / 60)
    log.info("Throughput:  %.0f rows/sec", stats["rows_per_second"])

    count = con.execute("SELECT count(*) FROM subreddits").fetchone()[0]
    if count != total_rows:
        log.error("MISMATCH: inserted %s but table has %s", total_rows, count)
    else:
        log.info("Validated:   %s rows", f"{count:,}")
    log.info("=" * 60)

    con.close()
    return stats


def main() -> None:
    """Entry point — reads paths from configs/settings.py."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from configs.settings import (
        BATCH_SIZE,
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
        batch_size=BATCH_SIZE,
        memory_limit=DUCKDB_MEMORY_LIMIT,
        threads=DUCKDB_THREADS,
    )


if __name__ == "__main__":
    main()
