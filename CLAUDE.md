# CEO Reddit Characteristics Pipeline

## Project

Data engineering pipeline that extracts CEO-relevant Reddit comments from
Academic Torrents Reddit dumps for accounting research on self-presentation
discrepancy.

## Architecture

- **ARCHITECTURE_DECISIONS.md** — All decided and open architecture tradeoffs
- **LAYER1_PIPELINE.md** — Step-by-step execution plan for data collection

## Stack

- Python 3.12, DuckDB, Polars, python-zstandard
- Parquet (zstd) for storage
- Prettier for markdown formatting (auto-runs via PostToolUse hook)
- No cloud — runs on local Ubuntu (32GB RAM, 2TB disk)

## Engineering Principles

### Code Design

- **Single Responsibility:** Each module does one thing. A loader loads. A
  filter filters. Don't mix concerns.
- **Fail Fast:** Validate inputs at boundaries. If the .zst file is missing or
  corrupt, error immediately with a clear message — don't process half the data
  and silently produce bad output.
- **Idempotency:** Running a step twice produces the same result. If data
  already exists in DuckDB, handle it (drop and reload, or skip).
- **No Premature Abstraction:** Don't build a generic framework. Build what this
  pipeline needs. Three similar lines are better than a clever helper nobody can
  read.

### Data Engineering

- **Stream, Don't Load:** Never load an entire file into memory. Stream
  decompress, process in batches, flush to disk. This is non-negotiable with our
  32GB RAM constraint.
- **Checkpoint Everything:** Every step must be resumable. If a process crashes
  at row 5M of 22M, it must resume from row 5M — not restart.
- **Schema on Write:** Define the schema before writing data. No schemaless
  dumps. Every Parquet file has typed columns.
- **Partition for Access Patterns:** Partition data by how it will be queried
  (year, subreddit), not by how it was produced.
- **Validate Before Proceeding:** Each step produces a validation report before
  the next step starts. Bad data does not flow downstream.

### Memory and Resource Management

- **Know Your Budget:** 32GB RAM, 2TB disk. Every processing decision must fit
  within these. Batch sizes, concurrent streams, DuckDB memory limits — all
  derived from actual constraints, not defaults.
- **Clean Up After Yourself:** Temporary files (raw .zst downloads) get deleted
  after processing. Disk is finite.
- **Measure, Don't Guess:** Log memory usage, processing time, and row counts.
  If a step takes unexpectedly long or uses unexpected memory, that's a bug.

### Code Quality

- **Logging Over Print:** Use Python logging, not print statements. Log at INFO
  for progress, WARNING for recoverable issues, ERROR for failures.
- **Config Over Hardcode:** Paths, batch sizes, memory limits — all in
  `configs/settings.py`. No magic strings in pipeline code.
- **Type Hints:** All function signatures have type hints. This is a data
  pipeline — types prevent silent data corruption.
- **Docstrings on Public Functions:** One line stating what it does and what it
  returns. No novels.

### Version Control

- **Atomic Commits:** One logical change per commit. Don't mix "add loader
  script" with "fix gitignore."
- **Never Commit Data:** All data files are in .gitignore. Code is versioned,
  data is not.
- **Document Decisions:** Architecture tradeoffs go in
  ARCHITECTURE_DECISIONS.md, not in code comments.

## Conventions

- Only create directories and files when they are needed for the current step
- All data paths defined in `configs/settings.py`
- Modules live under `src/ceo_reddit/`
- Every pipeline step must be resumable (checkpoint before moving to next step)
- DuckDB for analytical queries, not Postgres

## Data

- Source: Academic Torrents per-subreddit Reddit dumps (zstd NDJSON)
- Subreddit metadata: `data/discovery/subreddit_metadata_raw/`
- Raw .zst downloads go in `data/raw/` (temporary, deleted after filtering)
- Filtered output: `data/filtered/` (Parquet, partitioned by year/subreddit)
- Never commit data files — they are in .gitignore

## Current Phase

Step 1 (Subreddit Discovery) is COMPLETE. 81 subreddits approved from 22M
candidates. Next: build CEO Universe Table (Step 0A), then download approved
subreddits (Step 2). See `docs/LAYER1_PIPELINE.md` "Next Steps" section.
