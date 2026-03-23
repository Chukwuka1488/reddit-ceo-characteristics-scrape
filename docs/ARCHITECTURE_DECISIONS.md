# Architecture Decisions: Reddit CEO Characteristics Pipeline

## How This Document Was Built

This architecture was developed through an iterative question-and-answer process
between the research team and a principal data engineer. Each decision was
arrived at by:

1. Identifying the question and why it matters
2. Laying out the options with tradeoffs
3. Raising feasibility concerns based on our hardware constraints (32GB RAM, 2TB
   disk, zero budget)
4. Deciding based on what's defensible for an accounting journal publication
5. Documenting the reasoning so future contributors understand not just what was
   decided, but why

The research paper driving all decisions is: "CEO Self-Presentation Discrepancy
and Earnings Quality" — which measures the gap between how CEOs present
themselves in earnings calls vs. how Reddit communities perceive them. Every
pipeline decision serves this construct.

---

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

- **DuckDB** — out-of-core analytical queries, handles data exceeding RAM.
  Chosen because it runs in-process (no server), reads zstd NDJSON natively, and
  processed 22M rows in 1.3 minutes on our hardware. Research showed it's
  10-100x faster than Spark on single-machine workloads (DataTalks DE Zoomcamp
  uses it alongside dbt for local analytics).
- **Polars** — lazy/streaming DataFrames for any processing DuckDB can't do
  natively.
- **python-zstandard** — stream-decompress .zst without loading into memory.
  Required for the Step 3 filtering pipeline where we process line by line.
- **Parquet (zstd)** — storage format, 5-10x smaller than raw JSON. Standard for
  analytical workloads. DuckDB reads it with predicate pushdown and column
  pruning.
- **FinBERT** — transformer model fine-tuned on financial text, for trait
  scoring in Layer 2. Runs on Colab GPU, not local.
- **Trait dictionaries** — word lists for dictionary-based scoring as baselines
  alongside FinBERT.

**Stack research:** We investigated the DataTalks.club Data Engineering Zoomcamp
(free, open-source focused), Arctic Shift/Pushshift processing projects, and
single-machine TB-scale processing patterns. Key finding: DuckDB's native
`read_json` eliminates the need for Python-level JSON parsing entirely. Our
initial Python line-by-line approach ran at 160 rows/sec; DuckDB native ran at
284,695 rows/sec — a 175x improvement.

---

## Decision 1: Data Acquisition Strategy — DECIDED

**Question:** How do we get Reddit data onto our machine without downloading the
full 3.7TB dump?

**Options considered:**

- **Full monthly dump (3.7TB):** Ruled out immediately — doesn't fit on 2TB
  disk. Even if it did, we'd stream through every month's file to find
  CEO-relevant comments — massive wasted I/O.
- **Per-subreddit torrent (selective download):** Top 40K subreddits, each as
  its own .zst file. Download only what we need. Total is 3.7TB but individual
  subs range from MBs to ~15GB.
- **Arctic Shift API:** Query by subreddit + keyword + date range. Minimal
  storage but dependent on external service, rate-limited, may time out on large
  subs.

**Process:** We first considered jumping straight to downloading specific
subreddits, but realized we needed a discovery phase — we can't pick subreddits
without knowing what's available and what contains CEO signal. This led to the
three-pass approach.

**Decision:** Three-pass approach:

- Pass 1: Download subreddit metadata torrent (2.65GB, 22M subs), load into
  DuckDB, query and filter for relevance
- Pass 2: Iterative human review — 5 SQL queries progressively narrowing 22M
  subreddits to 81 approved candidates across 10 review batches
- Pass 3: Selective torrent download of only approved subreddits

---

## Decision 2: CEO Universe Dataset — DECIDED

**Question:** Where do we get a defensible list of S&P 500 CEOs across 20 years?

**Why this matters:** This list gates the entire pipeline. If the CEO names are
wrong, our Reddit filtering matches the wrong people, our subreddit selection is
wrong, and the paper's methodology is indefensible in peer review.

**Options considered:**

- **ExecuComp (WRDS):** Gold standard for accounting publications. Peer
  reviewers expect it. Requires university subscription.
- **SEC EDGAR (DEF 14A):** Free, defensible provenance. But parsing 20 years of
  proxy statements is its own data engineering project.
- **Wikipedia + validation:** Quick starting point but not citable as primary
  academic source.
- **Open datasets (Kaggle/GitHub):** Free but provenance varies, may lack CEO
  mapping.

**Decision:** ExecuComp via WRDS (university access confirmed).

- **Data available:** `data/discovery/snp1500.xls` — S&P 1500 companies,
  2010-2025, 31,281 rows, 107 columns
- **S&P 500 subset:** 499 unique companies, 3,276 CEO rows (`spcode = 'SP'`)
- **Key fields:** ticker, coname, exec_fullname, exec_fname, exec_lname,
  becameceo, pceo, year, spcode
- **Separate deliverable:** yes — build and validate the CEO panel dataset
  independently before feeding into the Reddit pipeline, because errors here
  cascade into everything downstream
- **Name variants:** full names + "CEO" + company name combos for Reddit
  matching (Option C from the original question — broadest recall, most API
  calls, but catches the most references)

---

## Decision 3: Pipeline Architecture — DECIDED (two-layer)

**Question:** Should we extract and score in one pass, or separate collection
from scoring?

**Why this matters:** The research scope expanded beyond the paper's original
two traits (overconfidence + integrity) to include additional dimensions like
narcissism. If we couple extraction with scoring, adding a new trait means
reprocessing all Reddit data.

**Decision:** Two-layer design:

- **Layer 1 (local machine):** Collect ALL CEO-relevant Reddit comments
  2005-2025. Trait-agnostic — store full text with metadata. Runs once and is
  never repeated. The expensive work (downloading, decompressing, filtering) is
  done once.
- **Layer 2 (Colab GPU):** Independent scoring passes over Layer 1 Parquet
  output. Each pass applies a different scoring method and writes scored output.
  Adding a new trait is a new scoring pass over existing data, not a new crawl.

**Why two layers:** We never reprocess Reddit data. Adding narcissism scoring
later is just a new Python script reading existing Parquet files. The 2005-2012
Reddit data is sparse (Reddit business discussion was minimal before ~2010) but
we still collect it for completeness.

---

## Trait Scoring Dictionaries

Reference word lists for Layer 2 dictionary-based scoring. These serve as
baselines alongside FinBERT model-based scoring. If FinBERT and dictionary
methods agree directionally on a CEO's trait score, this strengthens construct
validity.

**CEO Integrity Dictionary (`data/discovery/CEO_Integrity_Dictionary.csv`)**

- **Source:** Hennig, Bauer & Laamanen (2025) — "The role of CEO integrity in
  M&A decision-making", Strategic Management Journal
- **Contents:** 140 words categorized by integrity dimension (e.g.,
  Positive_Trust: "accountable", "candid", "forthright")
- **Use in pipeline:** Layer 2 Pass 1. Count dictionary word occurrences in
  Reddit comments to produce a dictionary-based integrity score per comment.
  Used as baseline/robustness check against FinBERT integrity scores.
- **Paper reference:** "CEO integrity is measured using the Hennig et al. (2025)
  226-word integrity dictionary" — the full 226-word version may include
  inflected forms; our 140-row file contains root words.

**CEO Narcissism Dictionary (`data/discovery/CEO_Narcissism_Dictionary.csv`)**

- **Source:** Derived from Loughran-McDonald financial text word lists, focused
  on narcissism-related terms
- **Contents:** 13 words (arrogance, arrogant, boast, boastful, etc.) with word
  count statistics, sentiment flags, and complexity measures
- **Use in pipeline:** Layer 2 Pass 2 (extension beyond the paper's original
  scope). Narcissism was identified as relevant because Ham et al. (2017) found
  "CFO narcissism is a better predictor of financial reporting quality than CEO
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

---

## Decision 4: Temporal Alignment and Extraction Strategy — DECIDED

**Question:** How do we align Reddit comments to earnings call timing? And
should we filter during extraction or at analysis time?

**Why this matters:** The paper requires Reddit text from the 90-day window
before each earnings announcement. If we bake this window into extraction, we
can't change it without reprocessing everything.

**Principle decided:** Collect broadly, filter narrowly at analysis time.

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

## Data Sources Not Yet Acquired

**Earnings call transcripts (CEO self-presentation side):**

The paper's self-presentation discrepancy requires scoring BOTH Reddit comments
(crowd perception) AND earnings call transcripts (CEO self-presentation). We
currently only have the Reddit pipeline. Transcripts are needed for Layer 2 when
computing the discrepancy.

**Recommended source:** Hugging Face `Bose345/sp500_earnings_transcripts`

- 33,362 transcripts, 685 S&P 500 companies, 2005-2025
- Speaker-segmented via `structured_content` field — array of `{speaker, text}`
  objects. CEO speech can be isolated by matching speaker name/role.
- 1.82GB single Parquet file, MIT license, free
- Coverage: 67 transcripts in 2005, ramps to 2,000+/year from 2015 onward
- Fields: symbol, company_name, company_id (Capital IQ), year, quarter, date,
  content (raw text), structured_content (speaker-segmented)
- company_id and symbol fields provide linkage to ExecuComp/CRSP

**Alternative source:** WRDS S&P Global Transcripts — 9,400+ companies from
2000, speaker-tagged. Requires WRDS access (already confirmed). More
comprehensive but not free. Use if Hugging Face dataset has gaps.

**How to acquire:**

```bash
source .venv/bin/activate
pip install datasets
python3 -c "
from datasets import load_dataset
ds = load_dataset('Bose345/sp500_earnings_transcripts', split='train')
ds.to_parquet('data/reference/earnings_transcripts.parquet')
"
```

- Output: `data/reference/earnings_transcripts.parquet` (~1.82GB)
- When needed: after Layer 1 is complete, before Layer 2 scoring begins

**Loughran-McDonald dictionaries (overconfidence baseline):**

- Not yet downloaded
- Available free from https://sraf.nd.edu/loughranmcdonald-master-dictionary/
- Needed for Layer 2 Pass 1 overconfidence scoring
- Contains positive/negative word lists designed for financial text
- Download the master dictionary CSV and place in `data/reference/`

---

## Decision 5: NLP Scoring Method for Layer 2 — OPEN

**Question:** What NLP method(s) do we use to score Reddit comments and earnings
call text on overconfidence, integrity, and narcissism?

**Why this matters:** The method choice determines whether the paper passes peer
review. Dictionary-based methods alone are increasingly insufficient for
top-tier accounting/finance journals.

**Evidence from our elite journal reading list:**

- **Merkley et al. (2024, Review of Accounting Studies)** — used CryptoBERT,
  FinBERT, and Twitter-RoBERTa (3 transformer models) for sentiment on social
  media text. Did NOT use dictionaries as primary method. Even they noted
  transformers "struggle with crypto colloquialisms, idioms, sarcasm,
  expletives, and abbreviations."
- **Bogachek et al. (2025, Review of Accounting Studies)** — used LDA topic
  modeling + XGBoost for prediction. Machine learning, not dictionaries.
  Positioned against "keyword searches within narrow portions" as a limitation
  of prior work.
- **Mai et al. (2018, JMIS)** — used Loughran-McDonald dictionary for bitcoin
  sentiment. Our own review flagged this as a weakness: "Loughran-McDonald
  dictionary designed for SEC filings, not informal crypto social media —
  misclassification rates likely substantial but never assessed or validated
  against human coders."

**Evidence from broader literature (web research):**

- **Huang et al. (2023, Contemporary Accounting Research)** — FinBERT
  "substantially outperforms" Loughran-McDonald AND other ML methods (naive
  Bayes, SVM, CNN, LSTM) for financial sentiment. Current gold standard.
- **Li et al. (2021, Review of Financial Studies)** — rejected dictionaries for
  measuring corporate culture because "subtle and nuanced" language escapes even
  diligent human dictionary construction. Used word2vec instead.
- **de Kok (2025, Management Science)** — published framework for using LLMs
  (ChatGPT/GPT-4) in accounting research. LLMs can solve "any textual analysis
  task solvable using non-generative methods" plus tasks previously requiring
  human coding.
- **Bochkay et al. (2023, CAR)** — survey paper representing field consensus:
  dictionaries are bag-of-words (ignore context, negation, word order),
  transformers use attention to capture how words are used in context. The field
  is explicitly moving from dictionaries to contextual models.

**The problem with dictionaries for our use case:**

- "This CEO is NOT honest" scores positive on integrity (dictionary sees
  "honest")
- "dude is shady af" expresses low integrity but matches zero dictionary words
- "cooking the books" — no dictionary captures this
- Reddit slang, sarcasm, and informal language systematically evade
  dictionary-based detection
- Loughran-McDonald was designed for 10-K filings, not Reddit posts

**Method hierarchy (from simplest to most capable):**

Each level builds on the one below. We use multiple levels for construct
validity — if simpler and more complex methods agree, that strengthens the
paper.

- **Level 1 — Dictionaries (baseline/robustness):** Loughran-McDonald
  (overconfidence), Hennig (integrity), narcissism dictionary. Count word
  occurrences. Fast, free, reproducible. Misses context, negation, slang. Used
  ONLY as a robustness check — reviewers expect to see dictionary baselines
  alongside modern methods, but will reject dictionaries as the sole method.

- **Level 2 — Traditional ML (SVM, Random Forest, XGBoost on TF-IDF):**
  Feature-based classifiers. Still published in top journals — Bogachek et al.
  (2025 RAST) used XGBoost. More capable than dictionaries because they learn
  feature combinations. Could serve as an intermediate method if FinBERT is too
  expensive to validate. Requires labeled training data.

- **Level 3 — Deep Learning (LSTM, CNN):** Neural networks on word embeddings.
  Superseded by transformers — Huang et al. (2023 CAR) showed FinBERT
  outperforms CNN and LSTM on financial text. NOT worth implementing separately
  since FinBERT (Level 4) exists and beats them.

- **Level 4 — FinBERT (PRIMARY METHOD):** Transformer pre-trained on financial
  text. Current gold standard per Huang et al. (2023 CAR). Handles negation,
  context, domain-specific vocabulary. Runs on Colab GPU (free). Processes 1-5M
  filtered comments in hours. May struggle with Reddit slang since it was
  trained on formal financial text — validate against human-labeled sample.

- **Level 5 — LLMs (LABELING ONLY, not bulk scoring):** Claude/GPT-4 following
  de Kok (2025 Management Science) framework. Used ONLY to label a small sample
  of 5,000-10,000 Reddit comments for: (a) Creating training data for a
  fine-tuned classifier (b) Validating FinBERT scores on Reddit text (c)
  Handling complex cases FinBERT can't resolve (sarcasm, slang) Cost: ~$50-300
  for 5-10K samples. NOT used on all 500M comments (~$5-15M would be
  prohibitive).

- **Supplementary — LDA topic modeling:** Unsupervised topic discovery to
  understand what themes drive CEO perception (leadership, scandal, layoffs,
  innovation). Descriptive/exploratory, not for trait scoring.

**Processing cost reality:**

- Layer 1 filters 500M comments → 1-5M CEO-relevant (regex matching, free)
- FinBERT scores 1-5M comments → hours on Colab GPU (free)
- LLM labels 5-10K sample → $50-300 (one-time)
- Dictionaries score 1-5M comments → seconds (free)
- We are NOT running LLMs on 500M or even 1-5M comments

**Proposed approach for the paper (for team review):**

- **Primary scoring: FinBERT** on all 1-5M filtered comments (Colab GPU, free)
- **Validation: LLM labeling** of 5-10K sample to verify FinBERT accuracy on
  Reddit text ($50-300)
- **Robustness: Dictionary baselines** to show directional agreement
- **Optional: Traditional ML (XGBoost)** trained on LLM-labeled data as an
  alternative classifier for comparison
- **Exploratory: LDA** for thematic analysis of CEO discussion topics

**The defensible story for reviewers:** "We use FinBERT (Huang et al. 2023 CAR)
as our primary scoring method, validated against dictionary baselines
(Loughran-McDonald; Hennig et al. 2025) and LLM-labeled ground truth (following
de Kok 2025 Management Science). This multi-method approach follows current best
practices in textual analysis for accounting research (Bochkay et al. 2023
CAR)."

**Still to decide:**

- Which LLM for labeling (Claude vs GPT-4 vs open-source)?
- Fine-tune a classifier on LLM labels, or use LLM only for validation?
- Colab session management and batch sizing for FinBERT inference
- Human labeling sample size for inter-rater reliability with LLM/FinBERT

---

## Decisions Queue

- **Decision 6:** Layer 2 processing logistics — Colab session management, batch
  sizing, checkpointing for GPU scoring
- **Decision 7:** Additional trait dimensions — narcissism dictionary is small
  (13 words), likely need transformer-based approach instead. Priority order for
  scoring passes.
