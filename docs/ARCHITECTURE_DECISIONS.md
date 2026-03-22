# Architecture Decisions: Reddit CEO Characteristics Pipeline

## Constraints

- **RAM:** 32GB
- **Disk:** 2TB
- **OS:** Ubuntu
- **Data Source:** Academic Torrents Reddit per-subreddit dumps (top 40K subs,
  zstd NDJSON) + Arctic Shift API
- **Budget:** Zero cost (open-source stack only)
- **Purpose:** Accounting journal publication + future research extensions
- **GPU:** Google Colab Pro (Layer 2 scoring)

## Stack

- **DuckDB** — out-of-core analytical queries, handles data exceeding RAM
- **Polars** — lazy/streaming DataFrames
- **python-zstandard** — stream-decompress .zst without loading into memory
- **Parquet (zstd)** — storage format, 5-10x smaller than raw JSON
- **FinBERT** — trait scoring (Layer 2, runs on Colab GPU)
- **Trait dictionaries** — word lists for dictionary-based scoring (Layer 2)

---

## Decision 1: Data Acquisition Strategy — DECIDED

Three-pass approach:

- Metadata catalog: download subreddit metadata torrent (22M subs), load into
  DuckDB, query and filter for relevance
- Subreddit selection: 81 subreddits approved through iterative human review
  across 10 batches (documented in LAYER1_PIPELINE.md)
- Selective download: torrent only approved subreddits from the per-subreddit
  data torrent

Monthly dump (3.7TB) ruled out — doesn't fit on disk, wasteful.

---

## Decision 2: CEO Universe Dataset — DECIDED

- **Source:** ExecuComp via WRDS (`data/discovery/snp1500.xls`)
- **Data available:** S&P 1500 companies, 2010-2025, 31,281 rows, 107 columns
- **S&P 500 subset:** 499 unique companies, 3,276 CEO rows (`spcode = 'SP'`)
- **Key fields:** ticker, coname, exec_fullname, exec_fname, exec_lname,
  becameceo, pceo, year, spcode
- **Separate deliverable:** yes — build and validate before feeding into Reddit
  pipeline
- **Name variants:** full names + "CEO" + company name combos for Reddit
  matching

---

## Decision 3: Pipeline Architecture — DECIDED (two-layer)

- **Layer 1 (local):** Collect all CEO-relevant Reddit comments 2005-2025.
  Trait-agnostic. Full text stored. Runs once.
- **Layer 2 (Colab GPU):** Scoring passes over Layer 1 output. Each pass applies
  a different scoring method. Repeatable without re-downloading Reddit data.

---

## Trait Scoring Dictionaries

Reference word lists for Layer 2 dictionary-based scoring. These serve as
baselines alongside FinBERT model-based scoring.

**CEO Integrity Dictionary (`data/discovery/CEO_Integrity_Dictionary.csv`)**

- **Source:** Hennig, Bauer & Laamanen (2025) — "The role of CEO integrity in
  M&A decision-making", Strategic Management Journal
- **Contents:** 140 words categorized by integrity dimension (e.g.,
  Positive_Trust: "accountable", "candid", "forthright")
- **Use in pipeline:** Layer 2 scoring pass for integrity trait. Count
  dictionary word occurrences in Reddit comments to produce a dictionary-based
  integrity score per comment. Used as baseline/robustness check against FinBERT
  integrity scores.
- **Paper reference:** "CEO integrity is measured using the Hennig et al. (2025)
  226-word integrity dictionary" — the full 226-word version may include
  inflected forms; our 140-row file contains root words.

**CEO Narcissism Dictionary (`data/discovery/CEO_Narcissism_Dictionary.csv`)**

- **Source:** Derived from Loughran-McDonald financial text word lists, focused
  on narcissism-related terms
- **Contents:** 13 words (arrogance, arrogant, boast, boastful, etc.) with word
  count statistics, sentiment flags, and complexity measures
- **Use in pipeline:** Layer 2 scoring pass for narcissism trait — an additional
  dimension beyond the paper's original two traits (overconfidence + integrity).
  Narcissism was identified as relevant because Ham et al. (2017) found "CFO
  narcissism is a better predictor of financial reporting quality than CEO
  narcissism."
- **Note:** Small dictionary (13 words). May need expansion or supplementation
  with a more comprehensive narcissism word list for robust scoring.

**How dictionaries fit into Layer 2:**

- Layer 2 runs multiple independent scoring passes over the same Layer 1 Parquet
  data
- **Pass 1 (current paper):** Overconfidence (FinBERT + Loughran-McDonald) +
  Integrity (FinBERT + Hennig dictionary)
- **Pass 2 (extension):** Narcissism (FinBERT + narcissism dictionary)
- **Future passes:** Additional traits as dictionaries/models are identified
- Dictionary scores serve as baselines — if FinBERT and dictionary methods agree
  directionally, this strengthens construct validity

---

## Decision 4: Temporal Alignment and Extraction Strategy — DECIDED

Principle: **collect broadly, filter narrowly at analysis time.**

- **Decoupled extraction (Q4.1):** Yes. Layer 1 stores ALL CEO-relevant comments
  with timestamps. Windowing to 90-day pre-earnings windows happens at analysis
  time by joining against the earnings calendar. This allows experimenting with
  different window sizes (60, 90, 120 days) without reprocessing Reddit data.
- **Earnings calendar source (Q4.2):** WRDS StreetEvents. Same source as
  earnings call transcripts, so announcement dates come bundled. One source for
  both transcripts and timing.
- **Reddit coverage threshold (Q4.3):** Keep everything, filter at analysis
  time. A CEO might have low mentions in one subreddit but sufficient coverage
  across multiple subreddits — we can't know total coverage until all subreddits
  are processed. Sub-threshold CEO-quarters may still be useful for robustness
  checks. The 20 posts/CEO/year minimum from the paper is enforced during
  analysis, not during extraction.

---

## Decisions Queue

- **Decision 5:** Layer 2 processing — Colab session management, batch sizing,
  checkpointing for GPU scoring
- **Decision 6:** Additional trait dimensions — which ones, what dictionaries,
  priority order
