# Claude Code Build Prompt

Paste everything below the line into Claude Code in the project directory to build the full pipeline.

---

I want you to build a complete Python automation pipeline that takes a recorded futures-trading session video, uploads it to YouTube as an unlisted video, pulls the auto-generated transcript, uses Claude to extract structured trade data, and logs each trade as a row in a Google Sheet.

Read `IMPLEMENTATION_PLAN.md` and every file in `features/` in this directory first — they are the full spec. Build in the order listed in `IMPLEMENTATION_PLAN.md` Section 7, and verify each stage runs standalone from the CLI before wiring it into the orchestrator.

## Hard requirements

- Python 3.11+, dependencies: `youtube-transcript-api>=1.2.4`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`, `gspread`, `oauth2client` (or migrate to `google-auth` for gspread if cleaner — your call), `anthropic`, `pydantic>=2`, `python-dotenv`.
- Use `youtube-transcript-api`'s **current instance-based API** (`YouTubeTranscriptApi().fetch(video_id, languages=["en"])`), not the deprecated static-method style. Confirm this against the installed package version at build time, not from memory.
- Use `claude-haiku-4-5-20251001` for LLM extraction calls.
- Before writing the Claude structured-output call, look up the current Anthropic Python SDK syntax for structured/JSON-schema-enforced output rather than assuming the exact method name — this API shape changes.
- YouTube upload must use **OAuth2 user credentials** (Desktop app client, `client_secret.json`), not a service account — service accounts cannot upload to a personal YouTube channel. Cache the token to `youtube_token.json` and auto-refresh.
- Google Sheets writes use a **separate service account** (`google_credentials.json`).
- Every credential/secret/token file must be gitignored — generate a `.gitignore` covering `client_secret.json`, `youtube_token.json`, `google_credentials.json`, `.env`, `processed_videos.json`, `logs/`.
- Idempotency: re-running the pipeline on a video already logged must not create duplicate rows. Dedupe key is `(video_id, time_offset)`.
- Two-pass LLM extraction: Pass 1 segments the transcript into `actual` / `theoretical` / `backtest` time windows; Pass 2 runs structured extraction only on `actual` windows. Do not combine these into one call.
- Confidence gating: trades with `confidence < 0.75` get `status = "Needs Review"` in the sheet, not silently dropped and not silently auto-logged.
- No hallucination: if the LLM can't ground a field (price, RR, etc.) in the transcript, it must leave it null/blank rather than invent a plausible-looking number. Bake this instruction directly into the extraction system prompt.
- CLI-first: every stage (`upload_to_youtube.py`, `fetch_transcript.py`, `extract_trades.py`, `log_to_sheets.py`) should be independently runnable with its own CLI args for testing, in addition to being importable by `run_pipeline.py`.
- Config (paths, sheet name, model name, polling intervals) lives in `config.py` / `.env`, not hardcoded across files.
- Logs go to `logs/` with timestamps — enough to debug a failed run without re-triggering API calls that already succeeded (e.g. don't re-upload a video just because the extraction step failed; the orchestrator should be resumable from any stage given a `video_id`).

## What NOT to build

- No Notion integration.
- No local Whisper / ffmpeg transcription or frame extraction.
- No Discord/OpenCode trigger — CLI only for this build.
- No vision/screenshot-based trade confirmation.

## Deliverable

A working `run_pipeline.py <path-to-mp4>` that:
1. Uploads the file to YouTube as unlisted {format of video title: DDMMYYYY HHMM <in IST>}
2. Waits for captions to be ready (polling, not a fixed sleep)
3. Fetches and formats the transcript
4. Runs two-pass extraction into validated trade objects
5. Appends new rows to the configured Google Sheet, skipping anything already logged for that `video_id`
6. Prints a summary: `Logged N trades (X auto, Y needs review) → <sheet URL>`

Ask me for my `SPREADSHEET_NAME`, target Sheet tab, and confirmation that I've completed the OAuth/service-account setup in `features/01-config-and-setup.md` before running anything that hits real APIs.
Also help me setup any requirements I may need. Ensure `run_pipeline.py <path-to-mp4>` is added to path so i can from anywhere run this.