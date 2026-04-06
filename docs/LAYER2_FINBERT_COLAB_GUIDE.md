# Layer 2 Pass 2: FinBERT + Twitter-RoBERTa Scoring — Colab Guide

Step-by-step explanation of every cell in
`notebooks/corpus_analysis/03_finbert_scoring_colab.ipynb`.

This notebook is the heart of Layer 2. It takes the 639K cleaned Reddit comments
about S&P 500 CEOs (produced by Layer 1) and transforms raw text into numerical
sentiment scores. These scores become the **crowd perception** side of the
paper's self-presentation discrepancy formula.

---

## Prerequisites

Before opening the notebook:

1. **Upload** `data/filtered_clean/ceo_mentions_clean.parquet` (117 MB) to
   Google Drive at `My Drive/ceo_reddit/data/`
2. **Open** the notebook in Google Colab (from GitHub or upload directly)
3. **Set runtime:** Runtime > Change runtime type > **T4 GPU**

**Why Google Colab?** FinBERT is a transformer model with 110 million
parameters. Running inference (feeding text through the model to get
predictions) on 639K comments requires a GPU to finish in a reasonable time.
Google Colab provides a free NVIDIA T4 GPU with 16 GB of VRAM. Without a GPU,
this same task would take 40-80 hours on a CPU; with the T4, it takes 1-3 hours.

**Why Google Drive?** Colab sessions are temporary — when the session ends
(after 12 hours max, or 90 minutes of idle), all files on the Colab virtual
machine are deleted. Google Drive persists. By reading input from Drive and
saving output back to Drive, your data survives session disconnections.

---

## What Are These Models?

### FinBERT (ProsusAI/finbert)

FinBERT is BERT (a 110M-parameter transformer language model created by Google)
that has been additionally trained ("fine-tuned") on the Financial PhraseBank
dataset — 4,840 sentences from English financial news articles that were
hand-labeled by 16 finance researchers as positive, negative, or neutral.

**What it's good at:** Formal financial language. Sentences like "The company
reported a 15% increase in quarterly revenue" or "Management expects continued
headwinds in the coming fiscal year." These are the kinds of sentences it was
trained on.

**What it struggles with:** Informal Reddit language. Sentences like "lol this
dude is delusional, company is tanking and he's out here buying yachts" or "Lisa
Su is the GOAT, AMD to the moon." FinBERT has never seen this kind of text
during training.

**Why we use it anyway:** Huang et al. (2023, Contemporary Accounting Research)
established FinBERT as the gold standard for financial sentiment analysis. It
"substantially outperforms" Loughran-McDonald dictionaries and all other ML
methods they tested. Using FinBERT makes our methodology defensible in an
accounting journal — reviewers expect it.

### Twitter-RoBERTa (cardiffnlp/twitter-roberta-base-sentiment-latest)

This is RoBERTa (a 125M-parameter improvement on BERT by Facebook) fine-tuned on
approximately 124 million tweets for sentiment analysis. It classifies text as
positive, negative, or neutral, just like FinBERT.

**What it's good at:** Informal, short, opinionated text. Slang, abbreviations,
sarcasm, emotional language — the kinds of things people write on Twitter and
Reddit. It has seen "lmao" and "this is fire" and "absolute garbage" millions of
times during training.

**What it struggles with:** Domain-specific financial vocabulary. It may not
distinguish between "the company missed earnings" (financially negative) and "I
missed the earnings call" (neutral). Financial context is not its strength.

**Why we use it alongside FinBERT:** Reddit text is closer to tweets than to SEC
filings. By running both models and comparing their outputs, we can assess
whether the sentiment signal is robust across different model architectures and
training domains. If both models agree that John Stumpf (Wells Fargo fake
accounts scandal) is perceived negatively by Reddit, that's stronger evidence
than either model alone. The comparison itself is a publishable finding about
construct validity.

---

## Part 1 — FinBERT (Financial Sentiment)

### Cell 0 — Title & Purpose (Markdown)

Describes the notebook's purpose: score 639K Reddit comments with two models.
Lists both models, explains why we use two (cross-validation of the sentiment
signal), and states the prerequisites (upload data, set GPU runtime).

### Cell 1 — Section Header (Markdown)

"Step 1 — Setup & GPU Check"

### Cell 2 — GPU Verification

**What it does:** Imports PyTorch, checks if a CUDA-compatible GPU is available,
and prints the GPU name and memory size. If no GPU is found, it prints a
warning.

**Why this matters:** The entire notebook depends on having a GPU. FinBERT
inference on a single CPU core processes about 2-5 comments per second — at that
rate, 639K comments would take 1.5-3.5 days. On a T4 GPU, the same work takes
1-3 hours because the GPU can process all 32 comments in a batch simultaneously
(parallel computation on thousands of CUDA cores). If someone accidentally runs
this notebook without selecting a GPU runtime, this cell catches the mistake
immediately instead of letting them discover it 10 hours into a painfully slow
run.

**What the output should look like:** `GPU: Tesla T4 (15.0 GB)` or similar. If
you see the WARNING message, go to Runtime > Change runtime type > T4 GPU and
restart.

### Cell 3 — Install Dependencies

**What it does:** Installs two Python packages:

- `transformers`: HuggingFace's library for loading and running pre-trained
  language models like FinBERT. This provides the `AutoTokenizer` (converts text
  to numbers) and `AutoModelForSequenceClassification` (the actual neural
  network).
- `fastparquet`: A lightweight library for reading and writing Parquet files. We
  chose this over PyArrow because it's smaller, installs faster, and avoids
  schema inference issues we hit with hive-partitioned data.

**Why not already installed:** Google Colab comes with PyTorch, NumPy, and
Pandas pre-installed, but not HuggingFace Transformers or fastparquet. The `-q`
flag suppresses verbose installation output to keep the notebook clean.

### Cell 4 — Mount Google Drive & Verify Data

**What it does:** Three things:

1. Calls `drive.mount()` which triggers a Google authentication popup. You click
   "Allow" and Colab gains read/write access to your Drive.
2. Sets up the file path where we expect the input data:
   `/content/drive/MyDrive/ceo_reddit/data/ceo_mentions_clean.parquet`
3. Asserts the file exists. If it doesn't, the cell fails with a clear error
   message telling you exactly where to upload the file.

**Why we mount Drive instead of uploading directly:** The scored output file
will be ~200-300 MB. If we uploaded input via `files.upload()` and downloaded
output via `files.download()`, both would live on Colab's temporary disk and
vanish when the session ends. With Drive mounted, the output is automatically
persisted. Also, if the session disconnects and we reconnect, the checkpoint
files on Drive let us resume without re-uploading anything.

**Why the assert:** Failing fast with a helpful message is better than a cryptic
`FileNotFoundError` three cells later. This is a boundary check — validate input
before doing any work.

### Cell 5 — Copy Data to Local Colab Disk

**What it does:** Copies the 117 MB parquet file from Google Drive to Colab's
local `/content/` directory.

**Why not read directly from Drive:** Google Drive is mounted via FUSE
(Filesystem in Userspace), which means every file read goes over a network
connection to Google's servers. For sequential reads (like loading a parquet
file once), this is fine. But during scoring, we access the DataFrame
repeatedly, and Pandas may trigger multiple I/O operations. Colab's local disk
is an SSD directly attached to the virtual machine — 10-50x faster for random
access. Copying 117 MB takes ~2 seconds and saves cumulative minutes during the
scoring loop.

**The `if not exists` guard:** If you re-run this cell (e.g., after a session
reconnect), it skips the copy if the file is already there. Avoids unnecessary
work.

### Cell 6 — Section Header (Markdown)

"Step 2 — Load Data"

### Cell 7 — Load and Filter Data

**What it does:** Reads the parquet file into a Pandas DataFrame (639K+ rows),
then applies quality filters to remove unscorable rows:

- **Deleted/removed text:** Reddit replaces comment content with `[deleted]` or
  `[removed]` when users or moderators remove posts. These strings contain no
  sentiment — FinBERT would score them as neutral, which would dilute real
  signals.
- **Very short text (< 10 characters):** Comments like "Elon Musk" or "lol" are
  too short for meaningful sentiment analysis. FinBERT needs some context to
  classify — a bare name has no sentiment.
- **Deleted/bot authors:** Comments by `[deleted]` users (account was deleted)
  or `AutoModerator` (a bot) don't represent genuine crowd perception. Bot
  comments are template text, not opinions.

**Why these exact filters:** These are the same filters applied in the
dictionary scorer (`src/ceo_reddit/scoring/dictionary_scorer.py`). Using
identical filters ensures that both scoring methods operate on the same set of
comments, making their outputs directly comparable.

**Result:** ~639,493 rows ready for scoring.

### Cell 8 — Section Header (Markdown)

"Step 3 — Load FinBERT Model"

### Cell 9 — Load FinBERT onto GPU

**What it does:** Four things:

1. `AutoTokenizer.from_pretrained("ProsusAI/finbert")`: Downloads FinBERT's
   tokenizer — a vocabulary mapping that converts English text into numerical
   token IDs. For example, "earnings" might become token 7523. The tokenizer
   also handles padding (making all texts in a batch the same length) and
   truncation (cutting texts longer than 512 tokens).

2. `AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")`:
   Downloads the actual neural network — 110 million parameters (weights) that
   were learned during training. The model takes token IDs as input and outputs
   three numbers (logits) representing the score for positive, negative, and
   neutral.

3. `model.to(device)`: Moves the model's 110M parameters from CPU RAM to GPU
   VRAM. This is essential — if the model stays on CPU, inference will be slow
   even with a GPU available.

4. `model.eval()`: Switches the model from training mode to evaluation mode. In
   training mode, layers like Dropout randomly zero out some neurons (a
   regularization technique). In eval mode, all neurons are active, giving
   deterministic, consistent predictions. Since we're scoring, not training, we
   always want eval mode.

**FinBERT's label mapping:** The model outputs three values in the order
`[positive, negative, neutral]`. This is important because different models use
different orderings — Twitter-RoBERTa uses `[negative, neutral, positive]`. The
code handles this mapping correctly for each model.

### Cell 10 — Quick Test with Sample Sentences

**What it does:** Feeds 5 hand-picked sentences through FinBERT and displays the
probability distribution for each:

- "The CEO delivered record earnings..." (should be positive)
- "This CEO is destroying the company..." (should be negative)
- "Tim Cook announced the new iPhone..." (should be neutral)
- "Elon Musk is delusional, Tesla is way overvalued." (should be negative)
- "Warren Buffett is the greatest investor..." (should be positive)

**Why this matters:** This is a smoke test. If FinBERT classifies "record
earnings" as negative or "destroying the company" as positive, something went
wrong during model loading — maybe the wrong model was downloaded, or the label
mapping is incorrect. Catching this here saves you from running a 2-hour scoring
loop that produces garbage results.

**What to look for:** Each sentence should have its highest probability in the
expected column. The probabilities should be reasonably confident (>0.5 for the
top label). If the model seems uncertain on everything (e.g., 0.35/0.33/0.32),
that's a red flag.

### Cell 11 — Section Header (Markdown)

"Step 4 — Batch Scoring" — explains the checkpointing strategy.

### Cell 12 — Initialize the Scoring Loop

**What it does:** Sets up the scoring infrastructure:

- `BATCH_SIZE = 32`: Process 32 comments at once.
- `CHECKPOINT_EVERY = 50_000`: Save progress every 50K rows.
- Checks for an existing checkpoint file from a previous interrupted session.
- If a checkpoint exists, loads the partial results and sets `start_idx` to
  resume from where it left off.
- If no checkpoint, initializes empty result lists.

**Why batch size 32:** This is a balance between speed and memory. Each comment
gets tokenized into up to 512 tokens, and each token has a 768-dimensional
embedding. A batch of 32 × 512 × 768 = ~12.5 million floating-point numbers,
plus intermediate computations. On a T4 with 16 GB VRAM, batch size 32 fits
comfortably even with longer texts. Batch size 64 would be ~20% faster but risks
out-of-memory errors on batches where many comments are long. 32 is safe.

**Why checkpoint every 50K:** Google Colab free tier disconnects after ~90
minutes of browser inactivity or 12 hours total. At ~200 rows/sec, 50K rows
takes about 4 minutes. So the worst case on disconnection is losing 4 minutes of
work. We save to Google Drive (not Colab local disk) because Drive persists
across sessions. When you reconnect and re-run the notebook, it detects the
checkpoint and resumes.

**The resume logic in detail:** The checkpoint file stores the DataFrame with
scores for all rows processed so far. On resume:

1. Load the checkpoint parquet
2. Count how many rows are already scored
3. Pre-fill the result arrays from the checkpoint
4. Set `start_idx` so the scoring loop skips already-completed rows This means
   you never re-score the same comment twice.

### Cell 13 — Main Scoring Loop

**What it does:** This is where the actual work happens. For each batch of 32
comments:

1. **Extract text:** Pull the raw comment text from the DataFrame.
2. **Pre-truncate to 2000 characters:** Some Reddit comments are extremely long
   (we saw texts up to 10,000 characters). The tokenizer will truncate to 512
   tokens anyway, but tokenizing a 10,000-character string just to throw away
   90% of the tokens wastes time. Pre-truncating to 2000 characters (roughly 500
   tokens) means the tokenizer does less unnecessary work.
3. **Tokenize:** Convert text to token IDs, pad shorter texts in the batch to
   match the longest one, truncate anything beyond 512 tokens. The result is a
   tensor of shape `[32, sequence_length]` where sequence_length <= 512.
4. **GPU inference:** Move the tokenized input to GPU, pass it through the
   model. The model outputs "logits" — raw, unnormalized scores for each class.
5. **Softmax:** Convert logits to probabilities that sum to 1.0. For example,
   logits `[2.1, -0.3, 0.5]` might become probabilities `[0.78, 0.07, 0.15]`.
6. **Move to CPU:** Transfer results back from GPU to CPU RAM and convert to
   Python lists for storage.
7. **Progress logging:** Every 10K rows, print current progress, processing
   speed (rows/sec), and estimated time remaining.
8. **Checkpoint:** Every 50K rows, save all results so far to Drive.

**Why `torch.no_grad()`:** During training, PyTorch tracks every mathematical
operation so it can compute gradients (derivatives used to update model
weights). This tracking uses significant memory and computation. Since we're
only doing inference (forward pass, no learning), we wrap the computation in
`torch.no_grad()` to disable gradient tracking. This reduces GPU memory usage by
~40-50% and speeds up computation by ~20%.

**Why `max_length=512`:** BERT-based models have a fixed maximum input length of
512 tokens (set during pre-training). A "token" is roughly a word or word piece
— "understanding" might become ["under", "##standing"]. 512 tokens is
approximately 350-400 words. For Reddit comments, the median length is 30 words,
so most comments fit entirely. For the rare long comments, the first 512 tokens
usually contain the main argument and sentiment — truncation from the end is
acceptable.

**Runtime:** At ~200-300 rows/sec on a T4, 639K rows takes approximately 35-55
minutes. The actual speed depends on text lengths in each batch (shorter texts =
faster, since there's less padding).

### Cell 14 — Section Header (Markdown)

"Step 5 — Attach Scores & Derive Traits"

### Cell 15 — Derive Sentiment Scores from Probabilities

**What it does:** Takes the three probability arrays (positive, negative,
neutral) and attaches them as new columns to the DataFrame. Then computes three
derived columns:

- **`finbert_label`**: The class with the highest probability. If a comment has
  probabilities `[positive=0.78, negative=0.07, neutral=0.15]`, the label is
  "positive." This is a discrete classification.

- **`finbert_sentiment`**: `positive_prob - negative_prob`. This gives a
  continuous score from -1 to +1. A comment with probabilities
  `[pos=0.78, neg=0.07, neu=0.15]` gets sentiment `+0.71`. A comment with
  `[pos=0.05, neg=0.88, neu=0.07]` gets sentiment `-0.83`. A purely neutral
  comment gets `~0.0`.

- **`finbert_confidence`**: The maximum probability across all three classes.
  High confidence (>0.8) means the model is sure. Low confidence (0.35-0.45)
  means the model is uncertain — the comment might be ambiguous or use language
  the model hasn't seen before.

**Why `positive - negative` as the sentiment score:** We need a single number
per comment that captures the direction and intensity of crowd sentiment. The
alternatives are:

- Just the positive probability: Loses negative information
- The label alone (pos/neg/neu): Loses intensity (barely positive and extremely
  positive both become "positive")
- `positive - negative`: Captures both direction and intensity on a clean scale.
  A comment the model is 90% sure is negative gets -0.8, while one it's 55% sure
  is negative gets -0.1. This distinction matters when we aggregate to CEO-year
  level.

**Connection to the paper:** This `finbert_sentiment` score, averaged across all
comments about a CEO in a given time window, becomes the **crowd perception
score**. The paper then computes:
`discrepancy = CEO_self_score (from earnings calls) - crowd_perception_score (from Reddit)`

### Cell 16 — Sanity Check: Show Extreme Examples

**What it does:** Displays the 5 comments with the highest sentiment scores
(most positive), the 5 with the lowest (most negative), and the 5 with the
highest neutral probability.

**Why this matters:** Numbers alone don't prove the model is working correctly.
You need to read actual examples and verify they make sense:

- Does the most positive comment actually express positive sentiment about a
  CEO?
- Does the most negative comment actually express negative sentiment?
- Are the neutral comments genuinely factual/non-opinionated?

If the most positive comment is actually sarcastic ("What a GREAT job destroying
shareholder value"), that's a sign FinBERT is missing sarcasm — important to
note in the paper's limitations section.

### Cell 17 — Section Header (Markdown)

"Step 6 — CEO-Year Aggregates"

### Cell 18 — Aggregate to CEO-Year Level

**What it does:** Groups all comments by `(CEO, company, year)` and computes
aggregate statistics:

- `mention_count`: Total comments about this CEO in this year
- `finbert_sentiment_mean`: Average sentiment (the main score for the paper)
- `finbert_sentiment_median`: Median sentiment (more robust to outliers than
  mean)
- `finbert_sentiment_std`: Standard deviation (measures how polarizing the CEO
  is — high std means some people love them and others hate them)
- `pct_positive/negative/neutral`: What fraction of comments fall into each
  category
- `avg_confidence`: How confident the model was on average (lower confidence for
  a CEO might mean their mentions use unusual language)

**Why CEO-year and not CEO-quarter:** The Reddit data is sparse for many CEOs. A
CEO with 80 annual mentions has only ~20 per quarter — right at the minimum
threshold. Annual aggregation gives more stable estimates. The paper can use
quarterly windows for high-volume CEOs (Musk, Cook, Buffett) and annual for
others. The per-comment scores are preserved so you can re-aggregate at any
granularity later.

**Why median alongside mean:** Reddit comment sentiment is typically skewed —
most comments are mildly negative with occasional extremely negative outliers
(scandal-related). The mean gets pulled by outliers; the median is more robust.
Reporting both lets the paper discuss which is more appropriate.

### Cell 19 — CEO Sentiment Rankings

**What it does:** Filters to CEOs with 100+ mentions (to ensure stable
estimates), then shows the 15 most negative and 15 most positive CEOs.

**Why this is a face validity test:** The research community expects that a
sentiment analysis tool, when applied to text about known entities, produces
results that align with common knowledge. If John Stumpf (Wells Fargo fake
accounts scandal, 2016) doesn't appear among the most negative, something is
wrong. If Warren Buffett (widely admired) appears among the most negative,
something is wrong. This doesn't prove the model is correct on every comment,
but it proves the aggregate signal is meaningful.

**Why minimum 100 mentions:** A CEO with only 5 mentions could have extreme
sentiment by chance (5 angry comments about a minor news story). 100 mentions
provides a more stable estimate. This threshold can be adjusted — the paper uses
20 as the absolute minimum, but for this ranking display, 100 gives cleaner
results.

### Cell 20 — Elon Musk Sentiment Trajectory

**What it does:** Shows Musk's average FinBERT sentiment for each year alongside
his mention count.

**Why Musk specifically:** He's the ideal validation case because:

1. **Highest volume:** 246K mentions — the most statistically robust signal
2. **Known trajectory:** Broadly positive before 2018, turning negative after
   the "pedo guy" tweet, SEC settlement, and erratic behavior, then sharply
   negative after the 2022 Twitter acquisition and subsequent controversies
3. **Public consensus:** There's no ambiguity about the direction of his
   perception change — it's documented in countless news articles

If FinBERT's year-by-year scores don't show this decline, the model isn't
capturing real sentiment shifts in Reddit text. If it does, we have strong
evidence that the scoring methodology works.

### Cell 21 — Section Header (Markdown)

"Step 7 — Save Results"

### Cell 22 — Save FinBERT Results to Google Drive

**What it does:** Three things:

1. Saves the full scored DataFrame (639K rows with FinBERT probability columns)
   as a compressed Parquet file on Drive. Zstd compression typically achieves
   3-5x reduction, so the ~200 MB DataFrame becomes a ~60-80 MB file.
2. Saves the CEO-year aggregate table as a CSV file. CSV is less efficient than
   Parquet but can be opened directly in Excel or Google Sheets for quick
   review.
3. Deletes the checkpoint file. Since scoring is complete, the checkpoint is no
   longer needed. Leaving it would cause confusion on the next run (the resume
   logic would think scoring was interrupted).

**Why save before running the second model:** If something goes wrong during the
Twitter-RoBERTa scoring (e.g., Colab disconnects), we don't want to lose the
FinBERT results. By saving now, the FinBERT output is safely on Drive regardless
of what happens next.

### Cell 23 — Download CEO-Year CSV

**What it does:** Triggers a browser download of the CEO-year aggregate CSV to
your local machine.

**Why:** Convenience. The CSV is small (~200 KB) and you might want to explore
it immediately in Excel without navigating Drive. The full parquet file (too
large for Excel) stays on Drive for programmatic access later.

---

## Part 2 — Twitter-RoBERTa (Social Media Sentiment)

### Cell 24 — Section Header (Markdown)

Explains the rationale for a second model: FinBERT was trained on formal
financial text, but Reddit text is informal. Running a second model trained on
social media text provides cross-validation. If both models agree on CEO
rankings, the signal is robust across text domains.

### Cell 25 — Free GPU Memory and Load Twitter-RoBERTa

**What it does:**

1. **`del model, tokenizer`**: Removes the FinBERT model from memory. Python's
   garbage collector eventually frees the RAM, but `del` makes it eligible
   immediately.
2. **`torch.cuda.empty_cache()`**: Tells PyTorch to release all unused GPU
   memory back to CUDA. Without this, the 440 MB of FinBERT weights could still
   occupy GPU VRAM even after `del`, potentially causing an out-of-memory error
   when loading the second model.
3. **Loads Twitter-RoBERTa** using the same HuggingFace API. The model is
   automatically downloaded from HuggingFace Hub (~500 MB).
4. **Quick test** with Reddit-style sentences including slang and informal
   language. This lets you compare how Twitter-RoBERTa handles "lol this dude is
   delusional" versus how FinBERT handled the same kind of text.

**Label mapping difference:** This is a critical implementation detail. FinBERT
outputs `[positive, negative, neutral]` at indices `[0, 1, 2]`. Twitter-RoBERTa
outputs `[negative, neutral, positive]` at indices `[0, 1, 2]`. The code uses
separate `LABELS` and `ROBERTA_LABELS` arrays to handle this correctly. Getting
this wrong would flip all positive and negative scores.

### Cell 26 — RoBERTa Batch Scoring Loop

**What it does:** Identical structure to FinBERT's Cell 13, but:

- Uses `tokenizer_rob` and `model_rob` instead of the FinBERT versions
- Saves checkpoints to a separate directory (`roberta_checkpoints/`) so the two
  models' progress is independent
- Stores results in `rob_negative`, `rob_neutral`, `rob_positive` arrays

**Why separate checkpoints:** If FinBERT completed but RoBERTa got interrupted,
you want to resume only RoBERTa without re-running FinBERT. Separate checkpoint
directories make this possible.

### Cell 27 — Attach RoBERTa Scores and Derive Sentiment

**What it does:** Same as Cell 15 but for RoBERTa. Attaches the three
probability columns and computes:

- `roberta_label`: The class with highest probability
- `roberta_sentiment`: `positive - negative` (same formula as FinBERT)

**After this cell:** The DataFrame has 6 score columns (3 per model) plus 2
derived sentiment columns and 2 labels. Every comment now has been evaluated by
both models, ready for comparison.

---

## Part 3 — Cross-Model Comparison

### Cell 28 — Section Header (Markdown)

"Do FinBERT and Twitter-RoBERTa agree?" This is the key question for construct
validity.

### Cell 29 — Comment-Level Agreement Statistics

**What it does:** Computes four metrics:

- **Pearson correlation:** Measures the linear relationship between
  `finbert_sentiment` and `roberta_sentiment` across all 639K comments. Ranges
  from -1 (perfect disagreement) to +1 (perfect agreement). Above 0.5 is good;
  above 0.7 is strong.

- **Spearman rank correlation:** Instead of comparing raw scores, this ranks all
  comments by sentiment for each model and then correlates the ranks. More
  robust to outliers and non-linear relationships. If Spearman is high but
  Pearson is lower, the models agree on ordering but disagree on magnitude.

- **Label agreement:** Simple percentage — what fraction of comments receive the
  same discrete label (positive, negative, or neutral) from both models.
  Typically 40-60% for different models on the same data (they disagree most on
  borderline cases).

- **Cross-tabulation:** A 3x3 matrix showing exactly where models disagree. For
  example: "Of the 200K comments FinBERT calls neutral, how many does RoBERTa
  call negative?" This reveals systematic biases — e.g., FinBERT might classify
  informal negative language as neutral because it wasn't in its training data.

**Why this matters for the paper:** Reviewers will ask: "How do you know your
sentiment scores are real and not artifacts of the model?" Cross-model agreement
is the answer. If two models trained on completely different data (financial
news vs. 124M tweets) both say "Reddit perceives this CEO negatively," the
signal is unlikely to be a model artifact. The specific correlation numbers and
cross-tabulation go in the paper's methodology or appendix.

### Cell 30 — CEO-Level Agreement (The Most Important Cell)

**What it does:** Aggregates sentiment to the CEO level and compares:

- **Spearman rank correlation at CEO level:** The key number. If this is high
  (>0.7), both models rank CEOs in roughly the same order from most negative to
  most positive. This means the CEO-level crowd perception scores — which go
  directly into the paper's regressions — are robust to model choice.

- **Biggest disagreements:** Shows CEOs where the two models give the most
  different sentiment scores. These are interesting cases to investigate — they
  might be CEOs discussed primarily in slang or sarcasm (where the models
  interpret text differently) or CEOs with mixed perception (some people love
  them, others hate them, and the models weight the ambiguity differently).

- **Consensus negatives and positives:** CEOs that both models agree are most
  negative or most positive. These are the most robust data points in the study
  — if you had to pick a smaller, higher-confidence sample for robustness
  checks, these would be it.

**Why CEO-level matters more than comment-level:** The paper doesn't use
per-comment scores in regressions — it uses CEO-quarter or CEO-year aggregates.
Two models might disagree on 40% of individual comments but still produce nearly
identical CEO rankings because the disagreements cancel out in aggregation. A
comment that FinBERT calls neutral but RoBERTa calls slightly negative has
minimal impact on a CEO's average across 5,000 comments. The CEO-level
correlation is what determines whether model choice affects the paper's
conclusions.

---

## Save & Summary

### Cell 31 — Section Header (Markdown)

"Step 9 — Save All Results"

### Cell 32 — Save Combined Results from Both Models

**What it does:**

1. Saves `ceo_mentions_dual_scored.parquet` — the full 639K-row DataFrame with
   all columns from both models. This is the primary output file (~200-300 MB on
   Drive). Any downstream analysis (earnings call comparison, discrepancy
   computation, LLM validation) reads from this file.
2. Saves `ceo_year_dual_scores.csv` — CEO-year aggregates with both models'
   scores side by side. Columns include `finbert_sentiment_mean`,
   `roberta_sentiment_mean`, `finbert_pct_negative`, `roberta_pct_negative`,
   etc. This is the file you'll likely open first to explore results.
3. Deletes both checkpoint directories now that scoring is complete.
4. Triggers a browser download of the CEO-year CSV.

### Final Cell — Summary Statistics

**What it does:** Prints a comprehensive summary of the entire notebook run:
total comments scored, unique CEOs, label distributions for both models,
cross-model correlation, label agreement percentage, output file locations, and
the next steps in the pipeline.

**Why:** After a 3-5 hour run, you want a single summary you can screenshot or
copy-paste. This cell gives you everything you need to verify the run completed
successfully and to report results to co-authors.

---

## Output Files

| File                                  | Location     | Size        | Contents                                      |
| ------------------------------------- | ------------ | ----------- | --------------------------------------------- |
| `ceo_mentions_finbert_scored.parquet` | Google Drive | ~120 MB     | 639K rows with FinBERT scores only            |
| `ceo_mentions_dual_scored.parquet`    | Google Drive | ~200-300 MB | 639K rows with both FinBERT + RoBERTa scores  |
| `ceo_year_finbert_scores.csv`         | Google Drive | ~200 KB     | CEO-year aggregates, FinBERT only             |
| `ceo_year_dual_scores.csv`            | Google Drive | ~400 KB     | CEO-year aggregates, both models side by side |

---

## After Running

1. **Download from Drive to local machine:**
   - `ceo_mentions_dual_scored.parquet` → `data/reference/`
   - `ceo_year_dual_scores.csv` → `data/reports/`

2. **Next pipeline steps:**
   - Compare transformer scores vs dictionary scores (3-way validation: FinBERT
     vs RoBERTa vs Loughran-McDonald). If all three agree directionally, the
     sentiment signal is highly robust.
   - LLM labeling of 5-10K sample with Claude for ground truth — human-quality
     labels to measure each model's accuracy on Reddit text
   - Score earnings call transcripts with FinBERT — the CEO self-presentation
     side of the discrepancy formula
   - Compute
     `self_presentation_discrepancy = CEO_self_score - crowd_perception_score`
     per CEO-quarter and run the paper's regressions

3. **What to report in the paper:**
   - Cross-model correlation (Spearman at CEO level)
   - Label agreement percentage
   - Which model you chose as primary and why
   - The biggest disagreements as a discussion point about construct validity
