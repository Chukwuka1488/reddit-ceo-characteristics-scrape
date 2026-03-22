"""Tests for subreddit metadata loading pipeline.

Tests:
- parse_subreddit: JSON parsing and field extraction
- streaming: zstd decompression line streaming
- load_subreddit_metadata: DuckDB native read_json loading
"""

import json
from pathlib import Path

import duckdb
import pytest
import zstandard

from src.ceo_reddit.discovery.load_subreddit_metadata import load_into_duckdb
from src.ceo_reddit.discovery.parse_subreddit import extract_record
from src.ceo_reddit.utils.streaming import stream_zst_lines

# --- Helpers ---


def make_subreddit_json(**overrides) -> str:
    """Create a valid subreddit JSON line for testing."""
    base = {
        "display_name": "TestSub",
        "description": "A test subreddit",
        "public_description": "Test",
        "title": "Test Subreddit",
        "subscribers": 50000,
        "advertiser_category": "Technology",
        "over18": False,
        "created_utc": 1400000000,
        "subreddit_type": "public",
        "lang": "en",
        "_meta": {
            "num_comments": 10000,
            "num_posts": 500,
            "earliest_post_at": 1400000000,
            "earliest_comment_at": 1400100000,
        },
    }
    base.update(overrides)
    return json.dumps(base)


def make_zst_file(tmp_path: Path, lines: list[str]) -> Path:
    """Create a zstd-compressed NDJSON file from lines."""
    raw = "\n".join(lines).encode("utf-8")
    zst_path = tmp_path / "test.zst"
    cctx = zstandard.ZstdCompressor()
    with zst_path.open("wb") as f:
        f.write(cctx.compress(raw))
    return zst_path


# --- parse_subreddit.extract_record ---


class TestExtractRecord:
    def test_valid_record(self) -> None:
        line = make_subreddit_json(display_name="wallstreetbets", subscribers=15000000)
        record = extract_record(line)

        assert record is not None
        assert record[0] == "wallstreetbets"
        assert record[4] == 15000000

    def test_extracts_meta_fields(self) -> None:
        record = extract_record(make_subreddit_json())

        assert record[10] == 10000  # num_comments
        assert record[11] == 500  # num_posts
        assert record[12] == 1400000000  # earliest_post_at
        assert record[13] == 1400100000  # earliest_comment_at

    def test_missing_fields_return_none(self) -> None:
        record = extract_record(json.dumps({"display_name": "minimal"}))

        assert record is not None
        assert record[0] == "minimal"
        assert record[4] is None
        assert record[10] is None

    def test_invalid_json_returns_none(self) -> None:
        assert extract_record("not valid json{{{") is None

    def test_empty_string_returns_none(self) -> None:
        assert extract_record("") is None

    def test_over18_flag(self) -> None:
        record = extract_record(make_subreddit_json(over18=True))
        assert record[6] is True

    def test_returns_14_fields(self) -> None:
        record = extract_record(make_subreddit_json())
        assert len(record) == 14


# --- utils.streaming.stream_zst_lines ---


class TestStreamZstLines:
    def test_yields_all_lines(self, tmp_path: Path) -> None:
        lines = [
            make_subreddit_json(display_name="sub1"),
            make_subreddit_json(display_name="sub2"),
            make_subreddit_json(display_name="sub3"),
        ]
        zst_path = make_zst_file(tmp_path, lines)

        result = list(stream_zst_lines(zst_path))
        assert len(result) == 3

    def test_content_is_correct(self, tmp_path: Path) -> None:
        lines = [make_subreddit_json(display_name="hello")]
        zst_path = make_zst_file(tmp_path, lines)

        result = list(stream_zst_lines(zst_path))
        parsed = json.loads(result[0])
        assert parsed["display_name"] == "hello"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            list(stream_zst_lines(Path("/nonexistent/file.zst")))


# --- load_subreddit_metadata.load_into_duckdb ---


class TestLoadIntoDuckdb:
    def test_loads_records(self, tmp_path: Path) -> None:
        lines = [
            make_subreddit_json(display_name="sub1", subscribers=100),
            make_subreddit_json(display_name="sub2", subscribers=200),
        ]
        zst_path = make_zst_file(tmp_path, lines)
        db_path = tmp_path / "test.duckdb"

        stats = load_into_duckdb(zst_path, db_path)

        assert stats["total_rows"] == 2

        con = duckdb.connect(str(db_path))
        count = con.execute("SELECT count(*) FROM subreddits").fetchone()[0]
        assert count == 2
        con.close()

    def test_correct_column_mapping(self, tmp_path: Path) -> None:
        lines = [
            make_subreddit_json(
                display_name="stocks",
                subscribers=5000000,
                advertiser_category="Finance",
                over18=False,
            ),
        ]
        zst_path = make_zst_file(tmp_path, lines)
        db_path = tmp_path / "test.duckdb"

        load_into_duckdb(zst_path, db_path)

        con = duckdb.connect(str(db_path))
        row = con.execute(
            "SELECT subreddit_name, subscribers, advertiser_category, over18, "
            "num_comments, num_posts FROM subreddits"
        ).fetchone()
        assert row[0] == "stocks"
        assert row[1] == 5000000
        assert row[2] == "Finance"
        assert row[3] is False
        assert row[4] == 10000  # from _meta
        assert row[5] == 500  # from _meta
        con.close()

    def test_idempotent(self, tmp_path: Path) -> None:
        lines = [make_subreddit_json(display_name="sub1")]
        zst_path = make_zst_file(tmp_path, lines)
        db_path = tmp_path / "test.duckdb"

        load_into_duckdb(zst_path, db_path)
        load_into_duckdb(zst_path, db_path)

        con = duckdb.connect(str(db_path))
        count = con.execute("SELECT count(*) FROM subreddits").fetchone()[0]
        assert count == 1
        con.close()

    def test_returns_stats(self, tmp_path: Path) -> None:
        lines = [make_subreddit_json() for _ in range(5)]
        zst_path = make_zst_file(tmp_path, lines)
        db_path = tmp_path / "test.duckdb"

        stats = load_into_duckdb(zst_path, db_path)

        assert stats["total_rows"] == 5
        assert "elapsed_seconds" in stats
        assert "rows_per_second" in stats
