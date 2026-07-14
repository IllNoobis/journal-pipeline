# Feature: Log Trades to Google Sheets

## Goal
Append each extracted trade as one row, deep-linked to the exact video moment, without duplicating rows on re-runs.

## File
`log_to_sheets.py`

## Auth
Service account (`google_credentials.json`), see `01-config-and-setup.md`. Separate from the YouTube OAuth flow — do not reuse credentials between the two.

## Core logic

```python
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_sheet(creds_path, spreadsheet_name, tab_name):
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, SCOPE)
    client = gspread.authorize(creds)
    return client.open(spreadsheet_name).worksheet(tab_name)

def time_to_seconds(t_str: str) -> int:
    h, m, s = map(int, t_str.split(":"))
    return h * 3600 + m * 60 + s

def trade_to_row(trade, video_id: str) -> list:
    seconds = time_to_seconds(trade.time_offset)
    video_link = f"https://youtu.be/{video_id}?t={seconds}"
    status = "Auto-logged" if trade.confidence >= CONFIDENCE_THRESHOLD else "Needs Review"
    return [
        video_link, trade.time_offset, trade.asset, trade.direction,
        trade.rr_planned, trade.rr_realized, trade.management_style,
        trade.account_type, ", ".join(trade.emotions), ", ".join(trade.confluences),
        trade.confidence, status, trade.notes, video_id,
    ]

def log_trades(sheet, trades, video_id, already_logged_offsets: set[str]):
    rows_added = 0
    for trade in trades:
        if trade.time_offset in already_logged_offsets:
            continue  # already logged this exact trade for this video — skip
        sheet.append_row(trade_to_row(trade, video_id))
        rows_added += 1
    return rows_added
```

`already_logged_offsets` comes from `state.py` (see `06-idempotency-state.md`) — the dedupe check happens **before** calling the Sheets API, not by reading the whole sheet back on every run (slower, and burns API quota for no reason).

## Sheet header row (create once, manually, matching column order exactly)

```
video_link | time_offset | asset | direction | rr_planned | rr_realized | management_style | account_type | emotions | confluences | confidence | status | notes | video_id
```

## CLI usage
```
python log_to_sheets.py --video-id abc123 --trades logs/abc123_trades.json
```

## Acceptance check
Running the CLI twice in a row against the same `--trades` file appends rows the first time and appends **zero** new rows the second time. Clicking a `video_link` cell opens the video within a couple seconds of the actual trade moment.
