"""
run_pipeline.py — Full orchestrator for the trading journal automation pipeline.

Chains: upload → wait for captions → fetch transcript → extract trades → log to sheets.
Resumable from any stage via state tracking.

Usage:
    python run_pipeline.py uploads/session_2026-07-14.mp4
    python run_pipeline.py uploads/session_2026-07-14.mp4 --from-stage extract
    python run_pipeline.py uploads/session_2026-07-14.mp4 --dry-run
    python run_pipeline.py --video-id abc123 --from-stage extract
"""
import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from config import (
    CAPTION_MAX_WAIT_MINUTES,
    CAPTION_POLL_INTERVAL_SECONDS,
    CONFIDENCE_THRESHOLD,
    LOGS_DIR,
    STATE_FILE,
    YOUTUBE_CHANNEL_TITLE_PREFIX,
    validate_creds_for,
)
import state

# Stage imports
import upload_to_youtube
from wait_for_captions import wait_for_captions
from fetch_transcript import format_transcript, save_transcript, fetch_and_format, YouTubeTranscriptApi
from extract_trades import extract_trades
import log_to_sheets


STAGES = ["upload", "transcript", "extract", "log"]
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


def _log_event(video_id: str, stage: str, message: str) -> None:
    """Append a timestamped line to the pipeline log file."""
    log_path = LOGS_DIR / f"{video_id}_pipeline.log"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [{stage.upper()}] {message}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"  {line.strip()}")


def _load_transcript(video_id: str) -> str:
    """Load a previously saved transcript from logs/."""
    path = LOGS_DIR / f"{video_id}_transcript.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Transcript not found at {path}. "
            "Run the transcript stage first or re-run from 'transcript'."
        )
    return path.read_text(encoding="utf-8")


def _load_trades(video_id: str) -> list:
    """Load previously saved trades from logs/."""
    path = LOGS_DIR / f"{video_id}_trades.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Trades not found at {path}. "
            "Run the extraction stage first or re-run from 'extract'."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    from schemas import Trade
    return [Trade(**item) for item in raw]


def _save_trades(video_id: str, trades: list) -> str:
    """Save trades to logs/{video_id}_trades.json. Returns path."""
    path = LOGS_DIR / f"{video_id}_trades.json"
    output_data = [t.model_dump() for t in trades]
    path.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def run_pipeline(
    source_file: str | None = None,
    video_id: str | None = None,
    from_stage: str | None = None,
    dry_run: bool = False,
) -> None:
    """Run the full pipeline end-to-end, resumable from any stage."""

    start_time = datetime.now(timezone.utc)
    force_stage_idx = STAGE_ORDER.get(from_stage, None) if from_stage else None

    # ── Stage 0: Resolve video_id ───────────────────────────────────────────
    if not video_id and source_file:
        source_path = Path(source_file).resolve()
        if not source_path.is_file():
            print(f"Error: file not found: {source_path}", file=sys.stderr)
            sys.exit(1)

        existing = state.find_by_source_file(STATE_FILE, str(source_path))
        if existing:
            print(f"File already uploaded as {existing}, resuming from there.")
            video_id = existing
        else:
            # Upload
            if force_stage_idx is not None and force_stage_idx > STAGE_ORDER["upload"]:
                print(f"Error: --from-stage {from_stage} requires --video-id since upload hasn't happened.", file=sys.stderr)
                sys.exit(1)

            print("=" * 60)
            print("STAGE 1/4: UPLOAD TO YOUTUBE")
            print("=" * 60)
            validate_creds_for("youtube")
            try:
                from upload_to_youtube import build_title
                title = build_title(source_path)
                print(f"Title: {title}")
                print(f"File: {source_path}")

                youtube = upload_to_youtube.get_youtube_client()
                video_id = upload_to_youtube.upload_video(youtube, source_path, title)
                state.mark_uploaded(STATE_FILE, video_id, str(source_path))
                _log_event(video_id, "upload", f"Uploaded: https://youtu.be/{video_id}")
            except Exception as exc:
                _log_event(video_id or "unknown", "upload", f"FAILED: {exc}")
                raise

    if not video_id:
        print("Error: must provide either a source file or --video-id", file=sys.stderr)
        sys.exit(1)

    # Check state
    current = state.get_video_state(STATE_FILE, video_id) or {}
    current_status = current.get("status", "uploaded")

    # ── Stage 2: Wait for captions + fetch transcript ───────────────────────
    should_run_transcript = (
        force_stage_idx is not None and force_stage_idx <= STAGE_ORDER["transcript"]
    ) or (
        force_stage_idx is None and current_status in ("uploaded",)
    )

    if should_run_transcript:
        print("\n" + "=" * 60)
        print("STAGE 2/4: WAIT FOR CAPTIONS + FETCH TRANSCRIPT")
        print("=" * 60)
        try:
            validate_creds_for("youtube")  # needed for youtube-transcript-api indirectly
            ytt_api = YouTubeTranscriptApi()
            raw = wait_for_captions(
                video_id,
                poll_interval_s=CAPTION_POLL_INTERVAL_SECONDS,
                max_wait_minutes=CAPTION_MAX_WAIT_MINUTES,
                ytt_api=ytt_api,
            )
            formatted = format_transcript(raw)
            save_transcript(video_id, formatted)
            state.mark_transcript_ready(STATE_FILE, video_id)
            current_status = "transcript_ready"
            _log_event(video_id, "transcript", f"Saved {len(formatted)} chars")
        except Exception as exc:
            _log_event(video_id, "transcript", f"FAILED: {exc}")
            raise

    # ── Stage 3: Two-pass extraction ────────────────────────────────────────
    should_run_extract = (
        force_stage_idx is not None and force_stage_idx <= STAGE_ORDER["extract"]
    ) or (
        force_stage_idx is None and current_status in ("uploaded", "transcript_ready")
    )

    trades = []
    if should_run_extract:
        print("\n" + "=" * 60)
        print("STAGE 3/4: TWO-PASS LLM EXTRACTION")
        print("=" * 60)
        try:
            transcript = _load_transcript(video_id)
            trades = extract_trades(transcript)
            _save_trades(video_id, trades)
            state.mark_extracted(STATE_FILE, video_id)
            current_status = "extracted"
            _log_event(video_id, "extract", f"Extracted {len(trades)} trades")
        except Exception as exc:
            _log_event(video_id, "extract", f"FAILED: {exc}")
            raise
    else:
        # Load existing trades if we skipped extraction
        try:
            trades = _load_trades(video_id)
        except FileNotFoundError:
            pass

    # ── Stage 4: Log to Google Sheets ───────────────────────────────────────
    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — SKIPPING SHEETS WRITE")
        print("=" * 60)
        for t in trades:
            status = "Auto-logged" if t.confidence >= CONFIDENCE_THRESHOLD else "Needs Review"
            print(f"  [{t.time_offset}] {t.asset} {t.direction} conf={t.confidence:.2f} → {status}")
    else:
        should_run_log = (
            force_stage_idx is not None and force_stage_idx <= STAGE_ORDER["log"]
        ) or (
            force_stage_idx is None and current_status in ("uploaded", "transcript_ready", "extracted")
        )

        if should_run_log:
            print("\n" + "=" * 60)
            print("STAGE 4/4: LOG TO GOOGLE SHEETS")
            print("=" * 60)
            try:
                from config import GOOGLE_SHEETS_CREDS, SPREADSHEET_NAME, SHEET_TAB, STATE_FILE
                validate_creds_for("sheets")
                already = state.already_logged_offsets(STATE_FILE, video_id)
                sheet = log_to_sheets.get_sheet(GOOGLE_SHEETS_CREDS, SPREADSHEET_NAME, SHEET_TAB)
                rows_added = log_to_sheets.log_trades(sheet, trades, video_id, already)
                state.mark_logged(STATE_FILE, video_id, [t.time_offset for t in trades])
                _log_event(video_id, "log", f"Added {rows_added} rows to sheet")
            except Exception as exc:
                _log_event(video_id, "log", f"FAILED: {exc}")
                raise

    # ── Summary ─────────────────────────────────────────────────────────────
    elapsed = datetime.now(timezone.utc) - start_time
    auto = sum(1 for t in trades if t.confidence >= CONFIDENCE_THRESHOLD)
    review = len(trades) - auto

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    if dry_run:
        print(f"[DRY RUN] Would log {len(trades)} trades ({auto} auto, {review} needs review)")
    else:
        try:
            from config import SPREADSHEET_NAME
            sheet_url = f"https://docs.google.com/spreadsheets/d/{_get_sheet_id(video_id)}"
        except Exception:
            sheet_url = "<set up Google Sheet first>"
        print(f"Logged {len(trades)} trades ({auto} auto, {review} needs review)")

    print(f"Video: https://youtu.be/{video_id}")
    print(f"Elapsed: {elapsed}")
    print(f"Logs: {LOGS_DIR / f'{video_id}_pipeline.log'}")


def _get_sheet_id(video_id: str) -> str:
    """Attempt to get the sheet ID from the state or config."""
    # This is a placeholder — the real URL comes from gspread
    return "SPREADSHEET_ID"


def main():
    parser = argparse.ArgumentParser(
        description="Run the full trading journal automation pipeline."
    )
    parser.add_argument(
        "video",
        nargs="?",
        type=Path,
        help="Path to the .mp4 file to process.",
    )
    parser.add_argument(
        "--video-id",
        help="Skip upload — use this existing YouTube video ID.",
    )
    parser.add_argument(
        "--from-stage",
        choices=STAGES,
        help="Force-start from a specific stage (overrides auto-resume).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run through extraction but don't write to Google Sheets.",
    )
    args = parser.parse_args()

    if not args.video and not args.video_id:
        parser.error("Provide either a video file path or --video-id.")

    source_file = str(args.video.resolve()) if args.video else None

    try:
        run_pipeline(
            source_file=source_file,
            video_id=args.video_id,
            from_stage=args.from_stage,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user. Re-run to resume from last successful stage.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        print("Check logs for details. Re-run to resume from the failed stage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
