"""
Two-pass LLM trade extraction from timestamped transcripts.

Pass 1 — Segmentation: classify trade windows as actual / theoretical / backtest.
Pass 2 — Structured Extraction: extract Trade records from each actual window.

Uses Google Gemini with structured output via response_schema.
Falls back to MODEL_FALLBACK if primary model times out.
"""
import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    MODEL_NAME,
    MODEL_FALLBACK,
    MODEL_TIMEOUT_MINUTES,
    LOGS_DIR,
)
from schemas import (
    CONFLUENCE_VOCAB,
    ExtractionResult,
    SegmentationResult,
    Trade,
)

# ── Timestamp helpers ────────────────────────────────────────────────────────

_TS_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)", re.DOTALL)


def _ts_to_seconds(ts: str) -> int:
    """Convert 'HH:MM:SS' to total seconds."""
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return h * 3600 + m * 60 + s


def _seconds_to_ts(total: int) -> str:
    """Convert total seconds to 'HH:MM:SS'."""
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_line_ts(line: str) -> int | None:
    """Extract seconds from a '[HH:MM:SS] ...' line. Returns None if no match."""
    m = _TS_RE.match(line)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def extract_transcript_slice(
    transcript_text: str, window, pad_seconds: int = 30
) -> str:
    """Return the transcript lines within a window's time range plus padding."""
    win_start = _ts_to_seconds(window.start_offset)
    win_end = _ts_to_seconds(window.end_offset)
    range_start = max(0, win_start - pad_seconds)
    range_end = win_end + pad_seconds

    selected: list[str] = []
    for line in transcript_text.splitlines():
        ts = _parse_line_ts(line)
        if ts is None:
            continue
        if range_start <= ts <= range_end:
            selected.append(line)

    return "\n".join(selected)


# ── LLM calls ────────────────────────────────────────────────────────────────

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _retry(fn, *args, retries: int = 3, **kwargs):
    """Call *fn* with retries and exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  API error (attempt {attempt + 1}/{retries}): {exc}. Retrying in {wait}s...")
                time.sleep(wait)
    raise RuntimeError(f"API call failed after {retries} attempts") from last_exc


def _call_with_timeout(fn, *args, timeout_minutes: int = MODEL_TIMEOUT_MINUTES, **kwargs):
    """Call *fn* in a thread with a timeout. Returns result or raises TimeoutError."""
    result = [None]
    exception = [None]

    def target():
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as exc:
            exception[0] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_minutes * 60)

    if thread.is_alive():
        raise TimeoutError(f"No response within {timeout_minutes} minutes")

    if exception[0] is not None:
        raise exception[0]
    return result[0]


def _generate_with_fallback(client, model, fallback_model, contents, config):
    """Try primary model; if timeout or server error, auto-switch to fallback."""
    try:
        print(f"  Trying {model}...")
        response = _call_with_timeout(
            client.models.generate_content,
            model=model,
            contents=contents,
            config=config,
        )
        return response
    except (TimeoutError, Exception) as exc:
        err_type = type(exc).__name__
        print(f"  {model} failed ({err_type}: {exc}) — switching to {fallback_model}...")
        response = _call_with_timeout(
            client.models.generate_content,
            model=fallback_model,
            contents=contents,
            config=config,
        )
        return response


def run_segmentation_pass(transcript_text: str) -> SegmentationResult:
    """Pass 1: segment the transcript into trade windows with classifications."""
    print("Running segmentation pass...")

    vocab_list = "\n".join(f"  - {v}" for v in CONFLUENCE_VOCAB)

    system_prompt = f"""\
You are a trade-segmentation assistant. Your job is to read a timestamped trading transcript and identify every distinct trade-related discussion window.

For each window, output:
- start_offset: the HH:MM:SS timestamp of the window start
- end_offset: the HH:MM:SS timestamp of the window end
- classification: one of "actual", "theoretical", or "backtest"

Classification definitions:
- "actual": Something the trader actually entered and executed live during this session. Real orders placed.
- "theoretical": Spoken hypotheticals ("if it breaks the high I'd go long", "I'm thinking about going short") that were never actually executed.
- "backtest": Replay or backtest narration — walking through historical price action as a learning exercise, not live execution.

Rules:
- Output every distinct trade discussion, even if there are many.
- A single trade with multiple entries should be one window.
- Separate entries at different times into separate windows.
- Timestamps must be actual timestamps from the transcript text.
- If a segment is ambiguous, classify it as the most likely option but note any uncertainty in your reasoning.

Confluence vocabulary available for reference:
{vocab_list}"""

    user_prompt = f"Segment the following transcript into trade windows:\n\n{transcript_text}"

    client = _get_client()
    response = _generate_with_fallback(
        client,
        model=MODEL_NAME,
        fallback_model=MODEL_FALLBACK,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=SegmentationResult,
            temperature=0.0,
        ),
    )

    if response.parsed is None:
        raise RuntimeError(
            f"Segmentation pass returned unparseable output. Raw: {response.text}"
        )

    result: SegmentationResult = response.parsed
    actual = sum(1 for w in result.windows if w.classification == "actual")
    print(f"  Found {len(result.windows)} windows ({actual} actual, "
          f"{len(result.windows) - actual} theoretical/backtest)")
    return result


def run_extraction_pass(slice_text: str) -> ExtractionResult:
    """Pass 2: extract structured Trade records from a single transcript slice."""
    vocab_list = "\n".join(f"  - {v}" for v in CONFLUENCE_VOCAB)

    system_prompt = f"""\
You are a trade-extraction assistant. Given a transcript slice from a live trading session, extract every actual trade into structured records.

CRITICAL ANTI-HALLUCINATION RULES:
- If a price, entry, stop-loss, take-profit, R:R, or any numeric field is NOT explicitly spoken or clearly inferable from the spoken text, leave it as null.
- NEVER invent a plausible number. Null is always better than a guess.
- If a field is ambiguous, set it to null and explain in notes.
- Only extract trades that were actually executed (live orders), not hypotheticals.

Field guidance:
- time_offset: the timestamp of the trade entry or decision point (HH:MM:SS)
- asset: the instrument traded (NQ, ES, GC, CL, etc.)
- direction: "Long" or "Short"
- rr_planned: planned risk-reward ratio. CALCULATE from spoken entry, stop-loss, and take-profit prices when available. Formula: rr = (TP - entry) / (entry - SL) for Longs, rr = (entry - TP) / (SL - entry) for Shorts. If the trader says "entry at 5200, stop 5190, target 5230" → rr_planned = 3.0. Only null if no TP/SL prices are mentioned at all.
- rr_realized: actual realized R:R — ONLY if trade outcome is discussed. CALCULATE from actual entry and exit prices if mentioned, or from rr_planned if the trade hit its target. POSITIVE for wins (e.g. 2.5), NEGATIVE for losses (e.g. -1.0). Must match trade_exit: if trade_exit is "TP", rr_realized > 0 and equals rr_planned; if "SL", rr_realized < 0 and equals -1.0 (full stop hit) or a partial loss fraction.
- management_style: "aggressive_trailing", "fixed_tp_sl", or "hybrid" — infer from how they describe managing the trade
- trade_duration: the approximate duration of the trade in minutes (e.g. "5m", "12m", "45m"). Infer from timestamps if entry/exit are discussed; null if unclear
- trade_exit: "TP" if the trade hit take-profit, "SL" if it hit a hard stop-loss, "TSL" if it hit a trailing stop-loss — only if outcome is discussed. Must be consistent with rr_realized sign
- pnl: the dollar profit/loss if mentioned — POSITIVE for wins, NEGATIVE for losses; null if not stated
- account_type: "funded", "demo", or "eval" — only if mentioned
- emotions: list of emotions evidenced by actual words/tone, NOT guessed
- confluences: match spoken reasons to the closest vocabulary term below; novel tags OK if nothing matches
- confidence: 0.0-1.0 reflecting how directly-stated vs inferred the fields are
- notes: any additional context

Confluence vocabulary:
{vocab_list}"""

    user_prompt = f"Extract trades from this transcript slice:\n\n{slice_text}"

    client = _get_client()
    response = _generate_with_fallback(
        client,
        model=MODEL_NAME,
        fallback_model=MODEL_FALLBACK,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=ExtractionResult,
            temperature=0.0,
        ),
    )

    if response.parsed is None:
        raise RuntimeError(
            f"Extraction pass returned unparseable output. Raw: {response.text}"
        )

    return response.parsed


# ── Orchestrator ──────────────────────────────────────────────────────────────


def extract_trades(transcript_text: str) -> list[Trade]:
    """Two-pass extraction: segment then extract from actual windows."""
    windows = run_segmentation_pass(transcript_text)
    actual_windows = [w for w in windows.windows if w.classification == "actual"]

    if not actual_windows:
        print("No actual trade windows found.")
        return []

    all_trades: list[Trade] = []
    for i, window in enumerate(actual_windows, 1):
        print(f"Processing window {i}/{len(actual_windows)} "
              f"[{window.start_offset} -> {window.end_offset}]...")
        slice_text = extract_transcript_slice(transcript_text, window, pad_seconds=30)
        if not slice_text.strip():
            print(f"  Warning: no transcript lines found for window, skipping.")
            continue
        result = run_extraction_pass(slice_text)
        all_trades.extend(result.trades)
        print(f"  Extracted {len(result.trades)} trade(s)")

    return all_trades


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Two-pass LLM trade extraction from timestamped transcripts."
    )
    parser.add_argument(
        "--transcript",
        required=True,
        type=Path,
        help="Path to the formatted transcript file.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for the JSON trades file.",
    )
    args = parser.parse_args()

    if not args.transcript.exists():
        print(f"Error: transcript not found at {args.transcript}", file=sys.stderr)
        sys.exit(1)

    transcript_text = args.transcript.read_text(encoding="utf-8")
    if not transcript_text.strip():
        print("Error: transcript file is empty.", file=sys.stderr)
        sys.exit(1)

    trades = extract_trades(transcript_text)

    # Write output
    args.out.parent.mkdir(parents=True, exist_ok=True)
    output_data = [t.model_dump() for t in trades]
    args.out.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary
    print(f"\nExtracted {len(trades)} trade(s) from transcript.")
    for t in trades:
        print(f"  [{t.time_offset}] {t.asset} {t.direction} "
              f"conf={t.confidence:.2f}")

    print(f"\nOutput saved to {args.out}")


if __name__ == "__main__":
    main()
