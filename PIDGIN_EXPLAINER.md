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
