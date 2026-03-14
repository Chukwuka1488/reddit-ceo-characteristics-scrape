# Architecture Decisions: Reddit CEO Characteristics Pipeline

## Constraints

| Resource   | Value                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------- |
| RAM        | 32GB                                                                                        |
| Disk       | 2TB                                                                                         |
| OS         | Ubuntu                                                                                      |
| Data Source | Academic Torrents Reddit per-subreddit dumps (top 40K subs, zstd NDJSON) + Arctic Shift API |
| Budget     | Zero cost (open-source stack only)                                                          |
| Purpose    | Accounting journal publication + future research extensions                                  |
| GPU        | Google Colab Pro (Layer 2 scoring)                                                          |

## Stack

| Tool             | Role                                                       |
| ---------------- | ---------------------------------------------------------- |
| DuckDB           | Out-of-core analytical queries, handles data exceeding RAM |
| Polars           | Lazy/streaming DataFrames                                  |
| python-zstandard | Stream-decompress .zst without loading into memory         |
| Parquet (zstd)   | Storage format, 5-10x smaller than raw JSON                |
| FinBERT          | Trait scoring (Layer 2, runs on Colab GPU)                 |

---

## Decision 1: Data Acquisition Strategy — DECIDED

Three-pass: metadata index → Arctic Shift relevance scoring → selective torrent
download. Monthly dump ruled out (doesn't fit on disk).

---

## Decision 2: CEO Universe Dataset — DECIDED

ExecuComp via WRDS. S&P 500, 2005-2025. Current + historical CEOs. Separate
deliverable. Name variants: full names + "CEO" + company combos.

---

## Decision 3: Pipeline Architecture — DECIDED (two-layer)

- **Layer 1 (local):** Collect all CEO-relevant Reddit comments 2005-2025.
  Trait-agnostic. Full text stored. Runs once.
- **Layer 2 (Colab GPU):** Scoring passes. First: overconfidence + integrity.
  Future: additional traits. Reads Layer 1 Parquet. Repeatable.

---

## Layer 1 Pipeline: Collection and Filtering

**Runs on:** Local Ubuntu machine (32GB RAM, 2TB disk)
**Output:** Parquet files of all CEO-relevant Reddit comments 2005-2025

### Step 0: Prerequisites

**0A — CEO Universe Table**

- Source: ExecuComp via WRDS
- Output: `data/reference/ceo_universe.parquet`
- Schema: company, ticker, ceo_legal_name, ceo_common_name,
  ceo_name_variants[], sp500_entry_date, sp500_exit_date, ceo_start_date,
  ceo_end_date
- ~1000+ CEO-company-year tuples

**0B — CEO Name Search Patterns**

- Input: CEO Universe Table
- Output: `data/reference/search_patterns.parquet`
- Variants per CEO: full name, reversed name, "CEO of {company}",
  "{company} CEO", company + "CEO"

### Step 1: Subreddit Discovery

**1A — Torrent Metadata Index**

- Download torrent file only (not content). Extract 40K subreddit names + file
  sizes.
- Output: `data/discovery/subreddit_index.parquet`
- Time: minutes

**1B — Arctic Shift Relevance Scoring**

- Query CEO name variants against Arctic Shift API for mention counts per
  subreddit.
- Rate limiting: 1 req/sec with backoff. Checkpoint per CEO.
- Output: `data/discovery/subreddit_relevance.parquet`
- Time: 1-3 hours

**1C — Subreddit Selection**

- Rank subreddits by CEO mention density. Cross-reference with file sizes.
- **Human decision point:** review ranked list, select subreddits.
- Output: `data/discovery/selected_subreddits.csv`
- Expected: 20-50 subreddits, 50-200GB download

### Step 2: Data Download

**2A — Selective Torrent Download**

- Torrent client downloads only selected subreddit .zst files.
- Output: `data/raw/{subreddit}_comments.zst`,
  `data/raw/{subreddit}_submissions.zst`
- Storage: 50-200GB (temporary)
- Time: hours to days

**2B — Download Verification**

- Verify checksums, log sizes, confirm completeness.
- Output: `data/raw/download_manifest.csv`

### Step 3: Stream, Filter, Store

**3A — Stream-Filter Pipeline (per subreddit)**

1. Stream decompress .zst (python-zstandard, line by line)
2. Parse JSON line → dict
3. Match against CEO name patterns (compiled regex)
4. If match → add to batch buffer
5. Every 10K records → flush to Parquet
6. Checkpoint after each .zst file

**Memory:** < 500MB per subreddit. Can run 4-8 concurrent streams under 4GB.

**3B — Output Schema**

```
comment_id        (string)  — Reddit comment/post ID
parent_id         (string)  — Parent comment/post ID
subreddit         (string)  — Source subreddit
author            (string)  — Reddit username
timestamp         (int64)   — Unix timestamp
datetime          (date)    — Derived, for partitioning
full_text         (string)  — Complete comment/post text
post_title        (string)  — Parent post title
score             (int32)   — Reddit upvote score
is_submission     (bool)    — Post vs comment
ceo_matched       (string)  — CEO name matched
company_matched   (string)  — Company matched
match_type        (string)  — full_name | ceo_title | company_ceo
match_variant     (string)  — Exact pattern that triggered match
```

**3C — Partitioning:** `data/filtered/year={YYYY}/subreddit={name}/part-{N}.parquet`
(zstd compressed, estimated 2-10GB total)

**3D — Post-Filter Cleanup:** Delete raw .zst files after verifying Parquet
output. Human confirmation required. Reclaims 50-200GB.

### Step 4: Validation

**4A — Coverage Report:** DuckDB queries → comments per CEO per year, per
subreddit per year, match type distribution. Flag CEOs < 20 mentions/year.

**4B — False Positive Sampling:** Random 200-500 matched comments for manual
review. If false positive rate > 10%, tighten matching and re-run Step 3.

**4C — Deduplication:** Check for duplicate comment_ids across subreddits.
Deduplicate, keep first.

### Checkpointing

| Step   | Resume behavior                                         |
| ------ | ------------------------------------------------------- |
| 0A, 0B | Re-run (minutes)                                        |
| 1A     | Re-run (minutes)                                        |
| 1B     | Resume from last completed CEO                          |
| 1C     | Human decision, no crash risk                           |
| 2A     | Torrent client auto-resumes                             |
| 3A     | Resume from last completed .zst file                    |
| 4A-4C  | Re-run against Parquet (fast DuckDB queries)            |

### Resource Usage

| Resource         | Step 2 (download) | Step 3 (filter) | Final output |
| ---------------- | ----------------- | --------------- | ------------ |
| Disk             | 50-200GB temp     | < 500MB working | 2-10GB       |
| RAM              | Minimal           | < 500MB         | —            |
| Time             | Hours-days        | 1-4 hours       | —            |
| Disk after cleanup | —               | —               | 2-10GB       |

### Directory Structure

```
data/
├── reference/
│   ├── ceo_universe.parquet
│   └── search_patterns.parquet
├── discovery/
│   ├── subreddit_index.parquet
│   ├── subreddit_relevance.parquet
│   └── selected_subreddits.csv
├── raw/                              ← deleted after Step 3D
│   ├── {subreddit}_comments.zst
│   └── download_manifest.csv
├── filtered/
│   └── year={YYYY}/
│       └── subreddit={name}/
│           └── part-{N}.parquet
└── reports/
    ├── layer1_coverage.csv
    └── false_positive_audit.csv
```

---

## Decision 4: Temporal Alignment — OPEN

Layer 1 stores all comments with timestamps. Windowing (90-day pre-earnings)
happens at analysis time by joining against an earnings calendar.

### Q4.1: Decoupled extraction?

Store all CEO-relevant comments, join to earnings windows at analysis time.

**Your answer:**

---

### Q4.2: Earnings calendar source?

WRDS StreetEvents or Compustat quarterly?

**Your answer:**

---

### Q4.3: Reddit coverage threshold?

Keep everything and filter at analysis, or enforce 20+ posts/CEO/year during
extraction?

**Your answer:**

---

## Decisions Queue

- **Decision 5:** Layer 2 processing — Colab session management, batch sizing,
  checkpointing for GPU scoring
- **Decision 6:** Additional trait dimensions — which ones, what dictionaries,
  priority order
