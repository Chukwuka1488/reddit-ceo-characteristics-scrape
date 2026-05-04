# Earnings Call Transcript Processing — Pidgin Explainer

Oya make I break am down for you, pidgin style.

## Wetin we dey do (the WHAT)

We dey process **earnings call transcripts** — na the calls wey CEO dem dey do
every quarter to tell investors how their company dey perform. We dey collect
wetin the CEO talk for the call, separate am from wetin analyst dem talk, and we
dey score the words.

We dey produce one file: every CEO, every year, wey get two parts —

- **Prepared remarks** (the speech wey CEO read from script for beginning of
  call)
- **Q&A** (when analyst dem dey fire question, CEO go answer off the cuff)

For each part, we dey measure two things:

1. **Overconfidence** — how the CEO dey hype himself ("we dey execute at the
   highest level…")
2. **Integrity** — words wey show trust or deception

## How we dey do am (the HOW)

E get like five steps:

1. **Collect transcripts.** We grab 33,000+ S&P 500 earnings call transcripts
   from HuggingFace (one researcher don already pack am for us). E be parquet
   file, 2.5GB.

2. **Sabi who be CEO.** From ExecuComp data, we build one table wey tell us "for
   this ticker, on this date, na this person be CEO." E dey time-aware because
   CEO dey change.

3. **Pick CEO talk only.** Every transcript get list of `{speaker, text}`. We
   match the speaker name to the CEO last name. But wahala dey — sometimes label
   be like "John Smith - CFO" or "John Smith - Goldman Sachs". So we check the
   title — if e contain "officer", "president", "ceo" e dey exec; if e be
   brokerage name, na analyst.

4. **Find where Q&A start.** This one tricky pass. Operator dey announce Q&A two
   times — once for opening ("there go be Q&A at the end") and once for the real
   handoff. So regex no go work. We use **structural rule**: the second time
   Operator talk after at least one exec don already speak — na there Q&A dey
   start. Anything before na prepared, anything after na Q&A.

5. **Score the words.** Two methods working together:
   - **Dictionary scoring** — count words from Loughran-McDonald financial
     dictionary + Hennig integrity dictionary. Cheap, fast, runs local for 80
     seconds.
   - **FinBERT/RoBERTa** — neural sentiment models wey understand context.
     Heavy, need GPU, runs for Colab.

   For long speech, we no fit just dump everything into FinBERT (e get 512-token
   limit). So we dey slice am into 510-token windows wey overlap by 50 tokens,
   score each window, average back.

6. **Join with Reddit data.** The Reddit side don already dey ready
   (`ceo_year_finbert_abc_merged_updated.csv`). We join on `(execid, year)` and
   compute:
   ```
   discrepancy = self_score (transcript) − crowd_score (Reddit)
   ```

## Why we dey do am (the WHY)

The whole research na to measure **self-presentation discrepancy** — the gap
between how CEO dey paint himself versus how the public dey see am. The bigger
the gap, the more we suspect say the CEO dey project image wey no match reality.

Why we separate prepared vs Q&A?

- **Prepared remarks** na scripted — CEO get time to polish am, IR team go
  review. So e dey show **deliberate impression management**. Na where
  confidence projection dey peak.
- **Q&A** na off-the-cuff — analyst go ask sharp question, CEO must answer
  immediately. Less polish, more authentic signal. Accounting paper dem (Larcker
  & Zakolyukina 2012) don already establish say Q&A na the unscripted gold mine
  for detecting deception.

If we no separate dem, the prepared script go dilute the Q&A signal and we go
miss the real thing.

Why discrepancy and no just CEO score alone?

- CEO of correct company go sound confident — that one no be lie, na truth. So
  if you only measure self-score, you no fit tell who dey hype versus who dey
  perform.
- But if CEO dey hype himself for transcript while Reddit (the crowd wey dey
  watch the company day-to-day) dey vex, **that gap** na the signal of
  overconfidence wey no match reality.

Final output na one CSV with `gvkey` (Compustat key), so the accounting
researchers fit join with financial statement data and test things like: "do
CEOs with high discrepancy do more earnings management? More restatements? More
fraud?"

Na im be the whole gist.

---

## Step-by-step wetin colleague go run for Colab

**Step 1 — Clone the repo.** `git clone` the GitHub repo. Why? All the scoring
code, dictionaries, and the Reddit-side joined CSV dey inside.

**Step 2 — Make Drive folder.** Create `MyDrive/ceo_reddit/data/` for him Google
Drive. Why? Colab go save output there so e no go lose am when runtime expire.

**Step 3 — Upload 5 files into that Drive folder.** Why? Colab no go fit pull
these from the repo automatically. Better upload once, reuse.

**Step 4 — Open FinBERT notebook for Colab.** Click the link for README, e go
open `04_master_pipeline_finbert_colab.ipynb` straight from GitHub. Why? No need
to download notebook, Colab dey read am live.

**Step 5 — Set GPU.** `Runtime → Change runtime type → T4 GPU`. Why? FinBERT na
neural model — on CPU e go take like 6 hours, on T4 e go finish for under 1
hour.

**Step 6 — Run All.** The notebook go:

1. Pull 33k earnings transcripts from HuggingFace (so colleague no need upload
   2.5GB)
2. Extract only CEO talk
3. Score with dictionaries + FinBERT
4. Join with the Reddit CSV
5. Save final `ceo_year_section_finbert_discrepancy.csv` to Drive

Why one-click? All the complexity dey hide inside the notebook — colleague no
need touch code.

**Step 7 — Open RoBERTa notebook, Run All.** Same thing but different model.

**Step 8 — Download two final CSVs from Drive.** Na the deliverable. Both get
gvkey, ready to merge with Compustat for the accounting analysis.

---

## The 5 files wey colleague go upload — wetin dem contain and why

### 1. `ceo_universe.parquet`

**Wetin dey inside:** 1,193 rows. Each row na one CEO tenure — execid, full
name, last name, ticker, company name, start date, end date.

**Why we need am:** When transcript come in for Apple on 2018-08-01, we must
sabi say na **Tim Cook** be CEO that day, no be Steve Jobs. The file dey
time-aware so e dey handle CEO transitions. Without am we no fit match speaker
to CEO at all.

### 2. `Loughran-McDonald_MasterDictionary_1993-2025.csv`

**Wetin dey inside:** 86,553 English words wey finance researchers don classify
— positive, negative, uncertainty, strong modal (will, must), litigious, etc.

**Why we need am:** Normal sentiment dictionaries (like the ones for movie
reviews) no fit work for finance text. Word like "liability" sound bad for
normal English but for accounting na neutral term. LM dictionary na the standard
wey accounting paper dem don dey use since 2011 — if you no use am, your paper
no go pass review.

### 3. `CEO_Integrity_Dictionary.csv`

**Wetin dey inside:** ~278 words wey Hennig research group classify into
trust-words versus deception-words.

**Why we need am:** Integrity na one of the two traits we dey measure. LM no get
integrity category, so we add this separate dictionary specifically for that
signal.

### 4. `CEO_Narcissism_Dictionary.csv`

**Wetin dey inside:** 12 words wey signal narcissism — arrogance, boast, pride,
supreme, etc.

**Why we need am:** Tertiary signal — small but useful as triangulation. If
overconfidence dey rise but narcissism words no dey rise, e fit be confidence
without grandiosity. Two different things.

### 5. `ceo_year_finbert_abc_merged_updated.csv`

**Wetin dey inside:** 2,860 rows. Reddit comments wey mention each CEO, already
FinBERT-scored, already joined to Compustat (gvkey, cusip, abc_conm). Na the
Reddit-side output we don already finish.

**Why we need am:** This na the **crowd_score** half of the discrepancy. Without
am you only get the CEO speaking — no public reaction to compare to, no
discrepancy. Also e carry the Compustat keys (gvkey) wey final output need. We
don already run this for previous Colab session — we no go re-run am because:

- E take long time
- Result no go change (Reddit comments na historical)
- E save GPU compute for the transcript side

---

## Why we dey run both FinBERT and RoBERTa

If one model alone fit do the work, we for don end am. But two models dey
necessary because:

### 1. **Different training data, different blind spots**

- **FinBERT** (`ProsusAI/finbert`) — train on financial news, analyst reports,
  earnings calls. E sabi finance language. Word like "headwind" or "guidance" e
  go interpret correct.
- **Twitter-RoBERTa** (`cardiffnlp/twitter-roberta-base-sentiment-latest`) —
  train on Twitter. E sabi informal English, slang, sarcasm, emoji-style text —
  exactly the kind of thing wey dey for Reddit comments.

For transcripts, FinBERT dey more accurate. For Reddit, RoBERTa fit catch
sarcasm and informal hate wey FinBERT go miss. So we dey ask both.

### 2. **Robustness check**

This na the main reason. If we only run one model and the discrepancy show,
reviewer go ask: "wetin if your model just biased? wetin if e dey see negative
where positive dey?" Two models give us cover:

- If **FinBERT and RoBERTa both agree** say discrepancy dey, e mean the signal
  dey real, no be model artifact.
- If **dem disagree**, that one self na useful information — e go tell us where
  the construct dey weak.

### 3. **Cross-model validation na standard for accounting**

When you dey publish for top finance journal (JAR, JFE, RFS), they go ask for
robustness checks. Running with two different models na cheap, fast way to
satisfy that requirement. Better we do am from start than reviewer go reject the
paper.

### 4. **No extra colleague effort**

The two notebooks share the same expensive step (extracting CEO utterances).
RoBERTa notebook dey use cache from FinBERT notebook, so e no go re-extract.
Total extra time: ~50 minutes for second model. Small price for the
methodological cover.

**Bottom line:** FinBERT na the primary, RoBERTa na the backup wey dey
strengthen the paper. Two heads dey reason pass one.
