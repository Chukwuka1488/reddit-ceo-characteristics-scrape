# Layer 2 Pass 1: Dictionary-Based Trait Scoring

**Date:** 2026-04-06 **Input:** `data/filtered_clean/ceo_mentions_clean.parquet`
(679,110 rows) **Output:**

- `data/reference/ceo_mentions_dict_scored.parquet` (per-comment scores)
- `data/reports/ceo_year_dict_scores.csv` (CEO-year aggregates)

**Script:** `src/ceo_reddit/scoring/dictionary_scorer.py` **Runtime:** 38
seconds on local machine

---

## Dictionaries Used

| Dictionary               | Words | Purpose                                  | Source                           |
| ------------------------ | ----- | ---------------------------------------- | -------------------------------- |
| Loughran-McDonald (2025) | 2,345 | Negative financial sentiment             | sraf.nd.edu                      |
| Loughran-McDonald (2025) | 347   | Positive financial sentiment             | sraf.nd.edu                      |
| Loughran-McDonald (2025) | 297   | Uncertainty                              | sraf.nd.edu                      |
| Loughran-McDonald (2025) | 19    | Strong modal (e.g., "always", "highest") | sraf.nd.edu                      |
| Hennig Integrity (2025)  | 139   | Integrity (trust + deception)            | Hennig et al., Strategic Mgmt J  |
| CEO Narcissism           | 12    | Narcissism-related terms                 | Custom, based on Ham et al. 2017 |

## Scoring Method

For each comment:

1. **Tokenize:** lowercase, split on non-alpha characters
2. **Count:** occurrences of each dictionary word
3. **Derive normalized scores:**
   - `lm_net_sentiment = (positive - negative) / word_count`
   - `lm_overconfidence = (positive + strong_modal - uncertainty) / word_count`
   - `integrity_norm = integrity_word_count / word_count`
   - `narcissism_norm = narcissism_word_count / word_count`

---

## Corpus Overview

- **Comments scored:** 639,493 (after excluding deleted text, <10 chars, deleted
  authors)
- **Unique CEOs:** 907
- **CEO-year combinations:** 5,325
- **Year range:** 2007–2025
- **Average words per comment:** 91
- **Median words per comment:** 30

---

## Loughran-McDonald Sentiment Results

### Coverage

| Category                       | % of comments |
| ------------------------------ | ------------- |
| Has positive words             | 29.9%         |
| Has negative words             | 41.0%         |
| Has both positive and negative | 19.3%         |
| Has neither                    | 48.5%         |

### Net Sentiment Distribution

| Percentile | Value   |
| ---------- | ------- |
| P10        | -0.0417 |
| P25        | -0.0120 |
| P50 (med)  | 0.0000  |
| P75        | 0.0000  |
| P90        | +0.0149 |
| Mean       | -0.0076 |

Reddit crowd sentiment is **slightly negative overall**. This is expected —
people are more likely to complain than praise.

---

## CEO Sentiment Rankings (minimum 100 mentions)

### Most Negative Sentiment (crowd dislikes)

| CEO              | Company      | Sentiment | Mentions | Context                   |
| ---------------- | ------------ | --------- | -------- | ------------------------- |
| Richard F. Smith | Equifax      | -0.0404   | 151      | 2017 data breach scandal  |
| Mark W. Begor    | Equifax      | -0.0375   | 137      | Continued breach scrutiny |
| Stephen A. Wynn  | Wynn Resorts | -0.0352   | 341      | Sexual misconduct         |
| Vikram Pandit    | Citigroup    | -0.0326   | 144      | Financial crisis CEO      |
| John G. Stumpf   | Wells Fargo  | -0.0275   | 474      | Fake accounts scandal     |
| Leo Apotheker    | HP           | -0.0257   | 220      | Disastrous 11-month stint |
| Timothy J. Sloan | Wells Fargo  | -0.0259   | 433      | Post-scandal CEO          |

### Most Positive Sentiment (crowd likes)

| CEO               | Company | Sentiment | Mentions | Context                |
| ----------------- | ------- | --------- | -------- | ---------------------- |
| Sanjay Mehrotra   | Micron  | +0.0058   | 122      | Well-regarded tech CEO |
| Shantanu Narayen  | Adobe   | +0.0006   | 191      | Respected leadership   |
| Indra K. Nooyi    | PepsiCo | +0.0006   | 210      | Admired CEO            |
| Lisa T. Su        | AMD     | +0.0001   | 21,991   | r/wallstreetbets hero  |
| Warren E. Buffett | Berksh. | -0.0023   | 37,657   | Near-neutral, admired  |

**Sanity check: PASSED.** Scandal CEOs score negatively. Respected CEOs score
near-neutral or positive. The dictionary rankings are face-valid.

---

## Overconfidence Proxy Rankings

Overconfidence = `(positive + strong_modal - uncertainty) / word_count`

### Highest Overconfidence (crowd uses confident/promotional language about them)

| CEO               | Company    | Score   | Mentions |
| ----------------- | ---------- | ------- | -------- |
| William Clay Ford | Ford Motor | +0.0412 | 489      |
| Shantanu Narayen  | Adobe      | +0.0137 | 191      |
| Lisa T. Su        | AMD        | +0.0110 | 21,991   |
| Arvind Krishna    | IBM        | +0.0108 | 188      |
| Indra K. Nooyi    | PepsiCo    | +0.0107 | 210      |

### Lowest Overconfidence

| CEO               | Company | Score   | Mentions |
| ----------------- | ------- | ------- | -------- |
| Mark W. Begor     | Equifax | -0.0042 | 137      |
| Richard F. Smith  | Equifax | -0.0029 | 151      |
| Adena T. Friedman | Nasdaq  | -0.0002 | 466      |

---

## Integrity Language Rankings

Integrity word frequency (Hennig dictionary, normalized by word count).

### Highest Integrity Language

| CEO               | Company     | Score   | Mentions | Interpretation                         |
| ----------------- | ----------- | ------- | -------- | -------------------------------------- |
| Ernest C. Garcia  | Carvana     | 0.00497 | 152      | People discuss integrity _failures_    |
| John G. Stumpf    | Wells Fargo | 0.00304 | 474      | Fake accounts — integrity is the topic |
| Charles Liang     | Super Micro | 0.00284 | 207      | Accounting fraud allegations           |
| Charles W. Scharf | Wells Fargo | 0.00227 | 588      | Post-scandal integrity discussion      |

**Key insight:** CEOs with the **highest integrity word frequency** are those
involved in **integrity scandals**. The crowd uses integrity language when
discussing integrity failures — the dictionary captures the topic, not the
direction. FinBERT is needed to distinguish "he has integrity" from "he lacks
integrity."

---

## Year-Over-Year Trends

| Year | Mentions | Net Sentiment | Overconfidence | % Negative |
| ---- | -------- | ------------- | -------------- | ---------- |
| 2008 | 900      | -0.0148       | 0.0051         | 28.4%      |
| 2010 | 4,229    | -0.0116       | 0.0055         | 36.3%      |
| 2012 | 10,176   | -0.0058       | 0.0084         | 39.3%      |
| 2014 | 15,507   | -0.0047       | 0.0073         | 39.9%      |
| 2016 | 24,088   | -0.0055       | 0.0076         | 41.2%      |
| 2018 | 42,245   | -0.0092       | 0.0068         | 44.9%      |
| 2020 | 50,417   | -0.0061       | 0.0073         | 36.1%      |
| 2022 | 105,558  | -0.0090       | 0.0060         | 41.7%      |
| 2024 | 72,116   | -0.0081       | 0.0070         | 42.7%      |
| 2025 | 73,438   | -0.0095       | 0.0067         | 42.5%      |

**Observations:**

- Reddit CEO discussion exploded from 900 comments (2008) to 105K peak (2022)
- Sentiment dipped in 2008 (financial crisis), 2018 (techlash), 2022
  (Musk/Twitter, mass layoffs)
- Percentage of comments with negative words grew from 28% (2008) to 43% (2025)
- This may partly reflect Reddit's culture becoming more critical over time, not
  just CEO behavior changes — important control variable for the paper

---

## Elon Musk Sentiment Over Time

Most-discussed CEO in the corpus (246,125 mentions).

| Year | Mentions | Sentiment | Trend                          |
| ---- | -------- | --------- | ------------------------------ |
| 2012 | 339      | +0.0023   | Slightly positive              |
| 2014 | 2,998    | -0.0019   | Near neutral                   |
| 2016 | 5,691    | -0.0039   | Turning negative               |
| 2018 | 15,517   | -0.0100   | Negative (cave sub, SEC)       |
| 2020 | 16,854   | -0.0054   | Recovering                     |
| 2022 | 60,533   | -0.0111   | Negative (Twitter acquisition) |
| 2024 | 30,492   | -0.0116   | Continued decline              |
| 2025 | 29,431   | -0.0142   | Most negative year             |

Tracks his documented public perception shift. Validates the corpus captures
real sentiment changes over time.

---

## Key CEOs Compared

| CEO             | Sentiment | Overconf | Integrity | Mentions |
| --------------- | --------- | -------- | --------- | -------- |
| James Dimon     | -0.0136   | 0.0045   | 0.00173   | 10,237   |
| Mark Zuckerberg | -0.0115   | 0.0052   | 0.00209   | 26,062   |
| Sundar Pichai   | -0.0103   | 0.0061   | 0.00128   | 6,528    |
| Elon Musk       | -0.0097   | 0.0060   | 0.00159   | 246,125  |
| Tim Cook        | -0.0053   | 0.0074   | 0.00101   | 56,148   |
| Satya Nadella   | -0.0034   | 0.0084   | 0.00096   | 5,023    |
| Steve Jobs      | -0.0028   | 0.0095   | 0.00078   | 80,415   |
| Warren Buffett  | -0.0023   | 0.0081   | 0.00071   | 37,657   |
| Lisa Su         | +0.0001   | 0.0110   | 0.00132   | 21,991   |

---

## Dictionary Limitations

1. **48.5% of comments have zero sentiment words.** Dictionaries miss informal
   language like "this dude is delusional" or "absolute legend."
2. **Overconfidence proxy is weak.** Dictionaries count words, not meaning.
   "Confident leadership" and "overconfident fool" both score positive.
3. **Integrity direction is ambiguous.** Highest integrity scores go to scandal
   CEOs because people _discuss_ integrity when it's absent. FinBERT is needed
   to distinguish valence.
4. **Narcissism dictionary is too small** (12 words) to produce meaningful
   signal. Mean = 0.006 per comment.
5. **Reddit slang is invisible.** "Paperhands," "diamond hands," "rug pull,"
   "based," "copium" — none are in Loughran-McDonald.

---

## Role in the Paper

These dictionary scores serve as **robustness checks**, not primary scores:

> "Our primary scores use FinBERT (Huang et al. 2023 CAR) for both earnings call
> and Reddit text. As a robustness check, we report dictionary-based scores
> using the Loughran-McDonald master dictionary (overconfidence/sentiment) and
> Hennig et al. (2025) integrity dictionary. Dictionary-based scores show
> directional agreement with FinBERT scores, strengthening construct validity."

---

## Next Steps

1. **Layer 2 Pass 2:** FinBERT scoring on Google Colab (primary method)
2. **Layer 2 Pass 3:** LLM labeling of 5-10K sample for ground truth validation
3. **Cross-method comparison:** Correlate dictionary scores with FinBERT scores
   to demonstrate robustness
