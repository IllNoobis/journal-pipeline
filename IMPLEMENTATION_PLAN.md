# Trading Journal Automation — Implementation Plan (v2)
### OBS → YouTube (upload + host + free transcription) → LLM Extraction → Google Sheets

This supersedes the earlier version of this plan. **The old local Whisper + Notion + Filesystem-MCP pipeline is dropped entirely** — not extended, not run in parallel. Everything here is one self-contained pipeline built around YouTube as the upload/transcription layer and Google Sheets as the destination.

---

## 1. Architecture

```
[1] OBS records .mp4
        │
[2] upload_to_youtube.py — automated upload, privacyStatus="unlisted"
        │   (YouTube Data API v3, resumable upload, OAuth2 user credentials)
        │
[3] wait_for_captions.py — polls YouTube for auto-caption readiness
        │
[4] fetch_transcript.py — pulls transcript via youtube-transcript-api v1.2.4
        │
[5] extract_trades.py — two-pass Claude Haiku 4.5 call
        │   Pass 1: segment transcript into actual / theoretical / backtest windows
        │   Pass 2: structured extraction (Pydantic-enforced) on actual windows only
        │
[6] log_to_sheets.py — gspread append, deduped against processed_videos.json
        │
[7] Google Sheet row includes a YouTube deep-link (?t=seconds) to the exact trade moment
```

Everything is driven by one orchestrator, `run_pipeline.py`, that chains steps 2–6 end to end from a single `.mp4` input.

---

## 2. What's New vs. the Original Blueprints

The two source documents you supplied assumed you'd **manually** upload to YouTube. This version automates that step too, since you asked for the full "upload it as unlisted and stuff" to be part of the pipeline, not a manual chore.

Also corrected against current library behavior (verified against PyPI, Jan 2026 release):

- **`youtube-transcript-api` is now class/instance-based**, not static methods. Current usage:
  ```python
  from youtube_transcript_api import YouTubeTranscriptApi
  ytt_api = YouTubeTranscriptApi()
  fetched = ytt_api.fetch(video_id, languages=["en"])
  # fetched is a FetchedTranscript — iterable, indexable, has .to_raw_data()
  ```
  The old `YouTubeTranscriptApi.get_transcript(...)` static call from the uploaded blueprint is deprecated-style and should not be used.
- **IP-block risk exists** for this library (`RequestBlocked` / `IpBlocked` exceptions) — YouTube blocks cloud-provider IPs and can rate-limit heavy self-hosted use. Running from your home/residential IP on the Windows machine should be fine at your volume, but the build includes a fallback hook for a proxy config (Webshare) in case you ever hit it.
- **Model:** use `claude-haiku-4-5-20251001`, not the 3.x Haiku IDs from the original docs.
- **Structured outputs API shape:** confirm current syntax against Anthropic's docs at build time — this surface moves; treat any `.parse()`/`response_format` call as a sketch to verify, not a final signature.

---

## 3. Directory Layout

```
C:\Users\illnoobis\Documents\general-ai\Claude-flow-setup\journal-pipeline\
├── run_pipeline.py
├── upload_to_youtube.py
├── wait_for_captions.py
├── fetch_transcript.py
├── extract_trades.py
├── log_to_sheets.py
├── state.py                    (idempotency / processed_videos.json helpers)
├── config.py                   (env + constants)
├── schemas.py                  (Pydantic models)
├── client_secret.json          (YouTube OAuth client — gitignored)
├── youtube_token.json          (cached OAuth token — gitignored, auto-created)
├── google_credentials.json     (Sheets service account — gitignored)
├── .env                        (ANTHROPIC_API_KEY, SPREADSHEET_NAME — gitignored)
├── processed_videos.json       (idempotency log — gitignored, auto-created)
├── uploads\                    (source .mp4s dropped here)
└── logs\
```

---

## 4. Credential Setup (two separate Google auth paths — important)

YouTube upload and Google Sheets writes use **different auth models**, don't conflate them:

- **Sheets:** service account (`google_credentials.json`), shared as Editor on the target sheet. No user interaction needed once set up.
- **YouTube upload:** must be **OAuth2 user credentials** (`client_secret.json` from a Desktop app OAuth client in Google Cloud Console), because a service account cannot upload to a personal YouTube channel. First run opens a browser consent screen once; token is cached to `youtube_token.json` and auto-refreshed after that.

Steps:
1. Google Cloud Console → same project as before → enable **YouTube Data API v3**, **Sheets API**, **Drive API**.
2. Credentials → **OAuth client ID** → Application type: Desktop app → download as `client_secret.json`.
3. OAuth consent screen → add your own Google account as a **Test user** (avoids needing app verification since this is single-user/personal use).
4. Credentials → **Service account** → download key → `google_credentials.json` → share target Sheet with its email as Editor.
5. `.gitignore`: `client_secret.json`, `youtube_token.json`, `google_credentials.json`, `.env`, `processed_videos.json`. This repo is Discord/OpenCode-bridged to GitHub — treat every one of these as a leak risk, not a formality.

---

## 5. Pipeline Stages

### Stage 1 — Upload to YouTube (unlisted)
See `features/02-youtube-upload.md`. Resumable upload via `googleapiclient`, `status.privacyStatus = "unlisted"`, title/description auto-generated from filename + timestamp.

### Stage 2 — Wait for captions
Poll YouTube for auto-caption readiness instead of a blind sleep timer. See `features/03-transcript-fetch.md`.

### Stage 3 — Fetch transcript
`youtube-transcript-api` v1.2.4, instance-based API, formatted into `[HH:MM:SS] text` lines.

### Stage 4 — Two-pass extraction
Pass 1 segments actual/theoretical/backtest windows; Pass 2 extracts structured trade records only from actual windows, enforced against a Pydantic schema. See `features/04-trade-extraction-llm.md`.

### Stage 5 — Log to Sheets
Idempotent append, dedupe by `(video_id, time_offset)`, confidence-gated `Auto-logged` / `Needs Review` status. See `features/05-google-sheets-logging.md` and `features/06-idempotency-state.md`.

---

## 6. Data Schema (Google Sheet Columns)

| Col | Field | Notes |
|---|---|---|
| A | `video_link` | Deep-linked to the exact trade timestamp |
| B | `time_offset` | HH:MM:SS |
| C | `asset` | NQ / ES / GC / CL, etc. |
| D | `direction` | Long / Short |
| E | `rr_planned` | float or blank |
| F | `rr_realized` | float or blank |
| G | `management_style` | aggressive_trailing / fixed_tp_sl / hybrid |
| H | `account_type` | funded / personal |
| I | `emotions` | comma-joined |
| J | `confluences` | comma-joined, merged vocabulary (see schema file) |
| K | `confidence` | 0.0–1.0 |
| L | `status` | Auto-logged / Needs Review |
| M | `notes` | one-sentence execution summary |
| N | `video_id` | needed for idempotency lookups |

---

## 7. Rollout Order

1. `features/01-config-and-setup.md` — env, dependencies, both Google auth paths
2. `features/02-youtube-upload.md` — upload automation
3. `features/03-transcript-fetch.md` — caption polling + transcript fetch
4. `features/04-trade-extraction-llm.md` — two-pass LLM extraction
5. `features/05-google-sheets-logging.md` — Sheets writer
6. `features/06-idempotency-state.md` — dedupe/state tracking
7. `features/07-orchestrator-cli.md` — `run_pipeline.py` wiring it all together
8. `features/08-testing-validation.md` — test plan before trusting it on a real session

Build in this order — each stage should run and be verified standalone via CLI before wiring into the orchestrator.

---

## 8. Explicitly Out of Scope (for now)

- No Notion, no local Whisper, no ffmpeg frame extraction — none of the old pipeline carries over.
- No Discord/OpenCode trigger yet — CLI-first. Discord integration is a clean follow-on once the CLI pipeline is proven, not part of this build.
- No visual/vision-based confirmation of low-confidence trades — audio-transcript-only for v1.
