"""Layer 2 input: Extract CEO-only utterances from earnings call transcripts.

Each transcript row in ``earnings_transcripts.parquet`` exposes a
``structured_content`` field — a list of ``{speaker, text}`` dicts. For each
call we look up the CEO(s) tenured on that date (from ``ceo_universe.parquet``)
and emit one row per utterance where the speaker is that CEO.

Each utterance is tagged ``section='prepared'`` or ``section='qa'`` so the
self-presentation score can be computed on prepared remarks (deliberate
projection) and Q&A (less scripted) separately.
"""

import json
import logging
import re
import time
from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from configs.settings import (
    CEO_UNIVERSE_PARQUET,
    CEO_UTTERANCES_PARQUET,
    EARNINGS_TRANSCRIPTS_PARQUET,
    TRANSCRIPT_EXTRACTION_REPORT,
)

logger = logging.getLogger(__name__)

# Speaker labels are sometimes "Name - Title" (e.g., 'David Ratcliffe - Chief
# Executive Officer') and sometimes "Name - Brokerage" (e.g., 'Ashar Khan -
# SAC Capital'). The dash alone does not distinguish them — we check the
# trailing fragment for executive-title keywords. If those keywords appear
# the speaker is an exec; otherwise we treat the label as an analyst.
DASH_SPLIT_RE = re.compile(r"\s[-–—]\s+")
EXEC_TITLE_KEYWORDS = (
    "officer", "president", "ceo", "cfo", "coo", "cio", "cto", "cmo",
    "chairman", "chairwoman", "chairperson", "chair",
    "founder", "co-founder", "director", "managing director",
    "vp", "evp", "svp", "vice president", "head of",
    "treasurer", "controller", "secretary",
    "investor relations", "ir contact", "general counsel",
    "executive", "principal", "owner",
)

# Q&A introduction is signaled by phrases that appear ONLY at the Q&A boundary.
# Patterns excluded as too broad: bare "[Operator Instructions]" (also appears
# at call start as a mute instruction) and "question-and-answer session" (the
# operator previews this in the opening). Matching one of these on utterance
# ``i`` means Q&A starts at ``i + 1``.
QA_CUE_RE = re.compile(
    r"first\s+question\s+(?:comes|is|will\s+come|today\s+is)\s+from"
    r"|now\s+(?:begin|take|start|open)\s+(?:the\s+|our\s+)?(?:question[-\s]and[-\s]answer|q\s*&\s*a)"
    r"|now\s+take\s+(?:our|the|your)?\s*first\s+question"
    r"|will\s+now\s+take\s+(?:any\s+|your\s+|some\s+)?questions"
    r"|open\s+(?:up\s+)?(?:the\s+)?(?:floor|line|call)\s+(?:up\s+)?(?:to|for)\s+(?:any\s+|your\s+)?questions"
    r"|opening\s+(?:up\s+)?(?:the\s+)?(?:floor|line)\s+(?:up\s+)?(?:to|for)\s+questions"
    r"|turn\s+(?:it\s+)?(?:back\s+)?(?:over\s+)?to\s+the\s+operator\s+for\s+(?:questions|q\s*&\s*a)"
    r"|operator\s*,?\s+(?:please\s+)?(?:provide\s+(?:the\s+)?instructions\s+for|let'?s\s+take|take\s+(?:the\s+)?(?:first\s+)?question)"
    r"|please\s+(?:provide|give\s+us)\s+(?:the\s+)?instructions\s+for\s+(?:the\s+)?q\s*&\s*a",
    re.IGNORECASE,
)


def _normalize_structured_content(value) -> list[dict]:
    """Coerce the ``structured_content`` cell to a list of speaker dicts.

    The HuggingFace dataset may store it as a Python list, a numpy array of
    dicts, or a JSON string depending on the parquet writer. This unifies them.
    """
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    # numpy arrays / pandas-extracted object arrays are iterable
    try:
        return [item for item in value if isinstance(item, dict)]
    except TypeError:
        return []


def _detect_qa_start(utterances: list[dict]) -> int:
    """Return the utterance index where Q&A begins; ``len(utterances)`` if none.

    Primary rule (structural): the Q&A handoff is the first Operator turn that
    follows both (a) the operator's opening intro and (b) at least one
    executive's prepared remark. This holds across nearly every S&P 500 call
    because operators speak in a very predictable arc: open → handoff →
    next-question → ... → close.

    Fallback A: any utterance whose text contains a specific Q&A-introduction
    phrase (e.g. "first question comes from"). Q&A starts on the turn AFTER it.

    Fallback B: the first speaker labeled in analyst-tag form
    ("Name - Brokerage" where the trailing fragment is not an executive title).
    """
    saw_first_operator = False
    saw_executive = False
    for idx, item in enumerate(utterances):
        speaker = (item.get("speaker") or "").strip()
        text = (item.get("text") or "").strip()
        is_operator = speaker.lower() == "operator"
        if is_operator and len(text) >= 30:
            if saw_first_operator and saw_executive:
                return idx
            saw_first_operator = True
        elif speaker and not is_operator and len(text) >= 30:
            saw_executive = True

    for idx, item in enumerate(utterances):
        if QA_CUE_RE.search(item.get("text") or ""):
            return idx + 1

    for idx, item in enumerate(utterances):
        speaker = (item.get("speaker") or "").strip()
        if _looks_like_analyst(speaker):
            return idx

    return len(utterances)


def _looks_like_analyst(speaker: str) -> bool:
    """True if the speaker label has 'Name - Brokerage' shape (not 'Name - Title').

    'David Ratcliffe - Chief Executive Officer'  -> exec  (False)
    'Ashar Khan - SAC Capital'                   -> analyst (True)
    'Operator', 'David Ratcliffe', ''            -> not enough info (False)
    """
    if not speaker or not DASH_SPLIT_RE.search(speaker):
        return False
    after = DASH_SPLIT_RE.split(speaker, maxsplit=1)[-1].strip().lower()
    if not after:
        return False
    return not any(kw in after for kw in EXEC_TITLE_KEYWORDS)


def _ceos_active_on(
    ceo_df: pd.DataFrame, ticker: str, call_date: date
) -> pd.DataFrame:
    """Return CEO rows tenured at ``ticker`` on ``call_date`` (0, 1, or 2 rows)."""
    if call_date is None:
        return ceo_df.iloc[0:0]
    mask = (
        (ceo_df["ticker"] == ticker)
        & (ceo_df["ceo_start_date"].dt.date <= call_date)
        & (
            ceo_df["ceo_end_date"].isna()
            | (ceo_df["ceo_end_date"].dt.date >= call_date)
        )
    )
    return ceo_df.loc[mask]


def _extract_call_utterances(
    transcript_row: pd.Series,
    ceos: pd.DataFrame,
) -> tuple[list[dict], dict]:
    """Walk one transcript and return (CEO utterance rows, per-call diagnostics)."""
    structured = _normalize_structured_content(transcript_row["structured_content"])
    diagnostics = {
        "symbol": transcript_row["symbol"],
        "year": int(transcript_row["year"]),
        "quarter": int(transcript_row["quarter"]),
        "date": transcript_row["call_date"],
        "n_utterances": len(structured),
        "n_ceo_utterances": 0,
        "qa_start_idx": None,
        "n_ceos_tenured": len(ceos),
        "matched_any_ceo": False,
    }

    if not structured or ceos.empty:
        return [], diagnostics

    qa_start = _detect_qa_start(structured)
    diagnostics["qa_start_idx"] = qa_start

    # Lowercased last names → CEO record (one per active CEO, usually 1)
    ceo_by_lname = {
        ceo["last_name"].lower(): ceo
        for _, ceo in ceos.iterrows()
        if isinstance(ceo["last_name"], str) and ceo["last_name"]
    }

    rows: list[dict] = []
    for idx, item in enumerate(structured):
        speaker = (item.get("speaker") or "").strip()
        text = (item.get("text") or "").strip()
        if not speaker or not text:
            continue
        if _looks_like_analyst(speaker):
            continue

        speaker_lower = speaker.lower()
        matched_ceo = None
        for lname, ceo in ceo_by_lname.items():
            if lname in speaker_lower:
                matched_ceo = ceo
                break
        if matched_ceo is None:
            continue

        section = "prepared" if idx < qa_start else "qa"
        rows.append({
            "symbol": transcript_row["symbol"],
            "company_name": transcript_row.get("company_name"),
            "year": int(transcript_row["year"]),
            "quarter": int(transcript_row["quarter"]),
            "call_date": transcript_row["call_date"],
            "execid": int(matched_ceo["execid"]),
            "ceo_full_name": matched_ceo["full_name"],
            "section": section,
            "utterance_idx": idx,
            "speaker_label": speaker,
            "text": text,
            "n_words": len(text.split()),
        })

    diagnostics["n_ceo_utterances"] = len(rows)
    diagnostics["matched_any_ceo"] = bool(rows)
    return rows, diagnostics


def _coerce_call_date(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw[: len(fmt) + 2], fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def extract_all(
    transcripts: pd.DataFrame,
    ceo_universe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """Extract CEO utterances from every transcript. Returns (utterances, diagnostics)."""
    transcripts = transcripts.copy()
    transcripts["call_date"] = transcripts["date"].map(_coerce_call_date)

    # Ensure CEO date columns are pandas datetimes (the parquet stores them as ns)
    ceo_universe = ceo_universe.copy()
    for col in ("ceo_start_date", "ceo_end_date"):
        ceo_universe[col] = pd.to_datetime(ceo_universe[col], errors="coerce")

    all_rows: list[dict] = []
    diagnostics: list[dict] = []
    started = time.time()
    for i, (_, row) in enumerate(transcripts.iterrows(), start=1):
        ceos = _ceos_active_on(ceo_universe, row["symbol"], row["call_date"])
        rows, diag = _extract_call_utterances(row, ceos)
        all_rows.extend(rows)
        diagnostics.append(diag)

        if i % 2000 == 0:
            elapsed = time.time() - started
            logger.info(
                "Processed %d/%d transcripts (%.1fs, %d CEO utterances so far)",
                i, len(transcripts), elapsed, len(all_rows),
            )

    df = pd.DataFrame(all_rows)
    return df, diagnostics


def _summarize(diagnostics: list[dict], utterances: pd.DataFrame) -> dict:
    """Build a JSON-serializable summary of extraction quality."""
    n_calls = len(diagnostics)
    n_calls_with_tenured_ceo = sum(1 for d in diagnostics if d["n_ceos_tenured"] > 0)
    n_calls_with_match = sum(1 for d in diagnostics if d["matched_any_ceo"])
    n_calls_no_qa = sum(
        1 for d in diagnostics
        if d["qa_start_idx"] is not None and d["qa_start_idx"] >= d["n_utterances"]
    )
    return {
        "n_transcripts": n_calls,
        "n_with_tenured_ceo": n_calls_with_tenured_ceo,
        "n_with_ceo_utterance_matched": n_calls_with_match,
        "match_rate_overall": (
            n_calls_with_match / n_calls if n_calls else 0.0
        ),
        "match_rate_among_tenured": (
            n_calls_with_match / n_calls_with_tenured_ceo
            if n_calls_with_tenured_ceo else 0.0
        ),
        "n_calls_no_qa_detected": n_calls_no_qa,
        "n_ceo_utterances": int(len(utterances)),
        "n_unique_ceos": int(utterances["execid"].nunique()) if len(utterances) else 0,
        "n_unique_tickers": int(utterances["symbol"].nunique()) if len(utterances) else 0,
        "section_counts": (
            utterances["section"].value_counts().to_dict() if len(utterances) else {}
        ),
        "words_per_section": (
            utterances.groupby("section")["n_words"].sum().to_dict()
            if len(utterances) else {}
        ),
    }


def main() -> None:
    """Read transcripts + CEO universe, write CEO-only utterances + report."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Loading transcripts from %s", EARNINGS_TRANSCRIPTS_PARQUET)
    transcripts = pd.read_parquet(EARNINGS_TRANSCRIPTS_PARQUET)
    logger.info("Loaded %d transcripts", len(transcripts))

    logger.info("Loading CEO universe from %s", CEO_UNIVERSE_PARQUET)
    ceo_universe = pd.read_parquet(CEO_UNIVERSE_PARQUET)
    logger.info("Loaded %d CEO records", len(ceo_universe))

    utterances, diagnostics = extract_all(transcripts, ceo_universe)
    logger.info(
        "Extracted %d CEO utterances across %d calls",
        len(utterances),
        sum(1 for d in diagnostics if d["matched_any_ceo"]),
    )

    CEO_UTTERANCES_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(utterances, preserve_index=False)
    pq.write_table(table, CEO_UTTERANCES_PARQUET, compression="zstd")
    logger.info("Wrote %s", CEO_UTTERANCES_PARQUET)

    summary = _summarize(diagnostics, utterances)
    TRANSCRIPT_EXTRACTION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with TRANSCRIPT_EXTRACTION_REPORT.open("w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("Wrote extraction report to %s", TRANSCRIPT_EXTRACTION_REPORT)

    logger.info(
        "match_rate_among_tenured=%.3f | calls_no_qa=%d | utterances=%d",
        summary["match_rate_among_tenured"],
        summary["n_calls_no_qa_detected"],
        summary["n_ceo_utterances"],
    )


if __name__ == "__main__":
    main()
