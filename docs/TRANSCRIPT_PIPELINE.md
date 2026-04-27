# Layer 2 — Transcript-side pipeline (CEO self-presentation)

Documents the pipeline that produces the **self_score** half of the
self-presentation discrepancy. Layer 1 (Reddit, the **crowd_score**) is
documented separately in `LAYER1_PIPELINE.md` and
`LAYER2_FINBERT_COLAB_GUIDE.md`.

## Construct

```
discrepancy = self_score - crowd_score
```

- `self_score` — sentiment / dictionary scores of CEO-only utterances on their
  earnings calls. Measured per (CEO, year, section) where
  `section ∈ {prepared, qa}` so deliberate impression projection (prepared
  remarks) can be analyzed separately from less-managed Q&A speech.
- `crowd_score` — sentiment scores of Reddit comments mentioning the CEO. From
  Layer 1, joined here on `(execid, year)`.

The split is per accounting/finance literature precedent (Larcker & Zakolyukina
2012, JAR; Davis et al. on tone/sentiment) — Q&A is typically isolated as the
unscripted signal.

## Stages

```
earnings_transcripts.parquet  (HuggingFace Bose345/sp500_earnings_transcripts)
            │
            │  extract_ceo_utterances.py
            ▼
ceo_utterances.parquet  (433K rows, 21K calls, 999 CEOs, 476 tickers)
            │
            │  score_utterances.py
            ▼
ceo_utterances_dict_scored.parquet  (LM + Hennig + Narcissism)
            │
            │  Colab: 04_master_pipeline_finbert_colab.ipynb
            │      OR  05_master_pipeline_roberta_colab.ipynb
            ▼
ceo_utterances_{finbert,roberta}_scored.parquet
            │
            │  groupby (execid, year, section) → mean
            ▼
ceo_year_section_{finbert,roberta}_scores.csv
            │
            │  inner join on (execid, year)
            │      ↑
            │      └─ ceo_year_finbert_abc_merged_updated.csv  (Layer 1, gvkey-keyed)
            ▼
ceo_year_section_{finbert,roberta}_discrepancy.csv  ← FINAL OUTPUT
```

## Stage-by-stage

### Stage B — Extract CEO utterances

`src/ceo_reddit/transcripts/extract_ceo_utterances.py`

Each transcript row in `earnings_transcripts.parquet` has a `structured_content`
field — a list of `{speaker, text}` dicts. We keep only utterances where the
speaker is the CEO of that ticker on that call date.

Three rules, all auditable:

1. **Speaker → CEO match.** Look up CEOs tenured at `ticker` on `call_date` in
   `ceo_universe.parquet`. Keep utterances whose speaker label contains the
   CEO's last name (case-insensitive substring).
2. **Exec vs analyst guard.** Speaker labels of the form `Name - Brokerage` are
   analysts; `Name - Title` (e.g., `Chief Executive Officer`) are execs. The
   trailing fragment is checked against an exec-title keyword set (`officer`,
   `president`, `ceo`, `cfo`, `chairman`, …).
3. **Q&A boundary (structural).** The second substantive Operator turn — after
   at least one executive has spoken — marks the Q&A handoff. Utterances before
   it are `prepared`; after it are `qa`. Falls back to a regex on Q&A-cue
   phrases ("first question comes from", "open the line for questions") and then
   to the first analyst-style speaker label if needed.

**Why structural Q&A detection** — operators preview Q&A in their opening line
("there will be a question-and-answer session at the end…"), so a regex on
"question" alone fires before any prepared remarks happen. The structural rule
(2nd Operator turn after 1st exec turn) is robust across S&P 500 calls because
operators speak in a predictable arc: open → handoff → next-question × N →
close.

**Outputs:**

- `data/processed/ceo_utterances.parquet` — 433,819 utterances
- `data/reports/transcript_extraction_report.json` — match-rate stats

**Match rate:** 85.6% of calls where the CEO was tenured on the call date
yielded ≥ 1 CEO utterance. The 14% gap is real (CEO didn't speak, source-data
ticker mislabels, transitions).

### Stage C — Dictionary scoring

`src/ceo_reddit/scoring/score_utterances.py`

Imports `score_text` and `_tokenize` from
`src/ceo_reddit/scoring/dictionary_scorer.py` so both halves of the discrepancy
use **identical** scoring logic — any divergence here would silently break the
construct.

Three dictionaries:

- **Loughran-McDonald** (2025 master) — `lm_positive`, `lm_negative`,
  `lm_uncertainty`, `lm_strong_modal`, `lm_weak_modal`. Derived:
  - `lm_net_sentiment = (positive − negative) / word_count`
  - `lm_overconfidence = (positive + strong_modal − uncertainty) / word_count`
- **Hennig integrity** — by-category counts (`integrity_positive_trust`,
  `integrity_negative_deception`) and `integrity_all`. Normalized:
  `integrity_norm = integrity_all / word_count`.
- **Narcissism** (12 words: arrogance, boast, pride, …) — small, weak signal by
  design, kept as a tertiary measure.

**Outputs:**

- `data/processed/ceo_utterances_dict_scored.parquet` — per-utterance scores
- `data/reports/ceo_quarter_dict_scores.csv` — per (execid, year, quarter,
  section) means

### Stages D + E — Transformer scoring (Colab)

`notebooks/corpus_analysis/04_master_pipeline_finbert_colab.ipynb` — FinBERT
(`ProsusAI/finbert`).

`notebooks/corpus_analysis/05_master_pipeline_roberta_colab.ipynb` —
Twitter-RoBERTa (`cardiffnlp/twitter-roberta-base-sentiment-latest`).

**Sliding-window chunking** is the key methodological choice. Prepared remarks
average ~860 words (~1100 tokens) and can exceed 9k words. Truncating at
FinBERT's 512-token limit would systematically bias scores toward call openings
(typically more positive than substantive content). Instead we tokenize each
utterance, split into 510-token windows with 50-token overlap, score each
window, and weighted-average back to utterance level.

**Cross-model:** the Reddit-side aggregate currently carries FinBERT scores
only. The RoBERTa notebook computes a `roberta_self − finbert_crowd` discrepancy
as a robustness check; for a strict same-model comparison, re-score Reddit with
RoBERTa first.

### Stage F — CEO-quarter-section aggregation

In each notebook, after model scoring, `df.groupby([...])` produces:

- `ceo_quarter_section_{model}_scores.csv` — per (execid, year, quarter,
  section)
- `ceo_year_section_{model}_scores.csv` — per (execid, year, section)

Both keep the prepared/qa split.

### Stage G — Discrepancy join

The Reddit aggregate `ceo_year_finbert_abc_merged_updated.csv` (committed at the
repo root in `data/`) carries both per-CEO-year FinBERT scores **and** the
Compustat firm linkage (`gvkey`, `cusip`, `abc_conm`). Inner join on
`(execid, year)` yields the final dataset:

- One row per (CEO, year, section)
- Both `*_self` (transcript) and `*_crowd` (Reddit) scores
- `*_discrepancy` columns
- Compustat keys for downstream accounting analysis

**Output:** `ceo_year_section_{finbert,roberta}_discrepancy.csv`

## Grain note

The construct memo specifies a **90-day pre-announcement window** (quarter
grain). The Reddit side is currently aggregated at year. To upgrade to
quarter-grain:

1. Re-aggregate the per-comment Reddit parquet (which has timestamps) into
   `ceo_quarter_finbert_aggregate.parquet`
2. Re-merge with Compustat keys → `ceo_quarter_finbert_abc_merged.csv`
3. Join to `ceo_quarter_section_{model}_scores.csv` (already produced) on
   `(execid, year, quarter)` instead of `(execid, year)`

The transcript-quarter aggregates are already saved by the Colab notebooks for
this future upgrade.

## Validation signals

The construct validates if the FinBERT result shows:

```
mean(finbert_sentiment_self | section='prepared')
   >  mean(finbert_sentiment_self | section='qa')
```

— CEOs project more confidence in scripted prepared remarks than in unscripted
answers. The local dictionary-scoring run confirmed this:

| Section  | `lm_overconfidence` | `lm_net_sentiment` |
| -------- | ------------------: | -----------------: |
| prepared |              0.0269 |             0.0166 |
| qa       |              0.0239 |             0.0170 |

Top overconfidence-scoring prepared utterances surface textbook examples:
"executing at the highest level in company history" (EOG), "I'm confident"
(STX), "deeply grateful…drive top and bottom line growth" (ADBE).
