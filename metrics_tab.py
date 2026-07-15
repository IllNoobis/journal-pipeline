"""Metrics & Options tab management for the trading journal Google Sheet.

Creates a 'Metrics' tab with live formulas that reference the Trades tab,
and an 'Options' tab showing valid values for each header column.
All formulas auto-update when new trades are added — no Python re-run needed.

Trades tab layout (A-Q):
  A: video_link      B: time_offset     C: asset
  D: account_type    E: direction       F: trade_duration
  G: rr_planned      H: rr_realized     I: management_style
  J: TP/SL           K: PNL             L: emotions
  M: confluences     N: confidence      O: status
  P: notes           Q: video_id
"""

import sys
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_SHEETS_CREDS, METRICS_TAB, SPREADSHEET_NAME

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

OPTIONS_TAB = "Options"

# ── Duration helper ──────────────────────────────────────────────────────────
# Parses "5m", "1h20m", "1h 20m", "1h20" → minutes as a number
# Used inside LET formulas: mins = DUR_TO_MINS(Trades!F2:F)
DUR_TO_MINS = (
    'IF(ISNUMBER(SEARCH("h",{r})),'
    'VALUE(LEFT({r},SEARCH("h",{r})-1))*60+'
    'IFERROR(VALUE(MID({r},SEARCH("h",{r})+1,LEN({r})-SEARCH("h",{r})-1)),0),'
    'VALUE(SUBSTITUTE({r},"m","")))'
).replace("{r}", "dur")


# ══════════════════════════════════════════════════════════════════════════════
# METRICS TAB
# ══════════════════════════════════════════════════════════════════════════════

METRICS_LAYOUT: list[tuple[str, str | None]] = [
    # ── PERFORMANCE ──────────────────────────────────────────────────────────
    ("PERFORMANCE", None),
    ("Win Rate", '=IFERROR(COUNTIF(Trades!H2:H,">"&0)/COUNTA(Trades!H2:H),0)'),
    ("Profit Factor", '=IFERROR(SUMPRODUCT((Trades!H2:H>0)*Trades!H2:H)/ABS(SUMPRODUCT((Trades!H2:H<0)*Trades!H2:H)),0)'),
    ("Avg R:R Realized", "=IFERROR(AVERAGE(Trades!H2:H),0)"),
    ("Avg R:R Planned", "=IFERROR(AVERAGE(Trades!G2:G),0)"),
    ("Total R:R P/L", "=SUM(Trades!H2:H)"),
    ("Avg Win / Avg Loss Ratio", '=IFERROR(AVERAGEIF(Trades!H2:H,">"&0)/ABS(AVERAGEIF(Trades!H2:H,"<"&0)),0)'),
    ("Expectancy", '=IFERROR((COUNTIF(Trades!H2:H,">"&0)/COUNTA(Trades!H2:H))*AVERAGEIF(Trades!H2:H,">"&0)-((1-(COUNTIF(Trades!H2:H,">"&0)/COUNTA(Trades!H2:H)))*ABS(AVERAGEIF(Trades!H2:H,"<"&0))),0)'),

    # ── RISK ─────────────────────────────────────────────────────────────────
    ("RISK", None),
    ("Sharpe Ratio (per trade)", "=IFERROR(AVERAGE(Trades!H2:H)/STDEV(Trades!H2:H),0)"),
    ("Sortino Ratio", '=IFERROR(AVERAGE(Trades!H2:H)/SQRT(SUMPRODUCT((Trades!H2:H<0)*(Trades!H2:H^2))/COUNTA(Trades!H2:H)),0)'),
    ("Max Drawdown (R)", "=IFERROR(LET(equity,SCAN(0,Trades!H2:H,LAMBDA(a,c,a+c)),peak,SCAN(0,Trades!H2:H,LAMBDA(a,c,MAX(a,a+c))),MAX(peak-equity)),0)"),
    ("Calmar Ratio", "=IFERROR(SUM(Trades!H2:H)/ABS(LET(equity,SCAN(0,Trades!H2:H,LAMBDA(a,c,a+c)),peak,SCAN(0,Trades!H2:H,LAMBDA(a,c,MAX(a,a+c))),MAX(peak-equity))),0)"),
    ("Equity Curve (cumulative R)", "=SCAN(0,Trades!H2:H,LAMBDA(acc,cur,acc+cur))"),

    # ── VOLUME ───────────────────────────────────────────────────────────────
    ("VOLUME", None),
    ("Total Trades", "=COUNTA(Trades!H2:H)"),
    ("Longs", '=COUNTIF(Trades!E2:E,"Long")'),
    ("Shorts", '=COUNTIF(Trades!E2:E,"Short")'),
    ("Funded", '=COUNTIF(Trades!D2:D,"funded")'),
    ("Demo", '=COUNTIF(Trades!D2:D,"demo")'),
    ("Eval", '=COUNTIF(Trades!D2:D,"eval")'),

    # ── TP/SL & PNL ─────────────────────────────────────────────────────────
    ("TP/SL & PNL", None),
    ("TP Hits", '=COUNTIF(Trades!J2:J,"TP")'),
    ("SL Hits", '=COUNTIF(Trades!J2:J,"SL")'),
    ("TSL Hits", '=COUNTIF(Trades!J2:J,"TSL")'),
    ("TP Rate", '=IFERROR(COUNTIF(Trades!J2:J,"TP")/COUNTA(Trades!J2:J),0)'),
    ("SL Rate", '=IFERROR(COUNTIF(Trades!J2:J,"SL")/COUNTA(Trades!J2:J),0)'),
    ("TSL Rate", '=IFERROR(COUNTIF(Trades!J2:J,"TSL")/COUNTA(Trades!J2:J),0)'),
    ("Avg PNL", "=IFERROR(AVERAGE(Trades!K2:K),0)"),
    ("Total PNL", "=SUM(Trades!K2:K)"),
    ("Best Trade ($PNL)", "=IFERROR(MAX(Trades!K2:K),0)"),
    ("Worst Trade ($PNL)", "=IFERROR(MIN(Trades!K2:K),0)"),
    ("Avg PNL on TP", '=IFERROR(AVERAGEIF(Trades!J2:J,"TP",Trades!K2:K),0)'),
    ("Avg PNL on SL", '=IFERROR(AVERAGEIF(Trades!J2:J,"SL",Trades!K2:K),0)'),
    ("Avg PNL on TSL", '=IFERROR(AVERAGEIF(Trades!J2:J,"TSL",Trades!K2:K),0)'),
    ("PNL per R Ratio", '=IFERROR(AVERAGE(Trades!K2:K)/AVERAGE(Trades!H2:H),0)'),

    # ── EXIT TYPE BREAKDOWN ──────────────────────────────────────────────────
    ("EXIT TYPE BREAKDOWN", None),
    ("TP Avg R:R", '=IFERROR(AVERAGEIF(Trades!J2:J,"TP",Trades!H2:H),0)'),
    ("TP Win Rate", '=IFERROR(COUNTIFS(Trades!J2:J,"TP",Trades!H2:H,">"&0)/COUNTIF(Trades!J2:J,"TP"),0)'),
    ("SL Avg R:R", '=IFERROR(AVERAGEIF(Trades!J2:J,"SL",Trades!H2:H),0)'),
    ("SL Win Rate", '=IFERROR(COUNTIFS(Trades!J2:J,"SL",Trades!H2:H,">"&0)/COUNTIF(Trades!J2:J,"SL"),0)'),
    ("TSL Avg R:R", '=IFERROR(AVERAGEIF(Trades!J2:J,"TSL",Trades!H2:H),0)'),
    ("TSL Win Rate", '=IFERROR(COUNTIFS(Trades!J2:J,"TSL",Trades!H2:H,">"&0)/COUNTIF(Trades!J2:J,"TSL"),0)'),

    # ── EXIT TYPE + DIRECTION ────────────────────────────────────────────────
    ("EXIT TYPE + DIRECTION", None),
    ("Long TP", '=COUNTIFS(Trades!E2:E,"Long",Trades!J2:J,"TP")'),
    ("Long SL", '=COUNTIFS(Trades!E2:E,"Long",Trades!J2:J,"SL")'),
    ("Long TSL", '=COUNTIFS(Trades!E2:E,"Long",Trades!J2:J,"TSL")'),
    ("Short TP", '=COUNTIFS(Trades!E2:E,"Short",Trades!J2:J,"TP")'),
    ("Short SL", '=COUNTIFS(Trades!E2:E,"Short",Trades!J2:J,"SL")'),
    ("Short TSL", '=COUNTIFS(Trades!E2:E,"Short",Trades!J2:J,"TSL")'),

    # ── QUALITY ──────────────────────────────────────────────────────────────
    ("QUALITY", None),
    ("Avg Confidence", "=IFERROR(AVERAGE(Trades!N2:N),0)"),
    ('Auto-logged', '=COUNTIF(Trades!O2:O,"Auto-logged")'),
    ('Needs Review', '=COUNTIF(Trades!O2:O,"Needs Review")'),
    ("Best Trade (R)", "=MAX(Trades!H2:H)"),
    ("Worst Trade (R)", "=MIN(Trades!H2:H)"),

    # ── TRADE DURATION ───────────────────────────────────────────────────────
    # Handles formats: 5m, 1h20m, 1h 20m, 1h20, 20m
    ("TRADE DURATION", None),
    (
        "Avg Duration (min)",
        '=IFERROR(LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT(mins*(dur<>""))/SUMPRODUCT((dur<>"")*1)),0)',
    ),
    (
        "Win Rate < 5min",
        '=IFERROR(LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((Trades!H2:H>0)*(mins>0)*(mins<5))/SUMPRODUCT((mins>0)*(mins<5))),0)',
    ),
    (
        "Win Rate 5-10min",
        '=IFERROR(LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((Trades!H2:H>0)*(mins>=5)*(mins<10))/SUMPRODUCT((mins>=5)*(mins<10))),0)',
    ),
    (
        "Win Rate 10-20min",
        '=IFERROR(LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((Trades!H2:H>0)*(mins>=10)*(mins<20))/SUMPRODUCT((mins>=10)*(mins<20))),0)',
    ),
    (
        "Win Rate 20min+",
        '=IFERROR(LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((Trades!H2:H>0)*(mins>=20))/SUMPRODUCT((mins>=20))),0)',
    ),
    (
        "Trades < 5min",
        '=LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((mins>0)*(mins<5)))',
    ),
    (
        "Trades 5-10min",
        '=LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((mins>=5)*(mins<10)))',
    ),
    (
        "Trades 10-20min",
        '=LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((mins>=10)*(mins<20)))',
    ),
    (
        "Trades 20min+",
        '=LET(dur,Trades!F2:F,mins,IF(ISNUMBER(SEARCH("h",dur)),VALUE(LEFT(dur,SEARCH("h",dur)-1))*60+IFERROR(VALUE(MID(dur,SEARCH("h",dur)+1,LEN(dur)-SEARCH("h",dur)-1)),0),VALUE(SUBSTITUTE(dur,"m",""))),SUMPRODUCT((mins>=20)))',
    ),

    # ── BREAKDOWN BY ASSET ──────────────────────────────────────────────────
    ("BREAKDOWN BY ASSET", None),
    ("NQ Win Rate", '=IFERROR(COUNTIFS(Trades!C2:C,"NQ",Trades!H2:H,">"&0)/COUNTIF(Trades!C2:C,"NQ"),0)'),
    ("NQ Trades", '=COUNTIF(Trades!C2:C,"NQ")'),
    ("NQ Avg R:R", '=IFERROR(AVERAGEIF(Trades!C2:C,"NQ",Trades!H2:H),0)'),
    ("NQ Total PNL", '=SUMIF(Trades!C2:C,"NQ",Trades!K2:K)'),
    ("ES Win Rate", '=IFERROR(COUNTIFS(Trades!C2:C,"ES",Trades!H2:H,">"&0)/COUNTIF(Trades!C2:C,"ES"),0)'),
    ("ES Trades", '=COUNTIF(Trades!C2:C,"ES")'),
    ("ES Avg R:R", '=IFERROR(AVERAGEIF(Trades!C2:C,"ES",Trades!H2:H),0)'),
    ("ES Total PNL", '=SUMIF(Trades!C2:C,"ES",Trades!K2:K)'),
    ("GC Win Rate", '=IFERROR(COUNTIFS(Trades!C2:C,"GC",Trades!H2:H,">"&0)/COUNTIF(Trades!C2:C,"GC"),0)'),
    ("GC Trades", '=COUNTIF(Trades!C2:C,"GC")'),
    ("CL Win Rate", '=IFERROR(COUNTIFS(Trades!C2:C,"CL",Trades!H2:H,">"&0)/COUNTIF(Trades!C2:C,"CL"),0)'),
    ("CL Trades", '=COUNTIF(Trades!C2:C,"CL")'),

    # ── BREAKDOWN BY DIRECTION ───────────────────────────────────────────────
    ("BREAKDOWN BY DIRECTION", None),
    ("Long Win Rate", '=IFERROR(COUNTIFS(Trades!E2:E,"Long",Trades!H2:H,">"&0)/COUNTIF(Trades!E2:E,"Long"),0)'),
    ("Long Avg R:R", '=IFERROR(AVERAGEIF(Trades!E2:E,"Long",Trades!H2:H),0)'),
    ("Long Total PNL", '=SUMIF(Trades!E2:E,"Long",Trades!K2:K)'),
    ("Short Win Rate", '=IFERROR(COUNTIFS(Trades!E2:E,"Short",Trades!H2:H,">"&0)/COUNTIF(Trades!E2:E,"Short"),0)'),
    ("Short Avg R:R", '=IFERROR(AVERAGEIF(Trades!E2:E,"Short",Trades!H2:H),0)'),
    ("Short Total PNL", '=SUMIF(Trades!E2:E,"Short",Trades!K2:K)'),

    # ── BREAKDOWN BY MANAGEMENT STYLE ────────────────────────────────────────
    ("BREAKDOWN BY MANAGEMENT STYLE", None),
    ("Aggressive Trailing Win Rate", '=IFERROR(COUNTIFS(Trades!I2:I,"aggressive_trailing",Trades!H2:H,">"&0)/COUNTIF(Trades!I2:I,"aggressive_trailing"),0)'),
    ("Aggressive Trailing Trades", '=COUNTIF(Trades!I2:I,"aggressive_trailing")'),
    ("Fixed TP/SL Win Rate", '=IFERROR(COUNTIFS(Trades!I2:I,"fixed_tp_sl",Trades!H2:H,">"&0)/COUNTIF(Trades!I2:I,"fixed_tp_sl"),0)'),
    ("Fixed TP/SL Trades", '=COUNTIF(Trades!I2:I,"fixed_tp_sl")'),
    ("Hybrid Win Rate", '=IFERROR(COUNTIFS(Trades!I2:I,"hybrid",Trades!H2:H,">"&0)/COUNTIF(Trades!I2:I,"hybrid"),0)'),
    ("Hybrid Trades", '=COUNTIF(Trades!I2:I,"hybrid")'),

    # ── BREAKDOWN BY ACCOUNT TYPE ────────────────────────────────────────────
    ("BREAKDOWN BY ACCOUNT TYPE", None),
    ("Funded Win Rate", '=IFERROR(COUNTIFS(Trades!D2:D,"funded",Trades!H2:H,">"&0)/COUNTIF(Trades!D2:D,"funded"),0)'),
    ("Funded Trades", '=COUNTIF(Trades!D2:D,"funded")'),
    ("Funded Avg R:R", '=IFERROR(AVERAGEIF(Trades!D2:D,"funded",Trades!H2:H),0)'),
    ("Funded Total PNL", '=SUMIF(Trades!D2:D,"funded",Trades!K2:K)'),
    ("Demo Win Rate", '=IFERROR(COUNTIFS(Trades!D2:D,"demo",Trades!H2:H,">"&0)/COUNTIF(Trades!D2:D,"demo"),0)'),
    ("Demo Trades", '=COUNTIF(Trades!D2:D,"demo")'),
    ("Demo Avg R:R", '=IFERROR(AVERAGEIF(Trades!D2:D,"demo",Trades!H2:H),0)'),
    ("Demo Total PNL", '=SUMIF(Trades!D2:D,"demo",Trades!K2:K)'),
    ("Eval Win Rate", '=IFERROR(COUNTIFS(Trades!D2:D,"eval",Trades!H2:H,">"&0)/COUNTIF(Trades!D2:D,"eval"),0)'),
    ("Eval Trades", '=COUNTIF(Trades!D2:D,"eval")'),
    ("Eval Avg R:R", '=IFERROR(AVERAGEIF(Trades!D2:D,"eval",Trades!H2:H),0)'),
    ("Eval Total PNL", '=SUMIF(Trades!D2:D,"eval",Trades!K2:K)'),
]


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS TAB — reference sheet for valid header values
# ══════════════════════════════════════════════════════════════════════════════

OPTIONS_LAYOUT: list[list[str]] = [
    # Header,              Type,      Possible Values / Format
    ["HEADER",             "TYPE",    "POSSIBLE VALUES / FORMAT"],
    ["",                   "",        ""],
    ["video_link",         "URL",     "https://youtu.be/{video_id}?t={seconds}"],
    ["time_offset",        "Time",    "HH:MM:SS  (e.g. 0:20:30)"],
    ["asset",              "String",  "NQ, ES, GC, CL, or any futures symbol"],
    ["account_type",       "Enum",    "funded | demo | eval"],
    ["direction",          "Enum",    "Long | Short"],
    ["trade_duration",     "Duration", "5m | 1h20m | 1h 20m | 1h20 | 20m  (supports hours+minutes)"],
    ["rr_planned",         "Float",   "2.5, 3.0, null  (planned risk-reward)"],
    ["rr_realized",        "Float",   "-1.0, 2.5, null  (NEGATIVE=loss, POSITIVE=win)"],
    ["management_style",   "Enum",    "aggressive_trailing | fixed_tp_sl | hybrid"],
    ["TP/SL",              "Enum",    "TP | SL | TSL  (TP=take-profit, SL=hard stop, TSL=trailing stop)"],
    ["PNL",                "Float",   "-150.00, 250.00  (dollar P&L, 2 decimal places)"],
    ["emotions",           "List",    "calm, confident, anxious, greedy, fearful, FOMO, etc."],
    ["confluences",        "List",    "FVG, order block, liquidity sweep, SMT confirmed, etc."],
    ["confidence",         "Float",   "0.00 - 1.00  (how confident the extraction is)"],
    ["status",             "Enum",    "Auto-logged | Needs Review  (auto-set by confidence threshold)"],
    ["notes",              "String",  "Free text — any extra context"],
    ["video_id",           "String",  "YouTube video ID (e.g. abc123XYZ)"],
    ["",                   "",        ""],
    ["── DURATION FORMAT REFERENCE ──", "", ""],
    ["5m",                 "=5 min",  "20 minutes"],
    ["20m",                "=20 min", "20 minutes"],
    ["1h20m",              "=80 min", "1 hour 20 minutes"],
    ["1h 20m",             "=80 min", "1 hour 20 minutes (with space)"],
    ["1h20",               "=80 min", "1 hour 20 minutes (no m suffix)"],
    ["2h",                 "=120 min","2 hours exactly"],
    ["",                   "",        ""],
    ["── PNL FORMAT ──", "", ""],
    ["PNL values",         "Float",   "Always 2 decimal places: 250.00, -125.50, 0.00"],
    ["",                   "",        ""],
    ["── RR_REALIZED RULES ──", "", ""],
    ["Win (TP hit)",       "Positive", "2.5, 3.0, 1.5  (must be > 0)"],
    ["Loss (SL hit)",      "Negative", "-1.0, -2.0, -0.5  (must be < 0)"],
    ["Loss (TSL hit)",     "Negative", "-0.5, -0.25  (trailing stop, usually smaller loss)"],
]


# ══════════════════════════════════════════════════════════════════════════════
# SHEET OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _get_client():
    """Authenticate and return a gspread client."""
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(GOOGLE_SHEETS_CREDS), SCOPE)
    return gspread.authorize(creds)


def _build_metrics_rows() -> list[list[str]]:
    """Build the full rows for the Metrics tab."""
    rows = []
    for label, formula in METRICS_LAYOUT:
        if formula is None:
            rows.append([label, ""])
        else:
            rows.append([label, formula])
    return rows


def ensure_metrics_tab(spreadsheet_name: str = SPREADSHEET_NAME, force: bool = False) -> None:
    """Create the Metrics tab with live formulas.

    Skips if tab already exists (unless force=True).
    Formulas auto-update when Trades data changes — no re-run needed.
    """
    client = _get_client()
    try:
        ss = client.open(spreadsheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Spreadsheet '{spreadsheet_name}' not found.", file=sys.stderr)
        return

    # Skip if already exists (unless force recreate)
    if not force:
        try:
            existing = ss.worksheet(METRICS_TAB)
            print(f"  '{METRICS_TAB}' tab already exists. Skipping creation. Use --force to recreate.")
            return
        except gspread.exceptions.WorksheetNotFound:
            pass

    # Delete existing if force
    if force:
        try:
            existing = ss.worksheet(METRICS_TAB)
            ss.del_worksheet(existing)
            print(f"  Deleted existing '{METRICS_TAB}' tab.")
        except gspread.exceptions.WorksheetNotFound:
            pass

    # Create new tab
    rows = _build_metrics_rows()
    tab = ss.add_worksheet(title=METRICS_TAB, rows=len(rows) + 5, cols=2)
    tab.update(f"A1:B{len(rows)}", rows, value_input_option="USER_ENTERED")

    # Bold section headers
    header_rows = [i + 1 for i, (_, f) in enumerate(METRICS_LAYOUT) if f is None]
    if header_rows:
        tab.format(
            [f"A{r}:B{r}" for r in header_rows],
            {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}},
        )

    print(f"  Created '{METRICS_TAB}' tab with {len(rows)} rows ({len(header_rows)} section headers).")
    try:
        print(f"  URL: {tab.url}")
    except Exception:
        pass


def ensure_options_tab(spreadsheet_name: str = SPREADSHEET_NAME, force: bool = False) -> None:
    """Create the Options tab showing valid values for each header column.

    Skips if tab already exists (unless force=True).
    """
    client = _get_client()
    try:
        ss = client.open(spreadsheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Spreadsheet '{spreadsheet_name}' not found.", file=sys.stderr)
        return

    # Skip if already exists
    if not force:
        try:
            existing = ss.worksheet(OPTIONS_TAB)
            print(f"  '{OPTIONS_TAB}' tab already exists. Skipping creation. Use --force to recreate.")
            return
        except gspread.exceptions.WorksheetNotFound:
            pass

    # Delete existing if force
    if force:
        try:
            existing = ss.worksheet(OPTIONS_TAB)
            ss.del_worksheet(existing)
            print(f"  Deleted existing '{OPTIONS_TAB}' tab.")
        except gspread.exceptions.WorksheetNotFound:
            pass

    # Create new tab
    tab = ss.add_worksheet(title=OPTIONS_TAB, rows=len(OPTIONS_LAYOUT) + 5, cols=3)
    tab.update(f"A1:C{len(OPTIONS_LAYOUT)}", OPTIONS_LAYOUT, value_input_option="USER_ENTERED")

    # Bold header row
    tab.format("A1:C1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})

    # Bold section dividers
    for i, row in enumerate(OPTIONS_LAYOUT, 1):
        if row[0].startswith("──"):
            tab.format(f"A{i}:C{i}", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}})

    print(f"  Created '{OPTIONS_TAB}' tab with {len(OPTIONS_LAYOUT)} rows.")
    try:
        print(f"  URL: {tab.url}")
    except Exception:
        pass


def setup_all_tabs(spreadsheet_name: str = SPREADSHEET_NAME, force: bool = False) -> None:
    """Create both Metrics and Options tabs. Called once during pipeline setup."""
    print("\nSetting up Metrics & Options tabs...")
    ensure_metrics_tab(spreadsheet_name, force=force)
    ensure_options_tab(spreadsheet_name, force=force)
    _format_trades_tab(spreadsheet_name)


def _format_trades_tab(spreadsheet_name: str = SPREADSHEET_NAME) -> None:
    """Format the Trades tab: widen Notes column (P) and enable text wrapping."""
    client = _get_client()
    try:
        ss = client.open(spreadsheet_name)
        tab = ss.worksheet("Trades")
    except Exception:
        return

    sheet_id = tab.id

    # Resize column P (index 15) to 400px and enable wrap
    ss.batch_update({
        "requests": [
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 15, "endIndex": 16},
                    "properties": {"pixelSize": 400},
                    "fields": "pixelSize",
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 15, "endColumnIndex": 16},
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 11, "endColumnIndex": 13},
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            },
        ]
    })

    print("  Formatted Trades tab: Notes column (P) widened + text wrap enabled.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create/update the Metrics and Options tabs in Google Sheets.")
    parser.add_argument("--spreadsheet", default=SPREADSHEET_NAME, help="Google Sheets title")
    parser.add_argument("--force", action="store_true", help="Delete and recreate existing tabs")
    parser.add_argument("--metrics-only", action="store_true", help="Only update Metrics tab")
    parser.add_argument("--options-only", action="store_true", help="Only update Options tab")
    args = parser.parse_args()

    if args.metrics_only:
        ensure_metrics_tab(args.spreadsheet, force=args.force)
    elif args.options_only:
        ensure_options_tab(args.spreadsheet, force=args.force)
    else:
        setup_all_tabs(args.spreadsheet, force=args.force)
