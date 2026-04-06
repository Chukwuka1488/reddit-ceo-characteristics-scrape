# Layer 2 Pass 2: FinBERT + Twitter-RoBERTa Scoring — Colab Guide

Step-by-step explanation of every cell in
`notebooks/corpus_analysis/03_finbert_scoring_colab.ipynb`.

---

## Prerequisites

Before opening the notebook:

1. **Upload** `data/filtered_clean/ceo_mentions_clean.parquet` (117 MB) to
   Google Drive at `My Drive/ceo_reddit/data/`
2. **Open** the notebook in Google Colab (from GitHub or upload directly)
3. **Set runtime:** Runtime > Change runtime type > **T4 GPU**

---

## Part 1 — FinBERT (Financial Sentiment)

### Cell 0 — Title & Purpose (Markdown)

Describes what the notebook does: score 639K Reddit comments with two models for
cross-validation. Lists the two models and why we use both.

### Cell 1 — Section Header (Markdown)

"Step 1 — Setup & GPU Check"

### Cell 2 — GPU Verification

**What:** Checks if a GPU is available and prints its name and memory.

**Why:** FinBERT inference on CPU takes 40-80 hours. On a T4 GPU it takes 1-3
hours. If no GPU is detected, the notebook warns you to change the runtime type.
This prevents accidentally running for days on CPU.

### Cell 3 — Install Dependencies

**What:** `pip install -q transformers fastparquet`

**Why:** Colab has PyTorch pre-installed but not `transformers` (the HuggingFace
library that loads FinBERT) or `fastparquet` (lightweight parquet reader). The
`-q` flag keeps output quiet.

### Cell 4 — Mount Google Drive

**What:** Mounts your Google Drive at `/content/drive/` and sets up file paths.

**Why:** Your data file (`ceo_mentions_clean.parquet`) lives on Google Drive.
Mounting makes it accessible as a regular file path. The cell also verifies the
file exists — if you haven't uploaded it yet, it fails here with a clear error
message telling you where to put the file.

### Cell 5 — Copy Data to Local Disk

**What:** Copies the parquet file from Drive to Colab's local `/content/` disk.

**Why:** Google Drive mounted via FUSE is slow for random I/O reads. Colab's
local SSD is 10-50x faster. For 639K rows of parquet reads, this one-time copy
saves significant time during scoring. The file is only 117 MB so the copy takes
seconds.

### Cell 6 — Section Header (Markdown)

"Step 2 — Load Data"

### Cell 7 — Load and Filter Data

**What:** Reads the parquet file into a pandas DataFrame, then removes
low-quality rows:

- Deleted/removed text (`[deleted]`, `[removed]`, empty)
- Very short text (< 10 characters)
- Deleted/bot authors

**Why:** These rows cannot be meaningfully scored by FinBERT. A comment that
says `[deleted]` has no sentiment to analyze. Filtering here matches the same
quality filter used in the dictionary scorer so results are comparable.

**Result:** ~639K scorable rows.

### Cell 8 — Section Header (Markdown)

"Step 3 — Load FinBERT Model"

### Cell 9 — Load FinBERT

**What:** Downloads and loads `ProsusAI/finbert` — a BERT model fine-tuned on
the Financial PhraseBank dataset for financial sentiment classification. Moves
it to the GPU and sets it to evaluation mode (no gradient tracking).

**Why:** FinBERT is the gold standard for financial text sentiment per Huang et
al. (2023, Contemporary Accounting Research). It classifies text into three
categories:

- **Positive:** optimistic/bullish language
- **Negative:** pessimistic/bearish language
- **Neutral:** factual/non-opinionated language

We use it as the **primary scoring method** because it's the most defensible
choice for an accounting journal.

### Cell 10 — Quick Test

**What:** Runs 5 sample sentences through FinBERT and prints the probability
scores for each label.

**Why:** Sanity check before processing 639K rows. If "The CEO delivered record
earnings" doesn't score positive, something is wrong with the model loading.
This catches errors early before committing to a 2-hour run.

### Cell 11 — Section Header (Markdown)

"Step 4 — Batch Scoring" — explains the checkpointing strategy.

### Cell 12 — Initialize Scoring Loop

**What:** Sets up batch size (32), checkpoint interval (every 50K rows), and
checks for a partial checkpoint from a previous interrupted session.

**Why:**

- **Batch size 32:** Fits comfortably in T4 GPU memory (16 GB). Larger batches
  are faster but risk out-of-memory errors on longer texts.
- **Checkpoint every 50K:** Colab sessions can disconnect (90-minute idle
  timeout, 12-hour max runtime). If you've scored 400K rows and Colab dies, you
  don't want to start over. The checkpoint saves progress to Google Drive (which
  persists across sessions).
- **Resume logic:** If a checkpoint file exists, it loads the partial results
  and continues from where it stopped.

### Cell 13 — Main Scoring Loop

**What:** The core processing loop:

1. Takes 32 comments at a time
2. Truncates text to 2000 characters (FinBERT's tokenizer handles the rest with
   512-token max)
3. Tokenizes the batch (converts text to numbers the model understands)
4. Runs FinBERT inference with `torch.no_grad()` (no backpropagation needed —
   inference only)
5. Converts logits to probabilities with softmax
6. Stores positive/negative/neutral probabilities for each comment
7. Logs progress every 10K rows (rate, ETA)
8. Saves checkpoint to Drive every 50K rows

**Why each design choice:**

- `torch.no_grad()`: We're not training, just scoring. Disabling gradient
  computation uses ~50% less GPU memory and is faster.
- `max_length=512`: FinBERT's maximum input. Longer texts are truncated — the
  first 512 tokens usually contain enough signal for sentiment.
- `[:2000]` pre-truncation: Prevents the tokenizer from wasting time on
  extremely long texts (some Reddit posts are 10K+ characters).
- Progress logging: So you know it's working and can estimate when it'll finish.

**Runtime:** ~1.5-2.5 hours on T4 GPU for 639K rows.

### Cell 14 — Section Header (Markdown)

"Step 5 — Attach Scores & Derive Traits"

### Cell 15 — Derive Sentiment Scores

**What:** Attaches the three probability scores to the DataFrame and computes
derived columns:

- `finbert_label`: The winning label (highest probability)
- `finbert_sentiment`: `positive - negative` (range -1 to +1). This is the main
  score used in the paper.
- `finbert_confidence`: The highest probability. High confidence = model is
  sure.

**Why:** The raw probabilities (0.7 positive, 0.2 negative, 0.1 neutral) are
useful, but for aggregation we need a single sentiment number.
`positive - negative` gives a clean -1 to +1 scale where:

- +1 = unanimously positive
- 0 = neutral or mixed
- -1 = unanimously negative

This is the **crowd perception score** that gets compared against earnings call
scores in the paper's discrepancy formula.

### Cell 16 — Sanity Check: Extreme Samples

**What:** Shows the 5 most positive, 5 most negative, and 5 most neutral
comments according to FinBERT.

**Why:** Eyeball validation. If the most negative comment is actually positive
(or vice versa), the model is broken. This catches systematic errors.

### Cell 17 — Section Header (Markdown)

"Step 6 — CEO-Year Aggregates"

### Cell 18 — CEO-Year Aggregation

**What:** Groups all comments by CEO and year, computing:

- Mean/median/std of sentiment score
- Percentage of comments labeled positive/negative/neutral
- Average model confidence

**Why:** The paper's unit of analysis is **CEO-quarter** (or CEO-year). We need
aggregate scores, not per-comment scores. The mean sentiment across all Reddit
comments mentioning "Tim Cook" in 2023 becomes that CEO-year's crowd perception
score.

### Cell 19 — CEO Rankings

**What:** Shows the 15 most negative and 15 most positive CEOs (minimum 100
mentions) by average FinBERT sentiment.

**Why:** Face validity check. Are the CEOs known for scandals (Stumpf, Equifax
CEOs) scoring negative? Are respected CEOs (Buffett, Lisa Su) scoring positive?
If these rankings don't match common knowledge, the model may not work on Reddit
text.

### Cell 20 — Elon Musk Over Time

**What:** Shows Musk's average FinBERT sentiment by year with a visual bar
chart.

**Why:** Musk is the most-discussed CEO (246K mentions) with a well-documented
public perception shift (positive early on, increasingly negative from
2018-2025). If FinBERT captures this trajectory, it validates that the model
detects real sentiment changes over time, not just noise.

### Cell 21 — Section Header (Markdown)

"Step 7 — Save Results"

### Cell 22 — Save FinBERT Results to Drive

**What:** Saves the scored DataFrame as a parquet file and CEO-year aggregates
as CSV to Google Drive. Removes the checkpoint file since scoring is complete.

**Why:** Google Drive persists across Colab sessions. If you close Colab, the
results are safe on Drive. Parquet for the full dataset (efficient), CSV for
aggregates (easy to open in Excel/Sheets).

### Cell 23 — Download CSV

**What:** Triggers a browser download of the CEO-year aggregate CSV.

**Why:** Quick way to get the summary data onto your local machine without
manually navigating Drive.

---

## Part 2 — Twitter-RoBERTa (Social Media Sentiment)

### Cell 24 — Section Header (Markdown)

Explains why we run a second model: FinBERT was trained on formal financial
text, but Reddit is informal. Twitter-RoBERTa was trained on 124M tweets and
handles slang, sarcasm, and casual language better.

### Cell 25 — Load Twitter-RoBERTa

**What:** Frees GPU memory from FinBERT (`del model`), then loads
`cardiffnlp/twitter-roberta-base-sentiment-latest`. Runs the same quick test.

**Why:** The T4 GPU has 16 GB memory. Both models are ~400 MB, so there's room,
but freeing FinBERT first is cleaner. The quick test with Reddit-style sentences
("lol this dude is delusional") shows whether RoBERTa handles informal text
better than FinBERT.

**Label mapping difference:** Twitter-RoBERTa uses
`[negative, neutral, positive]` (index 0, 1, 2), while FinBERT uses
`[positive, negative, neutral]` (index 0, 1, 2). The code handles this
correctly.

### Cell 26 — RoBERTa Batch Scoring

**What:** Same loop as FinBERT Cell 13, but using the Twitter-RoBERTa model.
Separate checkpoint directory so both models' progress is independent.

**Why:** Same reasoning — 639K rows, needs batching and checkpointing. Runs
another ~1.5-2.5 hours.

### Cell 27 — Attach RoBERTa Scores

**What:** Same as Cell 15 but for RoBERTa scores. Derives
`roberta_sentiment = positive - negative`.

**Why:** Now the DataFrame has both models' scores side by side for every
comment.

---

## Part 3 — Cross-Model Comparison

### Cell 28 — Section Header (Markdown)

"Do FinBERT and Twitter-RoBERTa agree?"

### Cell 29 — Comment-Level Agreement

**What:** Computes:

- **Pearson correlation:** Linear relationship between the two models' sentiment
  scores
- **Spearman correlation:** Rank-order agreement (more robust to outliers)
- **Label agreement:** What % of comments get the same label from both models
- **Cross-tabulation:** How many comments FinBERT calls positive but RoBERTa
  calls negative, etc.

**Why this matters for the paper:** If both models produce similar scores
(correlation > 0.6), it means the sentiment signal is real and not an artifact
of one model's training data. If they disagree, the disagreements reveal where
formal vs. informal text interpretation differs — publishable finding either
way.

### Cell 30 — CEO-Level Agreement

**What:** Aggregates to the CEO level and computes:

- **Spearman rank correlation:** Do both models rank CEOs in the same order?
- **Biggest disagreements:** Which CEOs do the models disagree about most?
- **Consensus negatives/positives:** CEOs both models agree are most
  negative/positive

**Why this is the most important comparison:** Comment-level disagreement is
expected (models interpret individual sentences differently). But if both models
agree that "John Stumpf is perceived negatively" and "Lisa Su is perceived
positively," the CEO-level signal is robust. This is what goes into the paper's
regressions.

---

## Save & Summary

### Cell 31 — Section Header (Markdown)

"Step 9 — Save All Results"

### Cell 32 — Save Combined Results

**What:** Saves one parquet file with ALL scores (FinBERT + RoBERTa) and one CSV
with CEO-year aggregates from both models. Cleans up both checkpoint
directories.

**Why:** One file with everything is easier to work with downstream. The
CEO-year CSV has columns like `finbert_sentiment_mean` and
`roberta_sentiment_mean` side by side — ready for the paper's analysis.

### Final Cell — Summary Statistics

**What:** Prints a complete summary: row counts, label distributions for both
models, cross-model correlation, and next steps.

**Why:** Quick reference after a 4-hour run. Confirms everything completed and
tells you what to do next.

---

## Output Files

| File                                  | Location     | Contents                           |
| ------------------------------------- | ------------ | ---------------------------------- |
| `ceo_mentions_finbert_scored.parquet` | Google Drive | 639K rows with FinBERT scores only |
| `ceo_mentions_dual_scored.parquet`    | Google Drive | 639K rows with both models' scores |
| `ceo_year_finbert_scores.csv`         | Google Drive | CEO-year aggregates, FinBERT only  |
| `ceo_year_dual_scores.csv`            | Google Drive | CEO-year aggregates, both models   |

---

## After Running

1. Download `ceo_mentions_dual_scored.parquet` from Drive to your local
   `data/reference/` directory
2. Download `ceo_year_dual_scores.csv` to `data/reports/`
3. Next: compare transformer scores vs dictionary scores (3-way validation)
4. Then: LLM labeling of 5-10K sample for ground truth
5. Then: score earnings call transcripts with the same FinBERT model
6. Finally: compute
   `self_presentation_discrepancy = CEO_self_score - crowd_perception_score` per
   CEO-quarter
