# Resume Prompt

Paste this to continue where we left off:

---

We're building a Reddit CEO characteristics pipeline for an accounting journal
paper on self-presentation discrepancy. Read these files to get up to speed:

1. `CLAUDE.md` — project rules and conventions
2. `docs/ARCHITECTURE_DECISIONS.md` — all decided tradeoffs
3. `docs/LAYER1_PIPELINE.md` — execution plan, scroll to "Next Steps"

Step 1 (subreddit discovery) is complete. 81 subreddits approved, 22M metadata
loaded in DuckDB. Pick up from the "Next Steps" section — the first task is
building the CEO Universe Table (Step 0A) from `data/inputs/snp1500.xls`.

Follow TDD — write tests first, then implement. Use DuckDB native operations
where possible (we learned Python line-by-line parsing was 175x slower). No
tables in documentation, use bullet points. No Co-Authored-By in commits.
