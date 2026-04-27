# Step-by-step: run the discrepancy pipeline

Total: ~2 hours of Colab compute, ~5 minutes of clicking.

1. **Clone:**
   `git clone https://github.com/Chukwuka1488/reddit-ceo-characteristics-scrape.git && cd reddit-ceo-characteristics-scrape`
2. **Create venv + install:**
   `python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .`
3. **Make a Drive folder** at `/MyDrive/ceo_reddit/data/` (web UI on
   drive.google.com).
4. **Upload these 5 repo files into that Drive folder:**
   - `data/processed/ceo_universe.parquet`
   - `data/inputs/Loughran-McDonald_MasterDictionary_1993-2025.csv`
   - `data/inputs/CEO_Integrity_Dictionary.csv`
   - `data/inputs/CEO_Narcissism_Dictionary.csv`
   - `data/ceo_year_finbert_abc_merged_updated.csv`
5. **Open the FinBERT notebook in Colab:**
   [04_master_pipeline_finbert_colab.ipynb](https://colab.research.google.com/github/Chukwuka1488/reddit-ceo-characteristics-scrape/blob/main/notebooks/corpus_analysis/04_master_pipeline_finbert_colab.ipynb)
6. **Set GPU runtime:** `Runtime → Change runtime type → T4 GPU`.
7. **Run All** — wait ~50–60 min. The notebook fetches transcripts from
   HuggingFace, extracts CEO utterances, scores them, joins to the Reddit
   aggregate, and writes `ceo_year_section_finbert_discrepancy.csv` to your
   Drive.
8. **Open the RoBERTa notebook in Colab:**
   [05_master_pipeline_roberta_colab.ipynb](https://colab.research.google.com/github/Chukwuka1488/reddit-ceo-characteristics-scrape/blob/main/notebooks/corpus_analysis/05_master_pipeline_roberta_colab.ipynb)
9. **Run All** — ~50 min (skips extraction, uses cache from step 7).
10. **Download the two final CSVs** from `/MyDrive/ceo_reddit/data/`:
    `ceo_year_section_finbert_discrepancy.csv` and
    `ceo_year_section_roberta_discrepancy.csv` — both `gvkey`-keyed, ready to
    merge with Compustat.
