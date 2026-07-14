# Feature: Two-Pass Trade Extraction (Claude Haiku 4.5)

## Goal
Turn a raw timestamped transcript into a validated list of trade records, with minimal hallucination and no fabricated numbers.

## File
`extract_trades.py`, schema in `schemas.py`

## Model
`claude-haiku-4-5-20251001`. Before implementing the structured-output call, check the current Anthropic Python SDK docs for the exact structured-output / JSON-schema-enforcement syntax — don't assume `.parse()`/`response_format` from the original blueprint is still accurate; that API surface changes.

## Pydantic schema (`schemas.py`)

```python
from pydantic import BaseModel
from typing import Optional, Literal

CONFLUENCE_VOCAB = [
    "OR break", "0.618 retrace", "unfinished UAL", "unfinished UAH",
    "FVG", "order block", "RVOL gate", "LVN pullback", "VAH/VAL reversal",
    "liquidity sweep", "absorption", "SMT confirmed", "POC", "HVN",
    "imbalance", "delta divergence",
]

class TradeWindow(BaseModel):
    start_offset: str          # HH:MM:SS
    end_offset: str            # HH:MM:SS
    classification: Literal["actual", "theoretical", "backtest"]

class SegmentationResult(BaseModel):
    windows: list[TradeWindow]

class Trade(BaseModel):
    time_offset: str
    asset: str                              # NQ, ES, GC, CL, etc — not restricted to an enum
    direction: Literal["Long", "Short"]
    rr_planned: Optional[float] = None
    rr_realized: Optional[float] = None
    management_style: Literal["aggressive_trailing", "fixed_tp_sl", "hybrid"]
    account_type: Literal["funded", "personal"]
    emotions: list[str] = []
    confluences: list[str] = []
    confidence: float
    notes: str

class ExtractionResult(BaseModel):
    trades: list[Trade]
```

## Pass 1 — Segmentation

System prompt (paraphrase this into the actual call, don't ship it verbatim as a comment — write real logic):
- Task: read the timestamped transcript, output every distinct trade-related window with a classification of `actual`, `theoretical`, or `backtest`.
- `actual` = something the trader actually entered/executed live in this session.
- `theoretical` = spoken hypotheticals ("if it breaks the high, I'd go long") that were never executed.
- `backtest` = replay/backtest narration, explicitly distinguish this from live execution.
- Output validated against `SegmentationResult`.

## Pass 2 — Structured Extraction (per `actual` window only)

For each `actual` window from Pass 1, send just that transcript slice (plus a little surrounding context, e.g. 30s before/after) and extract into the `Trade` schema.

Critical instructions to bake into this system prompt:
- **Anti-hallucination is non-negotiable.** If a price, RR, or other numeric field isn't explicitly spoken or clearly inferable from what's spoken, leave it `null` — never invent a plausible number.
- Use the merged confluence vocabulary (`CONFLUENCE_VOCAB` in `schemas.py`) — match spoken language to the closest vocab term rather than inventing new tags, but if genuinely nothing matches, it's fine to add a novel short tag rather than force a bad match.
- `confidence` should reflect how directly-stated vs. inferred the extracted fields are — a trade with an explicit entry, stop, and target spoken aloud should score high; one reconstructed mostly from vague language should score low.
- Never fabricate emotional state — only tag `emotions` if there's actual tone/word evidence in the transcript ("I was hesitant on this one," visible frustration in word choice), not a default guess.

## Orchestration inside `extract_trades.py`

```python
def extract_trades(transcript_text: str) -> list[Trade]:
    windows = run_segmentation_pass(transcript_text)  # -> SegmentationResult
    actual_windows = [w for w in windows.windows if w.classification == "actual"]

    all_trades = []
    for window in actual_windows:
        slice_text = extract_transcript_slice(transcript_text, window, pad_seconds=30)
        result = run_extraction_pass(slice_text)  # -> ExtractionResult
        all_trades.extend(result.trades)
    return all_trades
```

`extract_transcript_slice` pulls only the relevant `[HH:MM:SS] text` lines (plus padding) from the full formatted transcript — don't re-send the whole transcript for every window, that's wasted tokens and increases hallucination surface.

## Cost note
Two-pass costs roughly 2x the LLM calls of a single-pass design but meaningfully reduces false-positive "actual trades." At Haiku 4.5 pricing this is still a trivially small per-session cost — don't optimize this away for cost reasons.

## CLI usage
```
python extract_trades.py --transcript logs/abc123_transcript.txt --out logs/abc123_trades.json
```

## Acceptance check
On a test transcript with known ground truth (2-3 real trades, at least one theoretical "if it breaks I'd go long" statement, and if possible one backtest-replay mention), Pass 1 correctly separates them and Pass 2 produces trade records with zero fabricated numeric fields — check every extracted price/RR against what was actually said.
