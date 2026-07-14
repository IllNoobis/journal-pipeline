"""
Fetch and format a YouTube transcript into [HH:MM:SS] text lines.
"""
import time as _time
import argparse

from youtube_transcript_api import YouTubeTranscriptApi

from config import LOGS_DIR
from wait_for_captions import wait_for_captions


def format_transcript(raw_snippets: list[dict]) -> str:
    """Convert raw snippet dicts into '[HH:MM:SS] text' lines."""
    lines = []
    for seg in raw_snippets:
        ts = _time.strftime("%H:%M:%S", _time.gmtime(seg["start"]))
        text = seg["text"].replace("\n", " ")
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def fetch_and_format(
    video_id: str,
    languages: list[str] | None = None,
    ytt_api: YouTubeTranscriptApi | None = None,
) -> tuple[list[dict], str]:
    """
    Single-fetch attempt. Returns (raw_snippets, formatted_string).
    Raises NoTranscriptFound if captions aren't ready yet.
    """
    if languages is None:
        languages = ["en"]
    if ytt_api is None:
        ytt_api = YouTubeTranscriptApi()

    fetched = ytt_api.fetch(video_id, languages=languages)
    raw = fetched.to_raw_data()
    formatted = format_transcript(raw)
    return raw, formatted


def save_transcript(video_id: str, formatted: str) -> str:
    """Save formatted transcript to logs/{video_id}_transcript.txt. Returns path."""
    path = LOGS_DIR / f"{video_id}_transcript.txt"
    path.write_text(formatted, encoding="utf-8")
    return str(path)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and format a YouTube video transcript."
    )
    parser.add_argument(
        "--video-id", required=True, help="YouTube video ID"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="If set, poll until captions are ready before fetching",
    )
    args = parser.parse_args()

    ytt_api = YouTubeTranscriptApi()

    if args.wait:
        print(f"Waiting for captions on {args.video_id}...")
        raw = wait_for_captions(args.video_id, ytt_api=ytt_api)
        if raw is None:
            return
        formatted = format_transcript(raw)
    else:
        try:
            raw, formatted = fetch_and_format(args.video_id, ytt_api=ytt_api)
        except Exception:
            print(f"Captions not ready for {args.video_id}. Re-run with --wait to poll.")
            return

    path = save_transcript(args.video_id, formatted)
    print(f"Transcript saved to {path}")
    print("--- Preview (first 500 chars) ---")
    print(formatted[:500])


if __name__ == "__main__":
    main()
