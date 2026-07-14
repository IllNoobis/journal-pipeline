# Feature: Idempotency & Pipeline State

## Goal
Make the whole pipeline safely re-runnable at any stage without duplicating YouTube uploads, LLM calls, or Sheet rows.

## File
`state.py`, backed by `processed_videos.json`

## State file shape

```json
{
  "abc123": {
    "source_file": "uploads/session_2026-07-14.mp4",
    "status": "logged",
    "uploaded_at": "2026-07-14T18:02:11Z",
    "transcript_fetched_at": "2026-07-14T18:41:03Z",
    "extracted_at": "2026-07-14T18:41:40Z",
    "logged_at": "2026-07-14T18:41:55Z",
    "trade_offsets_logged": ["00:14:10", "00:26:50", "01:02:33"]
  }
}
```

`status` progresses through: `uploaded` → `transcript_ready` → `extracted` → `logged`. Each pipeline stage reads and updates this file so the orchestrator (`run_pipeline.py`) can resume from wherever a previous run stopped, given a `video_id` or source filename.

## API (`state.py`)

```python
import json, os
from datetime import datetime, timezone

def _load(state_path) -> dict: ...
def _save(state_path, data: dict) -> None: ...

def get_video_state(state_path, video_id) -> dict | None: ...
def find_by_source_file(state_path, source_file) -> str | None:
    """Return video_id if this exact source file was already uploaded, else None."""

def mark_uploaded(state_path, video_id, source_file) -> None: ...
def mark_transcript_ready(state_path, video_id) -> None: ...
def mark_extracted(state_path, video_id) -> None: ...
def mark_logged(state_path, video_id, offsets_logged: list[str]) -> None: ...

def already_logged_offsets(state_path, video_id) -> set[str]:
    state = get_video_state(state_path, video_id)
    return set(state.get("trade_offsets_logged", [])) if state else set()
```

## Rules the orchestrator must follow
- Before uploading, call `find_by_source_file` — if the exact source file was already uploaded, **ask before re-uploading** rather than silently creating a duplicate YouTube video.
- Before re-running extraction, if `status` is already `extracted` or `logged`, reuse the saved `logs/{video_id}_trades.json` instead of re-calling the LLM — save the tokens.
- Before logging, always pull `already_logged_offsets` and skip anything already present, even if `status` isn't yet `logged` (covers a partial-failure case where some rows made it into the Sheet before a crash).
- Any stage that fails should leave the state file in its last-successful state — never mark a stage complete until it actually succeeded.

## Acceptance check
Kill the pipeline mid-run (e.g. Ctrl+C during the extraction stage) and re-run `run_pipeline.py` on the same file — it should skip the already-completed upload and transcript-fetch stages and resume from extraction, without hitting the YouTube upload API a second time.
