# Feature: Upload to YouTube (Unlisted)

## Goal
Take a local `.mp4`, upload it to YouTube as **unlisted**, return the `video_id`. Fully automated — no manual drag-and-drop step.

## File
`upload_to_youtube.py`

## Auth
OAuth2 **user credentials**, not a service account (service accounts can't upload to a personal channel).

- `client_secret.json` — Desktop app OAuth client, from `features/01-config-and-setup.md`.
- On first run: opens a local browser window via `google_auth_oauthlib.flow.InstalledAppFlow.run_local_server()`, requests scope `https://www.googleapis.com/auth/youtube.upload`.
- Cache the resulting credentials (including refresh token) to `youtube_token.json`. On subsequent runs, load and auto-refresh from that file — no repeated browser prompts.

## Core logic

```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os, json

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_youtube_client(client_secret_path, token_path):
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_video(youtube, file_path, title, description=""):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",  # People & Blogs; fine for unlisted personal use
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")
    return response["id"]  # this is the video_id
```

## Title/description convention
- Title: `"{YOUTUBE_CHANNEL_TITLE_PREFIX} - {filename stem} - {upload date YYYY-MM-DD}"`
- Description: auto-generated, e.g. `"Auto-uploaded trading session recording. Source file: {filename}. Uploaded by journal-pipeline."`

## CLI usage
```
python upload_to_youtube.py uploads/session_2026-07-14.mp4
```
Prints the resulting `video_id` and the watch URL (`https://youtu.be/{video_id}`), and writes both into `processed_videos.json` under a new entry with `status: "uploaded"` (see `06-idempotency-state.md`).

## Edge cases
- Resumable upload must survive a dropped connection mid-upload by retrying failed chunks (built into `MediaFileUpload`'s resumable flow — just make sure `next_chunk()` failures are caught and retried with backoff, not left to crash the whole run).
- Large files (2+ hour sessions): don't load the whole file into memory — `MediaFileUpload` streams from disk already, just confirm `chunksize=-1` (auto) behaves reasonably for your file sizes; if uploads are unreliable on your connection, fall back to a fixed chunk size (e.g. `1024*1024*10`).
- If a video with the same source filename was already uploaded (check `processed_videos.json`), warn and ask before re-uploading rather than silently creating a duplicate YouTube video.

## Acceptance check
Running the CLI against a short test clip produces a real unlisted YouTube video, visible in YouTube Studio under your channel, with `privacyStatus = unlisted` confirmed in the API response.
