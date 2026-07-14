"""
Pydantic models for trade extraction — used by extract_trades.py and log_to_sheets.py.
"""
from pydantic import BaseModel
from typing import Optional, Literal


CONFLUENCE_VOCAB = [
    "OR break",
    "0.618 retrace",
    "unfinished UAL",
    "unfinished UAH",
    "FVG",
    "order block",
    "RVOL gate",
    "LVN pullback",
    "VAH/VAL reversal",
    "liquidity sweep",
    "absorption",
    "SMT confirmed",
    "POC",
    "HVN",
    "imbalance",
    "delta divergence",
]


class TradeWindow(BaseModel):
    start_offset: str  # HH:MM:SS
    end_offset: str  # HH:MM:SS
    classification: Literal["actual", "theoretical", "backtest"]


class SegmentationResult(BaseModel):
    windows: list[TradeWindow]


class Trade(BaseModel):
    time_offset: str  # HH:MM:SS
    asset: str  # NQ, ES, GC, CL, etc.
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
