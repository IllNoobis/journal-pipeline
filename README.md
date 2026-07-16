# Trading Journal Pipeline

Automated pipeline that processes trading session recordings → uploads to YouTube → fetches transcripts → extracts structured trade data via Gemini AI → logs to Google Sheets with live performance metrics.

## Architecture

```
.mp4 recording
    │
    ▼
┌─────────────────┐
│  1. UPLOAD       │  → YouTube (unlisted)
│  upload_to_youtube│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. TRANSCRIPT   │  → Polls for auto-captions, fetches text
│  wait_for_captions│
│  fetch_transcript │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. EXTRACT      │  → Gemini 3.5 Flash (two-pass LLM)
│  extract_trades  │     Pass 1: Segment trade windows
│                  │     Pass 2: Extract structured trades
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. LOG          │  → Google Sheets (deduped by time_offset)
│  log_to_sheets   │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  METRICS TAB     │  → Live formulas auto-calculate from Trades data
│  metrics_tab     │     No Python re-run needed
└─────────────────┘
```

## Prerequisites

- **Python 3.14+** (tested on 3.14.5)
- **Google Cloud account** (for YouTube + Sheets APIs)
- **Google AI Studio account** (for Gemini API key)
- **Windows** (currently; may work on other OS with adjustments)

---

## Full Account Setup

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Name it (e.g. `Trading Journal Pipeline`) → **Create**
4. Make sure the new project is selected in the dropdown

### Step 2: Enable Required APIs

In your new project, enable these APIs:

1. Go to **APIs & Services** → **Library**
2. Search for and enable each:
   - **YouTube Data API v3** (for video upload)
   - **Google Sheets API** (for trade logging)
   - **Google Drive API** (required by Sheets API)

### Step 3: YouTube OAuth2 Setup (for video upload)

This creates credentials that let the pipeline upload videos to your YouTube channel.

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth client ID**
3. If prompted, configure the **OAuth consent screen** first:
   - User type: **External** (or Internal if you have Google Workspace)
   - App name: `Trading Journal Pipeline` (or anything)
   - User support email: your email
   - Developer contact: your email
   - Save and continue through the steps
4. Back to **Credentials** → **+ Create Credentials** → **OAuth client ID**
5. Application type: **Desktop app**
6. Name: `Journal Pipeline` (or anything)
7. Click **Create**
8. **Download the JSON** (click the download icon next to your new client)
9. Rename the downloaded file to `client_secret.json`
10. Place it in the project root directory

**Add yourself as a test user:**

1. Go to **APIs & Services** → **OAuth consent screen**
2. Under **Testing**, click **Add Users**
3. Enter your Google email → **Add**
4. This lets you authenticate without Google verifying your app

### Step 4: Google Sheets Service Account Setup (for trade logging)

This creates a bot account that can write to your Google Sheet.

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **Service account**
3. Name: `sheet-writer` (or anything)
4. Click **Create and Continue**
5. Role: skip (leave blank) → **Continue**
6. Click **Done**
7. Click on the newly created service account
8. Go to **Keys** tab → **Add Key** → **Create new key**
9. Key type: **JSON** → **Create**
10. The JSON file downloads automatically
11. Rename it to `google_credentials.json`
12. Place it in the project root directory

**Note the service account email** (looks like `sheet-writer@your-project.iam.gserviceaccount.com`). You'll need it next.

### Step 5: Create Your Google Sheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Create a new spreadsheet
3. Name it `Futures Trading Journal` (or update `SPREADSHEET_NAME` in `.env`)
4. Rename the first tab to `Trades` (or update `SHEET_TAB` in `.env`)
5. **Share the sheet** with your service account email (from Step 4) as **Editor**
   - Click Share → enter the service account email → Editor access → Send

### Step 6: Gemini API Key (for trade extraction)

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **Create API Key**
4. Select your Google Cloud project (the one from Step 1)
5. Copy the generated API key

### Step 7: Clone & Install

```bash
git clone https://github.com/IllNoobis/journal-pipeline.git
cd journal-pipeline
pip install -r requirements.txt
```

### Step 8: Environment Variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
SPREADSHEET_NAME=Futures Trading Journal
SHEET_TAB=Trades
YOUTUBE_CHANNEL_TITLE_PREFIX=Session
CAPTION_POLL_INTERVAL_SECONDS=600
CAPTION_MAX_WAIT_MINUTES=90
CONFIDENCE_THRESHOLD=0.75
```

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Google AI Studio API key |
| `SPREADSHEET_NAME` | `Futures Trading Journal` | Name of your Google Sheet |
| `SHEET_TAB` | `Trades` | Tab name for trade data |
| `YOUTUBE_CHANNEL_TITLE_PREFIX` | `Session` | Prefix for uploaded video titles |
| `CAPTION_POLL_INTERVAL_SECONDS` | `600` | How often to check for captions (seconds) |
| `CAPTION_MAX_WAIT_MINUTES` | `90` | Max time to wait for captions |
| `CONFIDENCE_THRESHOLD` | `0.75` | Min confidence to auto-log (below = "Needs Review") |
| `MODEL_TIMEOUT_MINUTES` | `15` | Gemini API call timeout |

### Step 9: Create the Metrics Tab

```bash
python run_pipeline.py --metrics-only
```

This creates the **Metrics** and **Options** tabs with live formulas. Only needs to be done once — formulas auto-update when new trades are added.

### Step 10: Verify Credential Files

Make sure these files exist in the project root:

```
journal-pipeline/
├── client_secret.json         ← YouTube OAuth (from Step 3)
├── google_credentials.json    ← Sheets service account (from Step 4)
├── .env                       ← Environment variables (from Step 8)
```

### Step 11: First Run

```bash
python run_pipeline.py "C:\path\to\your\session.mp4"
```

On first run, a browser window opens for YouTube OAuth consent. After authorizing, the token is cached to `youtube_token.json` and auto-refreshes on future runs.

---

## Usage

### Full Pipeline

```bash
python run_pipeline.py "C:\path\to\session.mp4"
```

This runs all 4 stages: upload → wait for captions → extract trades → log to Sheets.

### Resume from a Specific Stage

```bash
# Skip upload, use existing YouTube video
python run_pipeline.py --video-id dQw4w9WgXcQ --from-stage transcript

# Re-extract from existing transcript
python run_pipeline.py --video-id dQw4w9WgXcQ --from-stage extract

# Re-log existing trades
python run_pipeline.py --video-id dQw4w9WgXcQ --from-stage log
```

### Dry Run (No Sheets Write)

```bash
python run_pipeline.py "C:\path\to\session.mp4" --dry-run
```

### Recreate Metrics Tab

```bash
# Create Metrics + Options tabs
python run_pipeline.py --metrics-only

# Force recreate if tabs already exist
python run_pipeline.py --metrics-only --force
```

### Individual Stages

Each stage can be run independently:

```bash
python upload_to_youtube.py "C:\path\to\session.mp4"
python wait_for_captions.py --video-id VIDEO_ID
python fetch_transcript.py --video-id VIDEO_ID
python extract_trades.py --transcript logs/VIDEO_ID_transcript.txt --out logs/VIDEO_ID_trades.json
python log_to_sheets.py --video-id VIDEO_ID --trades logs/VIDEO_ID_trades.json
python metrics_tab.py --force
```

### Windows Wrapper (Optional)

If you want to run `run_pipeline` from anywhere without typing `python run_pipeline.py`, create a wrapper script in a directory on your PATH:

```bat
@echo off
python "C:\path\to\journal-pipeline\run_pipeline.py" %*
```

Then you can run:
```bash
run_pipeline.bat "C:\path\to\session.mp4"
```

## CLI Reference

| Argument | Description |
|---|---|
| `video` (positional) | Path to `.mp4` file to process |
| `--video-id` | Skip upload — use existing YouTube video ID |
| `--from-stage` | Force-start from: `upload`, `transcript`, `extract`, `log` |
| `--dry-run` | Run extraction but skip Google Sheets write |
| `--metrics-only` | Recreate Metrics + Options tabs only |
| `--force` | Force-recreate existing tabs (use with `--metrics-only`) |

---

## Sheet Layout

### Trades Tab (Columns A–AP)

| Col | Header | Description |
|---|---|---|
| A | `video_link` | YouTube URL with timestamp (`?t=seconds`) |
| B | `trade_id` | Auto-generated (T001, T002, ...) |
| C | `date` | Trade date (YYYY-MM-DD) |
| D | `time_offset` | Trade entry time (HH:MM:SS) |
| E | `asset` | NQ, ES, GC, CL, etc. |
| F | `direction` | Long / Short |
| G | `session_phase` | NY open, NY AM, Post London, NY end |
| H | `htf_trend` | Bullish, Bearish, Range |
| I | `market_condition` | Trend_Day, Mean Reverting, Inside_Day |
| J | `key_level_reacted` | VAH, VAL, POC, PDH, PDL, VWAP, etc. |
| K | `account_type` | funded / demo / eval |
| L | `setup_type` | Delta-Divergence, Absorption-retest, etc. |
| M | `pace_of_tape` | Fast, Medium, Slow |
| N | `delta_at_entry` | Delta value at entry |
| O | `delta_divergence` | Yes / No |
| P | `stacked_imbalances` | Yes / No |
| Q | `absorption_present` | Yes / No |
| R | `confluences` | Comma-separated confluences |
| S | `emotions` | Comma-separated emotions |
| T | `planned_stop_ticks` | Planned stop distance (ticks) |
| U | `planned_target_ticks` | Planned target distance (ticks) |
| V | `rr_planned` | Planned R:R (auto-calculated) |
| W | `entry_price` | Entry price |
| X | `exit_price` | Exit price |
| Y | `contracts_traded` | Number of contracts |
| Z | `rr_realized` | Realized R:R (+ wins, - losses) |
| AA | `trade_exit` | TP / SL / TSL |
| AB | `trade_duration` | e.g. 5m, 1h20m |
| AC | `management_style` | aggressive_trailing / fixed_tp_sl / hybrid |
| AD | `gross_pnl` | Gross profit/loss |
| AE | `net_pnl` | Net profit/loss |
| AF | `exit_reason` | Hit_Target, Hit_Stop, Manual_Panic, etc. |
| AG | `rule_followed` | Yes / No |
| AH | `mistake_type` | None, FOMO_Entry, Early_Exit, etc. |
| AI | `execution_grade` | A / B / C |
| AJ | `mae_ticks` | Max adverse excursion (ticks) |
| AK | `mfe_ticks` | Max favorable excursion (ticks) |
| AL | `screenshot_link` | Screenshot URL |
| AM | `confidence` | Extraction confidence (0.0–1.0) |
| AN | `status` | Auto-logged (≥0.75) / Needs Review |
| AO | `notes` | Free text notes |
| AP | `video_id` | YouTube video ID |

### Valid Values Reference

**Setup Types:** Delta-Divergence, Absorption-retest, taking-of-control, FVG-fill, order-block-retest, liquidity-sweep, SMT-confirmation, POC-bounce, VAL-reversal, VAH-reversal

**Session Phases:** NY open, NY AM, Post London, NY end

**HTF Trends:** Bullish, Bearish, Range

**Market Conditions:** Trend_Day, Mean Reverting, Inside_Day

**Key Levels:** VAH, VAL, POC, PD VAH, PD VAL, PD POC, PDH, PDL, VWAP, Single_Print, Shelf, LVN, HVN, None

**Exit Reasons:** Hit_Target, Hit_Stop, Trailing_Stop, Manual_Panic, Manual_Target_Cut, Time_Stop

**Mistake Types:** None, FOMO_Entry, Early_Exit, Late_Entry, Moved_Stop, Revenge_Trade

**Confluences:** OR break, 0.618 retrace, unfinished UAL, unfinished UAH, FVG, order block, RVOL gate, LVN pullback, VAH/VAL reversal, liquidity sweep, absorption, SMT confirmed, POC, HVN, imbalance, delta divergence

### Metrics Tab

Live formulas auto-calculate from the Trades tab:

- **Performance:** Win Rate, Profit Factor, Avg R:R, Expectancy
- **Risk:** Sharpe Ratio, Sortino Ratio, Max Drawdown, Calmar Ratio, Equity Curve
- **Volume:** Total/Long/Short/Funded/Demo/Eval counts
- **TP/SL & PNL:** Hit rates, avg PNL by exit type, best/worst trades
- **Exit Type Breakdown:** Per exit type — avg R:R, win rate
- **Exit Type + Direction:** Cross-analysis
- **Quality:** Confidence distribution, auto-logged vs needs review
- **Duration Analysis:** Win rates by duration bucket (<5m, 5-10m, 10-20m, 20m+)
- **Breakdowns:** By asset, direction, management style, account type
- **Orderflow Analysis:** Per setup type, delta divergence, absorption
- **Trade Management:** MAE, MFE, stop/target distances
- **Behavioral:** Execution grades, rule following, mistake types
- **Context:** Session phase, market condition, HTF trend, key level breakdowns

### Options Tab

A reference sheet listing valid values for each column header. Useful as a quick reference when reviewing trades.

---

## LLM Configuration

| Model | Role |
|---|---|
| `gemini-3.5-flash` | Primary extraction model |
| `gemini-3-flash-preview` | Auto-fallback if primary times out (15min) or returns 503 |

### Free Tier Limits (Google AI Studio)

| Model | RPM | RPD | TPM |
|---|---|---|---|
| Gemini 3.5 Flash | 15 | 1,500 | 1M |
| Gemini 3 Flash | 15 | 1,500 | 1M |

**Two-pass extraction process:**
1. **Pass 1 — Segmentation:** Transcript is sent to Gemini to identify trade windows (actual vs theoretical vs backtest)
2. **Pass 2 — Extraction:** Each actual trade window is extracted into structured data with all 42 fields

---

## State & Resume

The pipeline tracks progress in `processed_videos.json`. Each video moves through states:

```
uploaded → transcript_ready → extracted → logged
```

If the pipeline fails or is interrupted, re-running automatically resumes from the last successful stage. Use `--from-stage` to force a specific starting point.

**Deduplication:** Trades are deduped by `time_offset` within each video. Re-running won't create duplicates.

---

## Project Structure

```
journal-pipeline/
├── run_pipeline.py          # Main orchestrator (entry point)
├── config.py                # Central config (loads .env)
├── schemas.py               # Pydantic trade models + vocabularies
├── state.py                 # Pipeline state tracking (processed_videos.json)
├── upload_to_youtube.py     # YouTube upload with OAuth
├── wait_for_captions.py     # Poll for YouTube auto-captions
├── fetch_transcript.py      # Fetch & format transcript
├── extract_trades.py        # Two-pass Gemini extraction
├── log_to_sheets.py         # Google Sheets logging
├── metrics_tab.py           # Metrics + Options tab creation
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (git-ignored)
├── client_secret.json       # YouTube OAuth (git-ignored)
├── google_credentials.json  # Sheets service account (git-ignored)
├── youtube_token.json       # YouTube OAuth token (auto-generated)
├── processed_videos.json    # Pipeline state (auto-generated)
├── uploads/                 # Uploaded video files
└── logs/                    # Pipeline logs + artifacts
    ├── pipeline.log         # Central log
    └── {video_id}_*         # Per-video logs, transcripts, trades JSON
```

---

## Troubleshooting

### "Access blocked: not completed Google verification"
→ Add your email as a test user in Google Cloud Console → OAuth consent screen → Testing → Add Users

### Gemini 503 / timeout
→ Model auto-falls back to `gemini-3-flash-preview`. If both fail, wait and retry. Check [status](https://ai.google.dev/gemini-api/docs/status).

### Captions not ready
→ YouTube can take 10-90 minutes to process captions for long videos. The pipeline polls every 10 minutes (configurable). Re-run with `--from-stage transcript` to retry.

### Duplicate rows in Sheets
→ Won't happen — `time_offset` dedup prevents re-logging the same trade.

### "Spreadsheet not found"
→ Make sure `SPREADSHEET_NAME` in `.env` matches your Google Sheet name exactly. Share the sheet with the service account email.

### "Tab not found"
→ Create a tab named `Trades` in your sheet, or update `SHEET_TAB` in `.env`.

### Service account permission denied
→ Share your Google Sheet with the service account email (found in `google_credentials.json`) as **Editor**.

### `processed_videos.json` corruption
→ Delete the file and re-run. The pipeline will re-process from scratch.

---

## Tech Stack

- **Python 3.14+**
- **Google Gemini** — Trade extraction via structured output (`response_schema`)
- **Google Sheets API** — Trade logging + live metrics formulas
- **YouTube Data API v3** — Video upload + caption polling
- **Pydantic v2** — Structured extraction schemas
- **Two-pass LLM** — Segmentation → extraction for accuracy

## License

Private — not for distribution.
