"""Step 3: Stream-filter pipeline for CEO-relevant Reddit comments.

Streams each .zst file, matches against CEO name patterns, and writes
matched records to partitioned Parquet files. Resumable via checkpoint.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from configs.settings import (
    CANDIDATE_SUBREDDITS_CSV,
    CHECKPOINT_DIR,
    FILTER_BATCH_SIZE,
    FILTERED_DIR,
    RAW_SUBREDDITS_DIR,
)
from src.ceo_reddit.filtering.matcher import CEOMatcher
from src.ceo_reddit.utils.streaming import stream_zst_lines

logger = logging.getLogger(__name__)

OUTPUT_SCHEMA = pa.schema([
    ("comment_id", pa.string()),
    ("parent_id", pa.string()),
    ("subreddit", pa.string()),
    ("author", pa.string()),
    ("timestamp", pa.int64()),
    ("year", pa.int32()),
    ("full_text", pa.string()),
    ("post_title", pa.string()),
    ("score", pa.int32()),
    ("is_submission", pa.bool_()),
    ("execid", pa.int64()),
    ("ceo_matched", pa.string()),
    ("company_matched", pa.string()),
    ("ticker_matched", pa.string()),
    ("match_type", pa.string()),
    ("match_variant", pa.string()),
])


def _parse_comment(line: str) -> dict | None:
    """Parse a comment JSON line into a normalized dict."""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    created = obj.get("created_utc")
    if created is None:
        return None
    # created_utc can be string or int
    ts = int(float(created))

    return {
        "comment_id": str(obj.get("id", "")),
        "parent_id": str(obj.get("parent_id", "")),
        "subreddit": str(obj.get("subreddit", "")),
        "author": str(obj.get("author", "")),
        "timestamp": ts,
        "full_text": str(obj.get("body", "")),
        "post_title": "",
        "score": int(obj.get("score", 0) or 0),
        "is_submission": False,
    }


def _parse_submission(line: str) -> dict | None:
    """Parse a submission JSON line into a normalized dict."""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    created = obj.get("created_utc")
    if created is None:
        return None
    ts = int(float(created))

    title = str(obj.get("title", "") or "")
    selftext = str(obj.get("selftext", "") or "")
    # Combine title and selftext for matching; store separately
    full_text = f"{title}\n{selftext}".strip() if selftext else title

    return {
        "comment_id": str(obj.get("id", "")),
        "parent_id": "",
        "subreddit": str(obj.get("subreddit", "")),
        "author": str(obj.get("author", "")),
        "timestamp": ts,
        "full_text": full_text,
        "post_title": title,
        "score": int(obj.get("score", 0) or 0),
        "is_submission": True,
    }


def _ts_to_year(ts: int) -> int:
    """Convert unix timestamp to year."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).year


def _get_completed_files() -> set[str]:
    """Load the set of already-processed .zst filenames from checkpoint."""
    checkpoint_file = CHECKPOINT_DIR / "filter_completed.txt"
    if not checkpoint_file.exists():
        return set()
    return set(checkpoint_file.read_text().strip().splitlines())


def _mark_completed(filename: str) -> None:
    """Append a completed filename to the checkpoint."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_file = CHECKPOINT_DIR / "filter_completed.txt"
    with checkpoint_file.open("a") as f:
        f.write(filename + "\n")


def _next_part_num(out_dir: Path) -> int:
    """Find the next available part number in a partition directory."""
    if not out_dir.exists():
        return 0
    existing = sorted(out_dir.glob("part-*.parquet"))
    if not existing:
        return 0
    # Extract highest part number and add 1
    last = existing[-1].stem  # e.g. "part-0003"
    return int(last.split("-")[1]) + 1


def _flush_batch(batch: list[dict], part_counter: dict[str, int]) -> int:
    """Write a batch of matched records to Parquet, partitioned by year/subreddit.

    Returns number of records written.
    """
    if not batch:
        return 0

    # Group by year/subreddit for partitioned output
    partitions: dict[tuple[int, str], list[dict]] = {}
    for record in batch:
        key = (record["year"], record["subreddit"])
        if key not in partitions:
            partitions[key] = []
        partitions[key].append(record)

    written = 0
    for (year, subreddit), records in partitions.items():
        part_key = f"{year}/{subreddit}"
        out_dir = FILTERED_DIR / f"year={year}" / f"subreddit={subreddit}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Initialize counter from existing files on disk if first write to this partition
        if part_key not in part_counter:
            part_counter[part_key] = _next_part_num(out_dir)

        part_num = part_counter[part_key]
        part_counter[part_key] = part_num + 1

        out_path = out_dir / f"part-{part_num:04d}.parquet"

        table = pa.Table.from_pylist(records, schema=OUTPUT_SCHEMA)
        pq.write_table(table, out_path, compression="zstd")
        written += len(records)

    return written


def process_file(
    zst_path: Path,
    matcher: CEOMatcher,
    is_submission: bool,
) -> dict:
    """Process a single .zst file: stream, match, write.

    Returns stats dict with counts.
    """
    parser = _parse_submission if is_submission else _parse_comment
    filename = zst_path.name
    file_type = "submissions" if is_submission else "comments"

    logger.info("Processing %s (%s)", filename, file_type)
    start = time.time()

    total_lines = 0
    parse_errors = 0
    matched_count = 0
    batch: list[dict] = []
    part_counter: dict[str, int] = {}

    truncated = False
    try:
        for line in stream_zst_lines(zst_path):
            total_lines += 1
            record = parser(line)
            if record is None:
                parse_errors += 1
                continue

            # Match against CEO patterns — search full_text
            text = record["full_text"]
            if not text:
                continue

            matches = matcher.match(text)
            if matches is None:
                continue

            year = _ts_to_year(record["timestamp"])
            # Create one output row per CEO match (a comment can mention multiple CEOs)
            for match_info in matches:
                row = {
                    **record,
                    "year": year,
                    "execid": match_info["execid"],
                    "ceo_matched": match_info["full_name"],
                    "company_matched": match_info["company"],
                    "ticker_matched": match_info["ticker"],
                    "match_type": match_info["pattern_type"],
                    "match_variant": match_info["match_variant"],
                }
                batch.append(row)
                matched_count += 1

            if len(batch) >= FILTER_BATCH_SIZE:
                _flush_batch(batch, part_counter)
                batch.clear()

            if total_lines % 500_000 == 0:
                elapsed = time.time() - start
                rate = total_lines / elapsed
                logger.info(
                    "  %s: %dk lines, %d matches, %.0f lines/sec",
                    filename, total_lines // 1000, matched_count, rate,
                )
    except Exception as e:
        # Partial download — save what we have so far
        logger.warning(
            "  %s: stream error at line %d: %s (saving partial results)",
            filename, total_lines, e,
        )
        truncated = True

    # Final flush
    _flush_batch(batch, part_counter)

    elapsed = time.time() - start
    stats = {
        "file": filename,
        "type": file_type,
        "total_lines": total_lines,
        "parse_errors": parse_errors,
        "matched": matched_count,
        "elapsed_sec": round(elapsed, 1),
        "lines_per_sec": round(total_lines / elapsed) if elapsed > 0 else 0,
        "truncated": truncated,
    }

    status = "PARTIAL" if truncated else "Done"
    logger.info(
        "  %s: %dk lines, %d matches (%.2f%%), %.0f lines/sec, %.1fs",
        status,
        total_lines // 1000,
        matched_count,
        (matched_count / total_lines * 100) if total_lines > 0 else 0,
        stats["lines_per_sec"],
        elapsed,
    )
    return stats


def run_filter() -> None:
    """Run the full filter pipeline across all .zst files."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Verify raw data directory exists
    if not RAW_SUBREDDITS_DIR.exists():
        logger.error("Raw data directory not found: %s", RAW_SUBREDDITS_DIR)
        return

    # Load approved subreddits
    candidates = pd.read_csv(CANDIDATE_SUBREDDITS_CSV)
    approved_subs = set(candidates[candidates["decision"] == "yes"]["subreddit"].tolist())
    logger.info("Approved subreddits: %d", len(approved_subs))

    # Find .zst files for approved subreddits only
    zst_files = sorted(RAW_SUBREDDITS_DIR.glob("*.zst"))
    approved_files = []
    for f in zst_files:
        # Filename format: {subreddit}_{comments|submissions}.zst
        sub_name = f.stem.rsplit("_", 1)[0]
        if sub_name in approved_subs:
            approved_files.append(f)

    # Filter to only valid files (has zstd magic bytes, not a zero-filled placeholder)
    valid_files = []
    for f in approved_files:
        with f.open("rb") as fh:
            header = fh.read(4)
        if header == b"\x28\xb5\x2f\xfd":
            valid_files.append(f)
    logger.info(
        "Approved .zst files: %d, valid (downloaded): %d, incomplete: %d",
        len(approved_files), len(valid_files), len(approved_files) - len(valid_files),
    )

    # Check for already completed files
    completed = _get_completed_files()
    pending = [f for f in valid_files if f.name not in completed]
    if completed:
        logger.info("Resuming: %d already done, %d remaining", len(completed), len(pending))

    if not pending:
        logger.info("All files already processed. Nothing to do.")
        return

    # Initialize matcher (loads patterns into compiled regex)
    logger.info("Loading CEO patterns...")
    matcher = CEOMatcher()

    # Process each file
    FILTERED_DIR.mkdir(parents=True, exist_ok=True)
    all_stats = []

    for zst_path in pending:
        is_sub = "_submissions.zst" in zst_path.name
        try:
            stats = process_file(zst_path, matcher, is_submission=is_sub)
            all_stats.append(stats)
            _mark_completed(zst_path.name)
        except Exception as e:
            logger.error("FAILED %s: %s", zst_path.name, e)
            # Don't mark as completed — will retry on next run
            continue

    # Summary
    total_lines = sum(s["total_lines"] for s in all_stats)
    total_matched = sum(s["matched"] for s in all_stats)
    total_time = sum(s["elapsed_sec"] for s in all_stats)
    logger.info(
        "COMPLETE: %d files, %dk lines, %d matches (%.3f%%), %.0f sec total",
        len(all_stats),
        total_lines // 1000,
        total_matched,
        (total_matched / total_lines * 100) if total_lines > 0 else 0,
        total_time,
    )


if __name__ == "__main__":
    run_filter()
