# CEO Reddit Characteristics — Self-Presentation Discrepancy Pipeline

Data pipeline that measures **self-presentation discrepancy** for accounting
research:

```
discrepancy = self_score (CEO earnings call transcript)
            − crowd_score (Reddit comments mentioning the CEO)
```

…computed per CEO per year for **overconfidence** and **integrity** traits, on
the S&P 500 between 2012 and 2025. Final output is a `gvkey`-keyed CSV ready to
merge with Compustat for the accounting analysis.

The pipeline runs in two halves:

|         | Side                          | Where it runs | Inputs                                           | Outputs                                              |
| ------- | ----------------------------- | ------------- | ------------------------------------------------ | ---------------------------------------------------- |
| Layer 1 | **Crowd** (Reddit)            | local + Colab | Academic Torrents Reddit dumps                   | `ceo_year_finbert_abc_merged_updated.csv`            |
| Layer 2 | **Self** (transcripts) + join | local + Colab | HuggingFace `Bose345/sp500_earnings_transcripts` | `ceo_year_section_{finbert,roberta}_discrepancy.csv` |

---

## Quickstart (transcript-side + discrepancy join)

This is the path most users will take. The Reddit-side aggregate is already
committed to the repo, so you can go straight to the transcript pipeline.

### 1. Clone + install

```bash
git clone https://github.com/Chukwuka1488/reddit-ceo-characteristics-scrape.git
cd reddit-ceo-characteristics-scrape
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Run the master pipeline on Colab

Open one of these in your browser (Colab will fetch the latest from GitHub):

- **FinBERT** master:
  [04_master_pipeline_finbert_colab.ipynb](https://colab.research.google.com/github/Chukwuka1488/reddit-ceo-characteristics-scrape/blob/main/notebooks/corpus_analysis/04_master_pipeline_finbert_colab.ipynb)
- **RoBERTa** master:
  [05_master_pipeline_roberta_colab.ipynb](https://colab.research.google.com/github/Chukwuka1488/reddit-ceo-characteristics-scrape/blob/main/notebooks/corpus_analysis/05_master_pipeline_roberta_colab.ipynb)

Set Runtime → Change runtime type → **T4 GPU**, then **Run All**. Each notebook
takes ~50–60 minutes on a free T4. The notebooks:

1. Fetch `earnings_transcripts.parquet` (2.5 GB) from HuggingFace
2. Extract CEO-only utterances using last-name match + structural Q&A boundary
3. Score utterances with Loughran-McDonald + Hennig integrity dictionaries
4. Score utterances with FinBERT or RoBERTa (sliding-window chunking)
5. Aggregate per `(execid, year, quarter, section)` and
   `(execid, year, section)`
6. Join to the Reddit-side aggregate; compute the discrepancy
7. Save `ceo_year_section_{finbert,roberta}_discrepancy.csv` to your Drive

You'll need to upload these to `/content/drive/MyDrive/ceo_reddit/data/` once
(~10 MB combined, web uploader is fine):

- `data/processed/ceo_universe.parquet`
- `data/inputs/Loughran-McDonald_MasterDictionary_1993-2025.csv`
- `data/inputs/CEO_Integrity_Dictionary.csv`
- `data/inputs/CEO_Narcissism_Dictionary.csv`
- `data/ceo_year_finbert_abc_merged_updated.csv`

(All five are in this repo.)

### 3. The final discrepancy CSV

`ceo_year_section_finbert_discrepancy.csv` carries:

- `execid`, `gvkey`, `cusip`, `abc_conm` (Compustat firm linkage)
- `year`, `section ∈ {prepared, qa}`
- `finbert_sentiment_self`, `finbert_sentiment_crowd`,
  `finbert_sentiment_discrepancy`
- LM dictionary trait scores (`lm_overconfidence_self`, `integrity_norm_self`)
- Per-section utterance counts and word totals

Two rows per (CEO, year) — one for prepared remarks, one for Q&A.

---

## Run locally instead of Colab

The extraction and dictionary-scoring steps run on CPU in ~3 minutes total. Only
the FinBERT/RoBERTa step needs a GPU.

```bash
# 1. Get the transcripts (once)
python -c "from datasets import load_dataset; \
  ds = load_dataset('Bose345/sp500_earnings_transcripts', split='train'); \
  ds.to_parquet('data/inputs/earnings_transcripts.parquet')"

# 2. Extract CEO utterances (~95s)
python -m src.ceo_reddit.transcripts.extract_ceo_utterances

# 3. Dictionary score (~80s)
python -m src.ceo_reddit.scoring.score_utterances
```

For local FinBERT scoring you need a CUDA GPU and the `ml` extras:

```bash
pip install -e '.[ml]'
```

…then port the model-scoring cells from
`notebooks/corpus_analysis/04_master_pipeline_finbert_colab.ipynb` to a local
script. (Most users find Colab easier.)

---

## Layer 1 (Reddit side, already complete)

The Reddit-side pipeline that produced `ceo_year_finbert_abc_merged_updated.csv`
is documented in [`docs/LAYER1_PIPELINE.md`](docs/LAYER1_PIPELINE.md) and
[`docs/LAYER2_FINBERT_COLAB_GUIDE.md`](docs/LAYER2_FINBERT_COLAB_GUIDE.md).
Re-running it requires the Academic Torrents Reddit subreddit dumps (~600 GB of
`.zst` files).

---

## Repository layout

```
configs/settings.py              # canonical paths for every input/output file
src/ceo_reddit/
  discovery/                     # subreddit metadata ingest (Layer 1)
  reference/                     # build CEO universe + name search patterns
  filtering/                     # CEO-name match across Reddit dumps
  scoring/dictionary_scorer.py   # LM + Hennig + narcissism, Reddit side
  scoring/score_utterances.py    # same scoring on CEO transcript utterances
  transcripts/extract_ceo_utterances.py  # Q&A boundary + speaker attribution
notebooks/corpus_analysis/
  03_finbert_scoring_colab.ipynb       # Layer 1 Reddit FinBERT (already run)
  04_master_pipeline_finbert_colab.ipynb  # Layer 2 transcript + discrepancy
  05_master_pipeline_roberta_colab.ipynb  # cross-model robustness
data/
  inputs/                        # what the pipeline reads
  processed/                     # what the pipeline builds
  ceo_year_finbert_abc_merged_updated.csv  # Layer 1 output, joined to Compustat
docs/
  ARCHITECTURE_DECISIONS.md      # design tradeoffs
  LAYER1_PIPELINE.md             # Reddit ingest + filter + score
  TRANSCRIPT_PIPELINE.md         # Layer 2 (this side)
```

---

## Attribution

- **Loughran-McDonald Master Dictionary** — Loughran, T. and McDonald, B.
  (2011). When Is a Liability Not a Liability? Textual Analysis, Dictionaries,
  and 10-Ks. _Journal of Finance_, 66(1), 35–65. The dictionary file in
  `data/inputs/` is committed under the SRAF non-commercial use license.
- **Earnings transcripts** — `Bose345/sp500_earnings_transcripts` on
  HuggingFace.
- **CEO universe** — derived from ExecuComp S&P 1500
  (`data/inputs/snp1500.xls`).
