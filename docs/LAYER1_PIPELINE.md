# Layer 1 Pipeline: Collection and Filtering

**Runs on:** Local Ubuntu machine (32GB RAM, 2TB disk) **Output:** Parquet files
of all CEO-relevant Reddit comments 2005-2025

---

## Step 0: Prerequisites

**0A — CEO Universe Table**

- Source: ExecuComp via WRDS
- Output: `data/processed/ceo_universe.parquet`
- Schema: company, ticker, ceo_legal_name, ceo_common_name, ceo_name_variants[],
  sp500_entry_date, sp500_exit_date, ceo_start_date, ceo_end_date
- ~1000+ CEO-company-year tuples

**0B — CEO Name Search Patterns**

- Input: CEO Universe Table
- Output: `data/processed/search_patterns.parquet`
- Variants per CEO: full name, reversed name, "CEO of {company}", "{company}
  CEO", company + "CEO"

---

## Step 1: Subreddit Discovery

Goal: Build a queryable database of all subreddits with metadata so we can
analyze and filter for relevance.

### Step 1A — Download subreddit metadata (COMPLETED)

- **Source:** Academic Torrents — "Reddit subreddits metadata, rules and wikis
  2025-01" (torrent hash: `5d0bf258a025a5b802572ddc29cde89bf093185c`)
- **Tool:** `aria2c` (installed via `sudo apt install aria2`)
- **Command:**
  ```bash
  aria2c \
    --dir=data/inputs/subreddit_metadata_raw \
    --seed-time=0 \
    "magnet:?xt=urn:btih:5d0bf258a025a5b802572ddc29cde89bf093185c&tr=https%3A%2F%2Facademictorrents.com%2Fannounce.php&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
  ```
- Downloads all 4 files (2.65GB). Only `subreddits_2025-01.zst` (2.1GB) needed.
  Delete the other 3 after download.
- **Result:** 2.1GB compressed, ~22M subreddit records in zstd NDJSON format.
- **Time:** ~3 minutes on broadband.

### Step 1B — Load into DuckDB (COMPLETED)

- **Script:** `src/ceo_reddit/discovery/load_subreddit_metadata.py`
- **How it works:** DuckDB's native `read_json` reads zstd NDJSON directly — no
  Python line-by-line parsing. DuckDB handles decompression, JSON parsing, and
  column selection at C++ speed.
- **Command:**
  ```bash
  source .venv/bin/activate
  python3 -m src.ceo_reddit.discovery.load_subreddit_metadata
  ```
- **Result:** 21,865,531 rows loaded in 1.3 minutes (284,695 rows/sec).
- **Output:** `data/processed/subreddits.duckdb`
- **Key lesson:** Initial approach used Python `zstandard` + `json.loads` +
  `executemany` at 160 rows/sec (would have taken 38 hours). Letting DuckDB do
  the work natively was 175x faster.

**Schema loaded:**

```
subreddit_name       VARCHAR  — display_name
description          VARCHAR  — sidebar description (markdown)
public_description   VARCHAR  — short tagline
title                VARCHAR  — subreddit title
subscribers          BIGINT   — subscriber count
advertiser_category  VARCHAR  — Reddit's topic classification
over18               BOOLEAN  — NSFW flag
created_utc          BIGINT   — subreddit creation timestamp
subreddit_type       VARCHAR  — public/private/restricted
lang                 VARCHAR  — language
num_comments         BIGINT   — total comment count
num_posts            BIGINT   — total post count
earliest_post_at     BIGINT   — first post timestamp
earliest_comment_at  BIGINT   — first comment timestamp
```

### Step 1C — Analyze and filter (IN PROGRESS)

- **Tool:** DBeaver connected to `data/processed/subreddits.duckdb`
- **Goal:** Query 22M subreddits to find those relevant to business, finance,
  company discussion, and CEO mentions.
- **Process:** Iterative — run queries, review results, refine filters.
- **Output:** `data/processed/candidate_subreddits.csv` (subreddit, category,
  subscribers, num_comments, description, decision)
- **Expected result:** ~92 candidate subreddits for human review

**Discovery queries (run in order):**

**Query 1 — Data quality check:**

```sql
SELECT
    count(*) AS total_subreddits,
    count(CASE WHEN subscribers > 0 THEN 1 END) AS has_subscribers,
    count(CASE WHEN advertiser_category != '' THEN 1 END) AS has_category,
    count(CASE WHEN public_description != '' THEN 1 END) AS has_description
FROM subreddits;
```

Result:

- 21.8M total subreddits
- 2.3M have subscribers (89% have zero — dead/empty subs)
- **961 have advertiser_category** — useless as a filter
- 7M have descriptions
- **Decision:** Filter by descriptions and subscriber counts, not category.

**Query 2 — Activity distribution by subscriber tier:**

```sql
SELECT
    CASE
        WHEN subscribers >= 1000000 THEN '1M+'
        WHEN subscribers >= 100000 THEN '100K-1M'
        WHEN subscribers >= 10000 THEN '10K-100K'
        WHEN subscribers >= 1000 THEN '1K-10K'
        WHEN subscribers > 0 THEN '1-1K'
        ELSE 'zero'
    END AS tier,
    count(*) AS cnt,
    sum(num_comments) AS total_comments
FROM subreddits
GROUP BY tier
ORDER BY total_comments DESC;
```

Result:

- **1M+ subs:** 1,153 subreddits, 8.7B comments (42%)
- **100K-1M:** 8,257 subreddits, 7.5B comments (36%)
- **10K-100K:** 32,656 subreddits, 3.3B comments (16%)
- **1K-10K:** 96,665 subreddits, 567M comments (3%)
- **1-1K:** 2,171,486 subreddits, 141M comments (<1%)
- **zero:** 19,555,314 subreddits, 1.0B comments (5%)
- **Decision:** Only subreddits with **10K+ subscribers** matter. That's ~42,000
  subreddits containing 94% of all Reddit comments. The 19.5M zero-subscriber
  subreddits are dead/empty.

**Query 3 — Business/finance subreddits by description keywords:**

```sql
SELECT subreddit_name, subscribers, num_comments, public_description
FROM subreddits
WHERE subscribers >= 10000
  AND over18 = false
  AND (
    public_description ILIKE '%stock%'
    OR public_description ILIKE '%invest%'
    OR public_description ILIKE '%finance%'
    OR public_description ILIKE '%business%'
    OR public_description ILIKE '%CEO%'
    OR public_description ILIKE '%corporate%'
    OR public_description ILIKE '%earning%'
    OR public_description ILIKE '%wall street%'
    OR description ILIKE '%stock market%'
    OR description ILIKE '%investing%'
    OR description ILIKE '%fortune 500%'
    OR description ILIKE '%S&P 500%'
  )
ORDER BY subscribers DESC;
```

Result:

- **~500+ subreddits** returned
- Too broad — keywords like "business", "stock", and "invest" match many
  irrelevant subs (learning, gaming, crafts, foreign language finance subs, meme
  stock subs, crypto-only subs)
- Need to refine with company-specific matching

**Query 4 — S&P 500 company name/ticker matching against subreddits:**

- Data source: `data/inputs/snp1500.xls` (ExecuComp S&P 1500, 2010-2025)
- Filtered to `spcode = 'SP'` (S&P 500) → 499 unique companies, 3,276 CEO rows
- Extracted company first-word brands + tickers, matched against subreddit names
- Result: **169 subreddit matches**, but many false positives

Actual company subs (keep):

- `apple`, `nvidia`, `Amd`, `intel`, `Costco`, `starbucks`, `walmart`
- `boeing`, `Ford`, `microsoft`, `netflix`, `disney`, `uber`, `paypal`
- `salesforce`, `IBM`, `Dell`, `Adobe`, `Comcast`, `kroger`, `verizon`
- `CVS`, `FedEx`, `UPS`, `Chipotle`, `doordash`, `CoinBase`, `AirBnB`
- `Hilton`, `marriott`, `Target`, `lululemon`, `Ebay`, `Nike`, `Cisco`
- `crowdstrike`, `palantir`, `accenture`, `PLTR`, `TSLA`, `carvana`
- `Schwab`, `fortinet`, `servicenow`, `dexcom`

False positives (dropped):

- `de` (Germany sub), `boston` (city), `texas` (state), `cat` (cats)
- `pool`, `iron`, `ben`, `it`, `es`, `public`, `Home`, `analog`
- `union`, `progressive` (politics), `dominion` (game), `arch` (architecture)
- `keys`, `Fox` (animal), `match`, `coin`, `dash`, `delta` (math), `MLM`
  (anti-MLM)

**Decision:** Company-specific subreddits cannot be selected automatically by
name alone. Require human review of each match.

**Query 5 — Check for missing major company subreddits:**

Manually checked for known large company subs not caught by automated matching
(different naming conventions):

- `teslamotors` (3.4M subs, 5.8M comments) — NOT `Tesla` (Nikola Tesla sub)
- `google` (3.4M subs) — company name != ticker (GOOGL/GOOG)
- `amazon` (234K subs) — ticker is AMZN
- `tmobile` (190K subs), `ATT` (83K subs) — telecom
- `HomeDepot` (105K subs), `Lowes` (65K subs) — retail
- `facebook` (362K subs), `Twitter` (1.3M subs) — social media
- `unitedairlines` (117K subs), `Honda` (222K subs) — transport

**False positives removed from final list:**

- `Tesla` → Nikola Tesla inventor sub, not Tesla Inc
- `Hershey` → Hershey PA town sub
- `blackstone` → Blackstone griddle cooking sub
- All generic word matches (`de`, `boston`, `texas`, `cat`, etc.)

**Final candidate list: `data/processed/candidate_subreddits.csv`**

92 subreddits across 8 categories, 535M total comments:

- **news** (2 subs, 207M comments) — CEO mentions in news headlines
- **finance_investing** (16 subs, 152M comments) — core financial discussion
- **company** (57 subs, 87M comments) — company-specific communities
- **news_tech** (2 subs, 33M comments) — tech industry/CEO coverage
- **work_culture** (3 subs, 32M comments) — employee perspective on CEO behavior
- **business_corporate** (6 subs, 17M comments) — general business discussion
- **entertainment_biz** (1 sub, 5M comments) — box office / entertainment
  business
- **company_investor** (5 subs, 3M comments) — retail investor stock discussion

**Human review process:** Reviewing candidates in batches of 10. Each subreddit
evaluated for whether it contains discussion about S&P 500 CEOs and their
behavior/decisions/leadership, not just company products or generic topics.

**Batch 1 — General Finance/Investing:**

Approved:

- `wallstreetbets` — high volume CEO discussion alongside memes
- `stocks` — serious stock discussions, CEO news
- `investing` — general investing, CEO strategy discussion
- `StockMarket` — trade ideas and market analysis, CEO impact
- `finance` — finance news, CEO-related content
- `economy` — economy, business, politics, stocks — CEO coverage
- `ValueInvesting` — fundamental analysis includes CEO assessment
- `dividends` — dividend investors discuss CEO capital allocation decisions
- `FluentInFinance` — finance news and debate, CEO coverage

Dropped:

- `Daytrading` — focused on short-term price action and chart patterns, not CEO
  discussion. Comments are about technical entries/exits, not leadership.
- `options` — focused on Greeks, premium decay, and trade mechanics. Discussion
  is about option strategies, not CEOs.

**Batch 2 — Finance/Investing continued + Business:**

Approved:

- `Superstonk` — 29M comments, heavily focused on Ryan Cohen/GME but useful for
  that specific CEO
- `business` — general business news, CEO coverage
- `Entrepreneur` — startups and business, CEO/founder discussion
- `Accounting` — accountants discuss earnings quality, restatements, and audit
  failures. They reference CEOs in the context of financial reporting — directly
  relevant to the paper's self-presentation discrepancy construct.

Dropped:

- `ETFs` — fund selection discussion, not individual company CEOs
- `financialindependence` — personal savings rate and retirement planning, very
  little CEO discussion
- `Bogleheads` — index fund philosophy ("buy VTI and chill"). The whole point is
  to ignore company-level decisions. No CEO discussion.
- `realestateinvesting` — real estate investors discussing rental properties,
  not S&P 500 CEOs
- `smallbusiness` — small business owners asking about payroll, LLCs, hiring.
  Not S&P 500 CEO discussion.

**Batch 3 — News + Tech + Work Culture:**

Approved:

- `news` — 29.5M subs, 89.8M comments. US and world current events. CEO mentions
  in news headlines drive substantial discussion.
- `worldnews` — 44.2M subs, 117.4M comments. Major global news. International
  CEO coverage and corporate controversy.
- `technology` — 18.0M subs, 31.4M comments. Tech news. CEO announcements,
  product launches, and leadership decisions heavily discussed.
- `tech` — 661K subs, 1.3M comments. More thoughtful tech discussion, CEO
  strategy and industry impact.
- `antiwork` — 2.9M subs, 23.8M comments. Employees voicing unfiltered opinions
  about CEO behavior — purest form of crowd perception. "CEO gave himself $20M
  bonus while cutting healthcare" is exactly the signal that differs from
  earnings call self-presentation.
- `WorkReform` — 749K subs, 2.1M comments. Similar to antiwork — employee
  perspective on corporate leadership, labor policy, CEO decisions.
- `cscareerquestions` — 2.2M subs, 6.4M comments. Tech workers discuss CEOs in
  context of layoffs, return-to-office mandates, company culture, hiring
  freezes. Signals from people inside or close to these companies.

Dropped:

- `sales` — sales reps discussing quotas, cold calling, CRM tools. ~1% of
  comments touch CEOs (comp plan changes, leadership promises). Not worth the
  processing cost for low signal. Can add later if CEO coverage is thin.
- `marketing` — tactical discussions (email subject lines, CTR optimization).
  CEO mentions are rare case studies, not sustained perception. Same low-signal
  rationale as sales.
- `boxoffice` — about weekend grosses and ticket numbers. Discusses movies and
  studios, rarely individual CEOs. When Bob Iger or David Zaslav are mentioned,
  it's in passing, not substantive leadership discussion.

**Batch 4 — Major company subs (tech):**

Approved (all S&P 500 confirmed):

- `apple` — 6.1M subs, 12.4M comments
- `google` — 3.4M subs, 893K comments
- `teslamotors` — 3.4M subs, 5.8M comments
- `microsoft` — 1.4M subs, 451K comments
- `nvidia` — 2.1M subs, 5.1M comments
- `Amd` — 2.2M subs, 7.5M comments
- `intel` — 892K subs, 1.2M comments
- `netflix` — 1.7M subs, 1.9M comments
- `disney` — 2.3M subs, 705K comments
- `amazon` — 235K subs, 361K comments

**Batch 5 — Company subs (social media, retail, consumer):**

Approved (all S&P 500 confirmed):

- `facebook` — 362K subs, 800K comments
- `Twitter` — 1.3M subs, 581K comments
- `Nike` — 1.6M subs, 333K comments
- `Costco` — 881K subs, 3.6M comments
- `walmart` — 323K subs, 5.4M comments
- `starbucks` — 301K subs, 3.8M comments
- `Target` — 207K subs, 2.8M comments
- `lululemon` — 842K subs, 2.2M comments
- `Chipotle` — 121K subs, 1.2M comments
- `Ebay` — 198K subs, 1.2M comments

**Batch 6 — Company subs (transport, telecom, services):**

Approved:

- `uber` — 73.5K subs, 850K comments
- `doordash` — 466K subs, 5.5M comments
- `AirBnB` — 375K subs, 1.0M comments
- `Ford` — 118K subs, 483K comments
- `Rivian` — 116K subs, 979K comments
- `boeing` — 45K subs, 293K comments
- `verizon` — 117K subs, 1.3M comments
- `tmobile` — 190K subs, 3.0M comments
- `ATT` — 83K subs, 845K comments

Dropped:

- `Honda` — not S&P 500 (Japanese company)

**Batch 7 — Company subs (tech/enterprise, retail, hospitality):**

Approved (all S&P 500 confirmed):

- `Dell` — 101K subs, 734K comments
- `IBM` — 25K subs, 111K comments
- `salesforce` — 87K subs, 390K comments
- `Adobe` — 29K subs, 40K comments
- `Cisco` — 94K subs, 258K comments
- `Comcast` — 26K subs, 256K comments
- `CoinBase` — 387K subs, 1.7M comments
- `paypal` — 70K subs, 448K comments
- `Hilton` — 51K subs, 200K comments
- `marriott` — 98K subs, 411K comments

**Batch 8 — Company subs (retail, logistics, misc):**

Approved (all S&P 500 confirmed):

- `CVS` — 69K subs, 970K comments
- `kroger` — 51K subs, 619K comments
- `FedEx` — 42K subs, 386K comments
- `UPS` — 64K subs, 622K comments
- `Schwab` — 58K subs, 165K comments
- `Garmin` — 250K subs, 978K comments
- `motorola` — 28K subs, 153K comments
- `Ulta` — 108K subs, 462K comments
- `AutoZone` — 6K subs, 70K comments
- `carvana` — 28K subs, 141K comments

**Batch 9 — Company subs (enterprise tech, specialty):**

Approved (all S&P 500 confirmed):

- `crowdstrike` — 35K subs, 61K comments
- `palantir` — 31K subs, 41K comments
- `accenture` — 28K subs, 100K comments
- `servicenow` — 24K subs, 90K comments
- `fortinet` — 57K subs, 277K comments
- `dexcom` — 36K subs, 203K comments
- `Cummins` — 21K subs, 84K comments
- `HomeDepot` — 105K subs, 1.5M comments
- `Lowes` — 65K subs, 972K comments
- `unitedairlines` — 117K subs, 860K comments

**Batch 10 — Low-volume company subs + investor subs:**

Approved (low-priority, may yield minimal data):

- `honeywell` — 1.3K subs, 1.3K comments
- `caterpillar` — 3.4K subs, 5.3K comments
- `Expedia` — 1.4K subs, 2.7K comments
- `godaddy` — 3.2K subs, 10.5K comments
- `Seagate` — 1.7K subs, 4.9K comments
- `Autodesk` — 6.6K subs, 4.2K comments
- `qualcomm` — 2.5K subs, 895 comments
- `netapp` — 5.5K subs, 30K comments
- `Arista` — 2.9K subs, 5.9K comments
- `L3Harris` — 4.2K subs, 11K comments

Approved (investor subs — higher value, discuss CEO decisions through investor
lens):

- `teslainvestorsclub` — 87K subs, 1.4M comments
- `AMD_Stock` — 59K subs, 756K comments
- `NVDA_Stock` — 82K subs, 215K comments
- `PLTR` — 94K subs, 498K comments
- `TSLA` — 38K subs, 116K comments
- `AAPL` — 8.3K subs, 13K comments
- `amzn` — 1.6K subs, 654 comments

**Review complete.**

**Review summary:**

- Total approved: 81 subreddits
- Total dropped: 11 subreddits (Daytrading, options, ETFs,
  financialindependence, Bogleheads, realestateinvesting, smallbusiness, sales,
  marketing, boxoffice, Honda)
- Total comments across approved subs: 512M
- Total posts across approved subs: 30.5M
- All 81 approved subs confirmed present in DuckDB metadata (none missing)
- Updated CSV: `data/processed/candidate_subreddits.csv` (decision column
  populated)

**Step 1 is COMPLETE.**

---

## Next Steps (to resume)

When resuming this project, pick up from here in order:

**1. Build the CEO Universe Table (Step 0A)**

- Process `data/inputs/snp1500.xls` into
  `data/processed/ceo_universe.parquet`
- Filter to S&P 500 (`spcode = 'SP'`), extract unique (company, ticker, CEO
  name, CEO start/end dates) tuples
- Generate name variants for each CEO (Step 0B) for use in Reddit comment
  matching

**2. Download approved subreddits (Step 2)**

- Use the per-subreddit Academic Torrents torrent (hash:
  `3e3f64dee22dc304cdd2546254ca1f8e8ae542b4`) to download .zst files for the 81
  approved subreddits
- Configure torrent client to select only the approved subs
- Verify downloads with checksums
- Estimated size: 50-200GB temporary disk usage

**3. Stream, filter, and store CEO-relevant comments (Step 3)**

- Stream each .zst file, regex-match against CEO name patterns from Step 0B
- Write matched comments to Parquet, partitioned by year/subreddit
- Checkpoint after each .zst file for resumability
- Delete raw .zst files after verification

**4. Validate Layer 1 output (Step 4)**

- Coverage report: comments per CEO per year
- False positive sampling: manual review of 200-500 matched comments
- Deduplication across subreddits

**5. Resolve remaining architecture decisions**

- Decision 5: Layer 2 processing — Colab session management, batch sizing,
  checkpointing for FinBERT GPU scoring
- Decision 6: Additional trait dimensions — narcissism dictionary is small (13
  words), may need expansion. Decide priority order for scoring passes.

---

## Step 2: Data Download (IN PROGRESS)

**2A — Get torrent metadata**

- Fetched .torrent file for per-subreddit dataset using
  `aria2c --bt-metadata-only=true --bt-save-metadata=true`
- Torrent hash: `3e3f64dee22dc304cdd2546254ca1f8e8ae542b4`
- Full torrent: 3,693 GB (3.7TB), ~80K files across 40K subreddits
- Used `aria2c --show-files` on the .torrent file to get actual file sizes for
  our 81 approved subreddits

**2B — Actual download sizes (from torrent metadata)**

- **Total: 72.35 GB** for 81 subreddits (162 files: comments + submissions)
- Much smaller than the 157GB estimate — the 300-byte-per-comment guess was
  wrong. Real data is more compressed.
- Top 5 by size: worldnews (16.2GB), news (12.0GB), wallstreetbets (8.5GB),
  technology (4.9GB), superstonk (3.8GB)
- Smallest subs are under 20MB (palantir, crowdstrike, adobe)
- All 81 approved subs confirmed present in the torrent (none missing)

**2C — Selective Torrent Download**

- Using `aria2c --select-file=` with the 162 file indices for our 81 subs
- Parallel download — torrent protocol handles this efficiently from the same
  swarm
- Output: `data/raw/reddit/subreddits25/{subreddit}_comments.zst`,
  `data/raw/reddit/subreddits25/{subreddit}_submissions.zst`
- Storage: 72.35GB (temporary — deleted after Step 3)

**2D — Download Verification**

- Verify all 162 files downloaded, check sizes match torrent metadata
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

- **Step 0A, 0B:** Re-run (minutes)
- **Step 1A:** aria2c auto-resumes interrupted downloads
- **Step 1B:** Re-run (DuckDB native load, ~1.3 min)
- **Step 1C:** Human decision, no crash risk
- **Step 2A:** Torrent client auto-resumes
- **Step 3A:** Resume from last completed .zst file
- **Step 4A-4C:** Re-run against Parquet (fast DuckDB queries)

---

## Resource Usage

- **Step 1 (discovery):** ~2.5GB disk, <500MB RAM, ~5 min
- **Step 2 (download):** 72.35GB temp disk, minimal RAM, hours to days
- **Step 3 (filter):** <500MB working disk, <500MB RAM, 1-4 hours
- **Final output:** 2-10GB disk (after cleanup)
- **Disk after cleanup:** ~2.5GB (discovery) + 2-10GB (filtered) = ~5-13GB total

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
│   ├── snp1500.xls
│   ├── CEO_Integrity_Dictionary.csv
│   ├── CEO_Narcissism_Dictionary.csv
│   └── candidate_subreddits.csv
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
