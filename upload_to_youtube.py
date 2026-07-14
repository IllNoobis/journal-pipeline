"""
YouTube upload stage — uploads a local .mp4 to YouTube as unlisted.

CLI:
    python upload_to_youtube.py uploads/session_2026-07-14.mp4
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import (
    STATE_FILE,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_TOKEN_FILE,
    validate_creds_for,
)
import state

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
IST = timezone(timedelta(hours=5, minutes=30))
MAX_RETRIES = 5
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_youtube_client() -> object:
    """Build an authenticated YouTube API client, caching the token to disk."""
    validate_creds_for("youtube")

    creds = None
    token_path = Path(YOUTUBE_TOKEN_FILE)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(YOUTUBE_CLIENT_SECRET), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ── Title helpers ─────────────────────────────────────────────────────────────

def _mtime_to_ist(file_path: Path) -> datetime:
    """Return the file's modification time converted to IST."""
    mtime = file_path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=IST)


def build_title(file_path: Path) -> str:
    """Build the video title in DDMMYYYY HHMM format (IST)."""
    dt = _mtime_to_ist(file_path)
    return f"Session: {dt.strftime('%d-%m-%Y')} {dt.strftime('%H:%M')}"


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_video(youtube: object, file_path: Path, title: str) -> str:
    """Upload *file_path* to YouTube and return the video_id."""
    description = (
        f"Auto-uploaded trading session recording. "
        f"Source file: {file_path.name}. Uploaded by journal-pipeline."
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path), chunksize=-1, resumable=True, mimetype="video/mp4"
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    error = None
    retry = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  Upload progress: {int(status.progress() * 100)}%")
        except Exception as exc:
            if hasattr(exc, "resp") and getattr(exc, "resp", None) is not None:
                if exc.resp.status in RETRIABLE_STATUS_CODES:
                    error = exc
                else:
                    raise
            else:
                raise

            retry += 1
            if retry > MAX_RETRIES:
                raise RuntimeError(
                    f"Upload failed after {MAX_RETRIES} retries: {error}"
                )

            sleep_secs = 2 ** retry
            print(f"  Retrying in {sleep_secs}s (attempt {retry}/{MAX_RETRIES})...")
            time.sleep(sleep_secs)

    return response["id"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Upload a trading session .mp4 to YouTube (unlisted)."
    )
    parser.add_argument(
        "video",
        type=Path,
        help="Path to the .mp4 file to upload.",
    )
    args = parser.parse_args(argv)

    video_path: Path = args.video.resolve()
    if not video_path.is_file():
        print(f"Error: file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    # Idempotency check
    existing_id = state.find_by_source_file(STATE_FILE, str(video_path))
    if existing_id:
        print(f"Warning: {video_path.name} was already uploaded.")
        print(f"Existing video_id: {existing_id}")
        print(f"Watch URL: https://youtu.be/{existing_id}")
        sys.exit(0)

    title = build_title(video_path)
    print(f"Title:   {title}")
    print(f"File:    {video_path}")
    print(f"Privacy: unlisted")

    youtube = get_youtube_client()
    video_id = upload_video(youtube, video_path, title)

    state.mark_uploaded(STATE_FILE, video_id, str(video_path))

    print(f"\nUpload complete.")
    print(f"video_id: {video_id}")
    print(f"Watch URL: https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
