"""
Central configuration — loads .env, exposes typed constants, validates credential files exist.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API keys ────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

# ── Sheets config ───────────────────────────────────────────────────────────
SPREADSHEET_NAME: str = os.environ.get("SPREADSHEET_NAME", "Futures Trading Journal")
SHEET_TAB: str = os.environ.get("SHEET_TAB", "Trades")
METRICS_TAB: str = os.environ.get("METRICS_TAB", "Metrics")

# ── YouTube config ──────────────────────────────────────────────────────────
YOUTUBE_CHANNEL_TITLE_PREFIX: str = os.environ.get("YOUTUBE_CHANNEL_TITLE_PREFIX", "Session")

# ── LLM config ─────────────────────────────────────────────────────────────
MODEL_NAME: str = "gemini-3.5-flash"
MODEL_FALLBACK: str = "gemini-3-flash-preview"
MODEL_TIMEOUT_MINUTES: int = int(os.environ.get("MODEL_TIMEOUT_MINUTES", "15"))

# ── Caption polling ─────────────────────────────────────────────────────────
CAPTION_POLL_INTERVAL_SECONDS: int = int(os.environ.get("CAPTION_POLL_INTERVAL_SECONDS", "600"))
CAPTION_MAX_WAIT_MINUTES: int = int(os.environ.get("CAPTION_MAX_WAIT_MINUTES", "90"))

# ── Confidence gating ───────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD: float = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75"))

# ── Paths (relative to project root) ────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent
UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
STATE_FILE: Path = PROJECT_ROOT / "processed_videos.json"

YOUTUBE_CLIENT_SECRET: Path = PROJECT_ROOT / "client_secret.json"
YOUTUBE_TOKEN_FILE: Path = PROJECT_ROOT / "youtube_token.json"
GOOGLE_SHEETS_CREDS: Path = PROJECT_ROOT / "google_credentials.json"

# Ensure directories exist
UPLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


def validate_creds_for(feature: str) -> None:
    """Raise a clear error if credential files needed for *feature* are missing."""
    if feature == "youtube":
        if not YOUTUBE_CLIENT_SECRET.exists():
            raise FileNotFoundError(
                f"YouTube OAuth client secret not found at {YOUTUBE_CLIENT_SECRET}. "
                "Download it from Google Cloud Console → Credentials → OAuth client ID."
            )
    elif feature == "sheets":
        if not GOOGLE_SHEETS_CREDS.exists():
            raise FileNotFoundError(
                f"Google Sheets service account key not found at {GOOGLE_SHEETS_CREDS}. "
                "Download it from Google Cloud Console → Credentials → Service account."
            )
    elif feature == "all":
        validate_creds_for("youtube")
        validate_creds_for("sheets")
