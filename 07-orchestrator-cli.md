# Feature: Orchestrator (`run_pipeline.py`)

## Goal
One command that runs the full chain end to end, resumable, with a clean summary at the end.

## CLI

```
python run_pipeline.py uploads/session_2026-07-14.mp4
```

Optional flags:
- `--video-id <id>` — skip upload entirely, run against an already-uploaded video.
- `--from-stage {upload,transcript,extract,log}` — force-start from a specific stage (overrides state-file auto-resume, for manual debugging).
- `--dry-run` — run through extraction and print what *would* be logged, without writing to Sheets.

## Flow

```python
def run_pipeline(source_file=None, video_id=None, from_stage=None, dry_run=False):
    # 1. Resolve video_id
    if not video_id:
        existing = state.find_by_source_file(STATE_FILE, source_file)
        if existing:
            print(f"File already uploaded as {existing}, resuming from there.")
            video_id = existing
        else:
            video_id = upload_to_youtube.upload_video(...)
            state.mark_uploaded(STATE_FILE, video_id, source_file)

    # 2. Transcript
    current = state.get_video_state(STATE_FILE, video_id)
    if current["status"] == "uploaded" or from_stage == "transcript":
        raw = wait_for_captions.wait_for_captions(video_id, ...)
        transcript = fetch_transcript.format_transcript(raw)
        save_transcript_to_log(video_id, transcript)
        state.mark_transcript_ready(STATE_FILE, video_id)

    # 3. Extraction
    if current["status"] in ("uploaded", "transcript_ready") or from_stage == "extract":
        transcript = load_transcript_from_log(video_id)
        trades = extract_trades.extract_trades(transcript)
        save_trades_to_log(video_id, trades)
        state.mark_extracted(STATE_FILE, video_id)

    # 4. Logging
    if not dry_run:
        trades = load_trades_from_log(video_id)
        already = state.already_logged_offsets(STATE_FILE, video_id)
        sheet = log_to_sheets.get_sheet(...)
        added = log_to_sheets.log_trades(sheet, trades, video_id, already)
        state.mark_logged(STATE_FILE, video_id, [t.time_offset for t in trades])

    # 5. Summary
    auto = sum(1 for t in trades if t.confidence >= CONFIDENCE_THRESHOLD)
    review = len(trades) - auto
    print(f"Logged {added} trades ({auto} auto, {review} needs review) → {sheet_url}")
```

(This is illustrative structure, not literal code to copy verbatim — build proper stage-skip logic driven by `state.py`, not a chain of loosely-related if-blocks.)

## Error handling
- Every stage's exceptions should be caught at the orchestrator level, logged to `logs/{video_id}_pipeline.log` with a timestamp and stage name, and re-raised with a clear message pointing at which stage failed and how to resume (`--from-stage` or just re-running, since state auto-resumes).
- Never let a failure in a later stage (e.g. Sheets write) trigger redoing an earlier expensive stage (upload, LLM extraction) — this is the entire point of the state file.

## Acceptance check
A full real run against a genuine trading session video, start to finish, unattended after kicking it off — including surviving the ~30-90 minute caption wait without needing you to babysit it.
