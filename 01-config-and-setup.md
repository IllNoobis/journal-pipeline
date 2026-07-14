# Feature: Config & Setup

## Goal
One place for all credentials, constants, and environment config. No API keys or paths hardcoded in pipeline files.

## Files
- `.env` — secrets and per-user values
- `config.py` — loads `.env`, exposes typed constants
- `.gitignore` — covers every secret/generated file

## `.env` contents

```
ANTHROPIC_API_KEY=sk-ant-...
SPREADSHEET_NAME=Futures Trading Journal
SHEET_TAB=Trades
YOUTUBE_CHANNEL_TITLE_PREFIX=Session
CAPTION_POLL_INTERVAL_SECONDS=600
CAPTION_MAX_WAIT_MINUTES=90
CONFIDENCE_THRESHOLD=0.75
```

## `config.py` responsibilities
- Load `.env` via `python-dotenv`.
- Expose constants: `ANTHROPIC_API_KEY`, `SPREADSHEET_NAME`, `SHEET_TAB`, `MODEL_NAME = "claude-haiku-4-5-20251001"`, `CONFIDENCE_THRESHOLD`, `CAPTION_POLL_INTERVAL_SECONDS`, `CAPTION_MAX_WAIT_MINUTES`.
- Resolve absolute paths for: `UPLOADS_DIR`, `LOGS_DIR`, `STATE_FILE` (`processed_videos.json`), `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_TOKEN_FILE`, `GOOGLE_SHEETS_CREDS`.
- Fail loudly (raise, don't silently default) if `ANTHROPIC_API_KEY` or either Google credential file is missing when the module is first imported by a stage that needs it.

## Google Cloud Console setup (do this manually, once)

1. Create/reuse a project. Enable: **YouTube Data API v3**, **Google Sheets API**, **Google Drive API**.
2. **OAuth client for YouTube upload:**
   - Credentials → Create Credentials → OAuth client ID → Application type: **Desktop app**.
   - Download JSON → save as `client_secret.json` in project root.
   - OAuth consent screen → add your Google account under **Test users** (keeps it out of the app-verification process since it's single-user).
   - Required scope: `https://www.googleapis.com/auth/youtube.upload`
3. **Service account for Sheets:**
   - Credentials → Create Credentials → Service account → create → Keys → Add key → JSON.
   - Save as `google_credentials.json`.
   - Open your target Google Sheet → Share → add the service account's `...@...iam.gserviceaccount.com` email as **Editor**.
4. Create the target Sheet with tab name matching `SHEET_TAB`, header row matching the schema in `IMPLEMENTATION_PLAN.md` Section 6.

## `.gitignore`

```
client_secret.json
youtube_token.json
google_credentials.json
.env
processed_videos.json
logs/
__pycache__/
*.pyc
```

## Dependencies (`requirements.txt`)

```
youtube-transcript-api>=1.2.4
google-api-python-client
google-auth-oauthlib
google-auth-httplib2
gspread
oauth2client
anthropic
pydantic>=2
python-dotenv
```

## Acceptance check
`python -c "import config; print(config.MODEL_NAME)"` runs without error once `.env` and both credential files are in place, and raises a clear error message naming the missing file if one isn't.
