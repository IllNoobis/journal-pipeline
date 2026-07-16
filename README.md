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

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/IllNoobis/journal-pipeline.git
cd journal-pipeline
pip install -r requirements.txt
```

### 2. Google Cloud Setup

**Create a project** at [Google Cloud Console](https://console.cloud.google.com/):

#### YouTube Data API (for upload)
1. Enable **YouTube Data API v3**
2. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Desktop app)
3. Download `client_secret.json` → place in project root
4. Go to **OAuth consent screen** → **Testing** → Add your Google email as test user

#### Google Sheets API (for logging)
1. Enable **Google Sheets API** + **Google Drive API**
2. Create a **Service Account** → download `google_credentials.json` → place in project root
3. Share your Google Sheet with the service account email (Editor access)

#### Gemini API (for extraction)
1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create an API key

### 3. Environment Variables

Create `.env` in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key
SPREADSHEET_NAME=Futures Trading Journal
SHEET_TAB=Trades
YOUTUBE_CHANNEL_TITLE_PREFIX=Session
CAPTION_POLL_INTERVAL_SECONDS=600
CAPTION_MAX_WAIT_MINUTES=90
CONFIDENCE_THRESHOLD=0.75
```

### 4. Create the Metrics Tab

```bash
python run_pipeline.py --metrics-only
```

This creates the Metrics and Options tabs with live formulas. Only needs to be done once — formulas auto-update when new trades are added.

### 5. Run the Pipeline

```bash
# Full pipeline (upload → transcript → extract → log)
python run_pipeline.bat "C:\path\to\session.mp4"

# Resume from a specific stage
python run_pipeline.bat --video-id VIDEO_ID --from-stage transcript

# Dry run (extract without writing to Sheets)
python run_pipeline.bat "C:\path\to\session.mp4" --dry-run

# Recreate Metrics tab
python run_pipeline.bat --metrics-only --force
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

## Configuration

### LLM Models

| Model | Role |
|---|---|
| `gemini-3.5-flash` | Primary extraction model |
| `gemini-3-flash-preview` | Auto-fallback if primary times out (15min) or returns 503 |

Configure timeout via `MODEL_TIMEOUT_MINUTES` in `.env` (default: 15).

### Free Tier Limits (Google AI Studio)

| Model | RPM | RPD | TPM |
|---|---|---|---|
| Gemini 3.5 Flash | 10 | 1,500 | 250K |
| Gemini 3 Flash | 10 | 1,500 | 250K |

### Sheet Layout

**Trades tab (A–Q):**

| Col | Header | Description |
|---|---|---|
| A | video_link | YouTube URL with timestamp |
| B | time_offset | Trade entry time (HH:MM:SS) |
| C | asset | NQ, ES, GC, CL, etc. |
| D | account_type | funded / demo / eval |
| E | direction | Long / Short |
| F | trade_duration | e.g. 5m, 1h20m |
| G | rr_planned | Planned R:R (calculated from TP/SL) |
| H | rr_realized | Realized R:R (+ wins, - losses) |
| I | management_style | aggressive_trailing / fixed_tp_sl / hybrid |
| J | TP/SL | TP / SL / TSL |
| K | PNL | Dollar profit/loss |
| L | emotions | Extracted emotions |
| M | confluences | Trading confluences |
| N | confidence | 0.0–1.0 extraction confidence |
| O | status | Auto-logged / Needs Review |
| P | notes | Free text |
| Q | video_id | YouTube video ID |

### Metrics Tab

Live formulas auto-calculate from the Trades tab:

- **Performance:** Win Rate, Profit Factor, Avg R:R, Expectancy
- **Risk:** Sharpe Ratio, Sortino Ratio, Max Drawdown, Calmar Ratio
- **Volume:** Total/Long/Short/Funded/Demo/Eval counts
- **TP/SL & PNL:** Hit rates, avg PNL by exit type, best/worst trades
- **Duration Analysis:** Win rates by duration bucket (<5m, 5-10m, 10-20m, 20m+)
- **Breakdowns:** By asset, direction, management style, account type

## Project Structure

```
journal-pipeline/
├── run_pipeline.py          # Main orchestrator
├── config.py                # Central config (loads .env)
├── schemas.py               # Pydantic trade models
├── state.py                 # Pipeline state tracking (processed_videos.json)
├── upload_to_youtube.py     # YouTube upload with OAuth
├── wait_for_captions.py     # Poll for YouTube auto-captions
├── fetch_transcript.py      # Fetch & format transcript
├── extract_trades.py        # Two-pass Gemini extraction
├── log_to_sheets.py         # Google Sheets logging
├── metrics_tab.py           # Metrics + Options tab creation
├── run_pipeline.bat         # Windows wrapper
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (git-ignored)
├── client_secret.json       # YouTube OAuth (git-ignored)
├── google_credentials.json  # Sheets service account (git-ignored)
├── youtube_token.json       # YouTube OAuth token (auto-generated)
├── processed_videos.json    # Pipeline state (auto-generated)
├── uploads/                 # Uploaded video files
└── logs/                    # Pipeline logs
    ├── pipeline.log         # Central log
    └── {video_id}_*.log     # Per-video logs
```

## State & Resume

The pipeline tracks progress in `processed_videos.json`. Each video moves through states:

```
uploaded → transcript_ready → extracted → logged
```

If the pipeline fails or is interrupted, re-running automatically resumes from the last successful stage. Use `--from-stage` to force a specific starting point.

**Deduplication:** Trades are deduped by `time_offset` within each video. Re-running won't create duplicates.

## Troubleshooting

### "Access blocked: not completed Google verification"
→ Add your email as a test user in Google Cloud Console → OAuth consent screen → Testing → Add Users

### Gemini 503 / timeout
→ Model auto-falls back to `gemini-3-flash-preview`. If both fail, wait and retry.

### CTRL+C not working
→ Run `taskkill /f /im python.exe` to force-kill, or use `run_pipeline.bat` (fixed in latest version).

### Captions not ready
→ YouTube can take 10-90 minutes to process captions for long videos. The pipeline polls every 10 minutes (configurable). Re-run with `--from-stage transcript` to retry.

### Duplicate rows in Sheets
→ Won't happen — `time_offset` dedup prevents re-logging the same trade.

## Tech Stack

- **Python 3.14+**
- **Google Gemini** — Trade extraction via structured output (`response_schema`)
- **Google Sheets API** — Trade logging + live metrics formulas
- **YouTube Data API v3** — Video upload + caption polling
- **Pydantic v2** — Structured extraction schemas
- **Two-pass LLM** — Segmentation → extraction for accuracy

## License

Private — not for distribution.
