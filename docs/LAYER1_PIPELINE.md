# Layer 1 Pipeline: Collection and Filtering

**Runs on:** Local Ubuntu machine (32GB RAM, 2TB disk)
**Output:** Parquet files of all CEO-relevant Reddit comments 2005-2025

---

## Step 0: Prerequisites

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

---

## Step 1: Subreddit Discovery

Goal: Build a queryable database of all subreddits with metadata so we can
analyze and filter for relevance.

### Step 1A — Download subreddit metadata

**Completed prerequisites:**

- [x] `aria2c` installed (`sudo apt install aria2`)
- [x] Directory created: `data/discovery/subreddit_metadata_raw/`

**Magnet link** (Academic Torrents download URLs require a browser session, so
we use the magnet link for CLI):

```
magnet:?xt=urn:btih:5d0bf258a025a5b802572ddc29cde89bf093185c&tr=https%3A%2F%2Facademictorrents.com%2Fannounce.php&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce
```

**Download command:**

```bash
cd /home/harkeybour/Desktop/reddit-ceo-characteristics-scrape

aria2c \
  --dir=data/discovery/subreddit_metadata_raw \
  --seed-time=0 \
  "magnet:?xt=urn:btih:5d0bf258a025a5b802572ddc29cde89bf093185c&tr=https%3A%2F%2Facademictorrents.com%2Fannounce.php&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
```

**Notes:**

- Downloads all 4 files (2.65GB total). `--show-files` / `--select-file` do not
  work with magnet links — they require a local .torrent file.
- `--seed-time=0` stops seeding after download completes
- We only need `subreddits_2025-01.zst` (2.24GB). Delete the other 3 files
  after download:
  ```bash
  cd data/discovery/subreddit_metadata_raw/reddit/subreddits/
  rm subreddits_meta_only_2025-01.zst subreddit_rules_2025-01.zst subreddit_wikis_2025-01.zst
  ```
- Time: depends on bandwidth and torrent seeders

**Verify download:**

```bash
# Check file exists and size is reasonable (~2.24GB)
ls -lh data/discovery/subreddit_metadata_raw/reddit/subreddits/subreddits_2025-01.zst

# Peek at first 3 lines to confirm format (zstd-compressed NDJSON)
zstdcat data/discovery/subreddit_metadata_raw/reddit/subreddits/subreddits_2025-01.zst \
  | head -n 3 | python3 -m json.tool --no-ensure-ascii | head -n 50
```

### Step 1B — Install Python dependencies

```bash
cd /home/harkeybour/Desktop/reddit-ceo-characteristics-scrape

# Activate existing venv
source .venv/bin/activate

# Install dependencies for this step
pip install duckdb zstandard
```

### Step 1C — Load into DuckDB

**Script:** `scripts/load_subreddit_metadata.py`

The script does:

1. Stream-decompress `subreddits_2025-01.zst` line by line
2. Parse each JSON line, extract only the fields we need
3. Batch-insert into DuckDB (10K rows per batch)
4. 22M rows total — takes ~10-20 minutes

**Fields we extract per subreddit:**

```
subreddit_name       — display_name
description          — sidebar description (markdown)
public_description   — short tagline
subscribers          — subscriber count
advertiser_category  — Reddit's topic classification
over18               — NSFW flag
created_utc          — subreddit creation timestamp
subreddit_type       — public/private/restricted
num_comments         — from _meta.num_comments
num_posts            — from _meta.num_posts
```

**Output:** `data/discovery/subreddits.duckdb`

**Verify load:**

```bash
source .venv/bin/activate
python3 -c "
import duckdb
con = duckdb.connect('data/discovery/subreddits.duckdb')
print(con.sql('SELECT count(*) as total FROM subreddits').fetchone())
print(con.sql('SELECT * FROM subreddits LIMIT 5').df())
"
```

### Step 1D — Analyze and filter

Once loaded, query DuckDB to find relevant subreddits:

```sql
-- How many subreddits by advertiser_category
SELECT advertiser_category, count(*) as cnt
FROM subreddits
WHERE subscribers > 1000
GROUP BY advertiser_category
ORDER BY cnt DESC;

-- Business/finance/investing subreddits with meaningful activity
SELECT subreddit_name, subscribers, num_comments, public_description
FROM subreddits
WHERE over18 = false
  AND subscribers > 5000
  AND (
    public_description ILIKE '%business%'
    OR public_description ILIKE '%finance%'
    OR public_description ILIKE '%invest%'
    OR public_description ILIKE '%stock%'
    OR public_description ILIKE '%CEO%'
    OR public_description ILIKE '%corporate%'
    OR advertiser_category ILIKE '%business%'
    OR advertiser_category ILIKE '%finance%'
  )
ORDER BY subscribers DESC;

-- Company-specific subreddits (match against S&P 500 names)
-- Run after Step 0A (CEO Universe Table) is built
```

- **Human decision point:** Review query results, tag subreddits as
  relevant/not relevant
- **Output:** `data/discovery/selected_subreddits.csv`
  (subreddit, category, file_size_gb, relevance_reason, decision: yes/no)
- **Expected result:** 20-50 subreddits

---

## Step 1B (later) — Get per-subreddit data torrent file list

After Step 1D identifies relevant subreddits, we need to confirm they exist in
the per-subreddit data torrent and get their file sizes.

```bash
# Download only the .torrent file (not data) for the per-subreddit dataset
# Torrent: "Subreddit comments/submissions 2005-06 to 2025-12"
aria2c --show-files \
  "https://academictorrents.com/download/3e3f64dee22dc304cdd2546254ca1f8e8ae542b4"
```

This shows the 40K file list. We cross-reference against our selected subreddits
to confirm availability and get download sizes.

---

## Step 2: Data Download

**2A — Selective Torrent Download**

- Torrent client downloads only selected subreddit .zst files from the
  per-subreddit data torrent.
- Output: `data/raw/{subreddit}_comments.zst`,
  `data/raw/{subreddit}_submissions.zst`
- Storage: 50-200GB (temporary)
- Time: hours to days

**2B — Download Verification**

- Verify checksums, log sizes, confirm completeness.
- Output: `data/raw/download_manifest.csv`

---

## Step 3: Stream, Filter, Store

Goal: Stream through each .zst file, extract only CEO-relevant comments, write
to Parquet.

**3A — Stream-Filter Pipeline (per subreddit)**

1. Stream decompress .zst (python-zstandard, line by line)
2. Parse JSON line → dict
3. Match against CEO name patterns from Step 0B (compiled regex)
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

**3C — Partitioning:**
`data/filtered/year={YYYY}/subreddit={name}/part-{N}.parquet` (zstd compressed,
estimated 2-10GB total)

**3D — Post-Filter Cleanup:** Delete raw .zst files after verifying Parquet
output. Human confirmation required. Reclaims 50-200GB.

---

## Step 4: Validation

**4A — Coverage Report:** DuckDB queries → comments per CEO per year, per
subreddit per year, match type distribution. Flag CEOs < 20 mentions/year.

**4B — False Positive Sampling:** Random 200-500 matched comments for manual
review. If false positive rate > 10%, tighten matching and re-run Step 3.

**4C — Deduplication:** Check for duplicate comment_ids. Deduplicate, keep
first.

---

## Checkpointing

| Step   | Resume behavior                              |
| ------ | -------------------------------------------- |
| 0A, 0B | Re-run (minutes)                             |
| 1A     | aria2c auto-resumes interrupted downloads    |
| 1B     | Re-run (pip install, seconds)                |
| 1C     | Re-run (DuckDB load, 10-20 min)             |
| 1D     | Human decision, no crash risk                |
| 2A     | Torrent client auto-resumes                  |
| 3A     | Resume from last completed .zst file         |
| 4A-4C  | Re-run against Parquet (fast DuckDB queries) |

---

## Resource Usage

| Resource           | Step 1 (discovery) | Step 2 (download) | Step 3 (filter) | Final output |
| ------------------ | ------------------ | ----------------- | --------------- | ------------ |
| Disk               | ~2.5GB             | 50-200GB temp     | < 500MB working | 2-10GB       |
| RAM                | < 500MB            | Minimal           | < 500MB         | —            |
| Time               | ~30 min            | Hours-days        | 1-4 hours       | —            |
| Disk after cleanup | ~2.5GB (keep)      | —                 | —               | 2-10GB       |

---

## Directory Structure

```
data/
├── reference/
│   ├── ceo_universe.parquet
│   └── search_patterns.parquet
├── discovery/
│   ├── subreddit_metadata_raw/
│   │   └── reddit/subreddits/subreddits_2025-01.zst
│   ├── subreddits.duckdb
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
