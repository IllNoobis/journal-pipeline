"""Google Sheets logging stage for automated trading journal.

Loads parsed trades from a JSON file, checks what's already been logged,
and appends new rows to the configured Google Sheet.
"""

import argparse
import json
import sys
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import CONFIDENCE_THRESHOLD, GOOGLE_SHEETS_CREDS, SHEET_TAB, SPREADSHEET_NAME, validate_creds_for
from schemas import Trade
from state import already_logged_offsets, mark_logged

# Valid values for TP/SL and status columns
VALID_TP_SL = {"TP", "SL", "TSL", ""}
VALID_STATUS = {"Auto-logged", "Needs Review"}

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEADER = [
    "video_link",       # A
    "time_offset",      # B
    "asset",            # C
    "account_type",     # D
    "direction",        # E
    "trade_duration",   # F
    "rr_planned",       # G
    "rr_realized",      # H
    "management_style", # I
    "TP/SL",            # J
    "PNL",              # K
    "emotions",         # L
    "confluences",      # M
    "confidence",       # N
    "status",           # O
    "notes",            # P
    "video_id",         # Q
]


def get_sheet(creds_path: Path, spreadsheet_name: str, tab_name: str):
    """Authenticate with a service account and return the target worksheet."""
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(creds_path), SCOPE)
    client = gspread.authorize(creds)
    return client.open(spreadsheet_name).worksheet(tab_name)


def time_to_seconds(t_str: str) -> int:
    """Convert 'H:MM:SS' offset string to total seconds."""
    h, m, s = map(int, t_str.split(":"))
    return h * 3600 + m * 60 + s


def trade_to_row(trade: Trade, video_id: str) -> list:
    """Convert a Trade model into a sheet row matching HEADER order.

    Validates TP/SL and status values before building the row.
    """
    seconds = time_to_seconds(trade.time_offset)
    video_link = f"https://youtu.be/{video_id}?t={seconds}"
    status = "Auto-logged" if trade.confidence >= CONFIDENCE_THRESHOLD else "Needs Review"

    # Validate TP/SL
    trade_exit = trade.trade_exit or ""
    if trade_exit and trade_exit not in VALID_TP_SL:
        print(f"  WARNING: Invalid TP/SL '{trade_exit}' at {trade.time_offset}, defaulting to empty")
        trade_exit = ""

    # Validate status
    if status not in VALID_STATUS:
        status = "Needs Review"

    # Auto-infer TP/SL from rr_realized if not set
    if not trade_exit and trade.rr_realized is not None:
        if trade.rr_realized > 0:
            trade_exit = "TP"
        elif trade.rr_realized < 0:
            trade_exit = "SL"

    return [
        video_link,         # A: video_link
        trade.time_offset,  # B: time_offset
        trade.asset,        # C: asset
        trade.account_type, # D: account_type
        trade.direction,    # E: direction
        trade.trade_duration or "",  # F: trade_duration
        trade.rr_planned,   # G: rr_planned
        trade.rr_realized,  # H: rr_realized
        trade.management_style,  # I: management_style
        trade_exit,         # J: TP/SL
        trade.pnl if trade.pnl is not None else "",  # K: PNL
        ", ".join(trade.emotions),   # L: emotions
        ", ".join(trade.confluences), # M: confluences
        trade.confidence,   # N: confidence
        status,             # O: status
        trade.notes,        # P: notes
        video_id,           # Q: video_id
    ]


def log_trades(sheet, trades: list[Trade], video_id: str, logged_offsets: set[str]) -> int:
    """Append un-logged trades to the sheet. Returns number of rows added."""
    rows_added = 0
    for trade in trades:
        if trade.time_offset in logged_offsets:
            continue
        sheet.append_row(trade_to_row(trade, video_id))
        logged_offsets.add(trade.time_offset)
        rows_added += 1
    return rows_added


def _ensure_header(sheet) -> None:
    """Verify the header row matches expected order; warn if mismatched."""
    existing = sheet.row_values(1)
    if existing != HEADER:
        print(
            f"WARNING: Sheet header mismatch.\n"
            f"  Expected: {HEADER}\n"
            f"  Found:    {existing}\n"
            "Rows will still be appended, but column order may be wrong.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Log parsed trades to Google Sheets")
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--trades", required=True, help="Path to trades JSON file")
    parser.add_argument(
        "--creds",
        default=str(GOOGLE_SHEETS_CREDS),
        help="Path to service account credentials JSON",
    )
    parser.add_argument("--spreadsheet", default=SPREADSHEET_NAME, help="Google Sheets title")
    parser.add_argument("--tab", default=SHEET_TAB, help="Sheet tab name")
    parser.add_argument("--state", default="state.json", help="Path to state file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be logged without writing"
    )
    args = parser.parse_args()

    creds_path = Path(args.creds)
    try:
        validate_creds_for("sheets")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    trades_path = Path(args.trades)
    if not trades_path.exists():
        print(f"ERROR: Trades file not found: {trades_path}", file=sys.stderr)
        sys.exit(1)

    with open(trades_path) as f:
        raw = json.load(f)
    trades = [Trade(**item) for item in raw]

    logged = already_logged_offsets(Path(args.state), args.video_id)
    total = len(trades)
    skipped = sum(1 for t in trades if t.time_offset in logged)
    to_log = total - skipped

    print(f"Trades loaded: {total} | Already logged: {skipped} | New: {to_log}")

    if to_log == 0:
        print("Nothing new to log.")
        return

    if args.dry_run:
        print("Dry run — no rows appended.")
        for trade in trades:
            if trade.time_offset not in logged:
                print(f"  Would log: {trade.time_offset} {trade.asset} {trade.direction}")
        return

    try:
        sheet = get_sheet(creds_path, args.spreadsheet, args.tab)
    except gspread.exceptions.SpreadsheetNotFound:
        print(
            f"ERROR: Spreadsheet '{args.spreadsheet}' not found. "
            "Make sure the name is correct and the service account has access.",
            file=sys.stderr,
        )
        sys.exit(1)
    except gspread.exceptions.WorksheetNotFound as e:
        print(
            f"ERROR: Tab '{args.tab}' not found in spreadsheet '{args.spreadsheet}'. "
            f"Available tabs: {[ws.title for ws in e.response]}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        error_str = str(e).lower()
        if "403" in error_str or "forbidden" in error_str or "permission" in error_str:
            print(
                "ERROR: Service account lacks access to this spreadsheet.\n"
                "Fix: Share the sheet with the service account email found in your "
                f"credentials file ({creds_path}).",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Failed to connect to Google Sheets: {e}", file=sys.stderr)
        sys.exit(1)

    _ensure_header(sheet)

    rows_added = log_trades(sheet, trades, args.video_id, logged)

    mark_logged(Path(args.state), args.video_id, list(logged))

    print(f"Added {rows_added} rows to {args.spreadsheet} → {args.tab} (skipped {skipped} already logged)")
    try:
        print(f"Sheet URL: {sheet.url}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
