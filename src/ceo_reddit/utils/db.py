"""DuckDB connection and table utilities."""

import logging
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)


def get_connection(
    db_path: Path,
    memory_limit: str = "20GB",
    threads: int = 8,
) -> duckdb.DuckDBPyConnection:
    """Create a configured DuckDB connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET threads = {threads}")
    log.info("Connected to DuckDB: %s (memory=%s, threads=%d)", db_path, memory_limit, threads)
    return con
