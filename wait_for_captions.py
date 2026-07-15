"""
Polls YouTube for auto-caption readiness on a freshly uploaded video.
Uses the instance-based youtube-transcript-api.
"""
import logging
import time
import argparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    RequestBlocked,
    IpBlocked,
    VideoUnplayable,
    VideoUnavailable,
)

from config import (
    CAPTION_POLL_INTERVAL_SECONDS,
    CAPTION_MAX_WAIT_MINUTES,
    LOGS_DIR,
)

logger = logging.getLogger(__name__)


def wait_for_captions(
    video_id: str,
    poll_interval_s: int = CAPTION_POLL_INTERVAL_SECONDS,
    max_wait_minutes: int = CAPTION_MAX_WAIT_MINUTES,
    ytt_api: YouTubeTranscriptApi | None = None,
) -> list[dict] | None:
    """
    Poll until auto-captions are ready for *video_id*.

    Returns raw snippets list on success, or raises on fatal errors / timeout.
    Accepts an optional pre-configured YouTubeTranscriptApi instance so a
    proxy-enabled one can be swapped in later without touching call sites.
    """
    if ytt_api is None:
        ytt_api = YouTubeTranscriptApi()

    elapsed = 0
    max_seconds = max_wait_minutes * 60

    while elapsed < max_seconds:
        try:
            fetched = ytt_api.fetch(video_id, languages=["en"])
            return fetched.to_raw_data()
        except NoTranscriptFound:
            logger.info(
                "Captions not ready yet for %s, waiting %ds...", video_id, poll_interval_s
            )
            time.sleep(poll_interval_s)
            elapsed += poll_interval_s
        except VideoUnplayable as exc:
            reason = getattr(exc, "reason", "unknown")
            logger.info(
                "Video %s unplayable (%s), waiting %ds for processing...",
                video_id, reason, poll_interval_s,
            )
            time.sleep(poll_interval_s)
            elapsed += poll_interval_s
        except TranscriptsDisabled:
            raise RuntimeError(
                f"Captions disabled for video {video_id} — cannot proceed."
            )
        except VideoUnavailable:
            raise RuntimeError(
                f"Video {video_id} is no longer available — cannot fetch transcript."
            )
        except (RequestBlocked, IpBlocked):
            raise RuntimeError(
                "YouTube blocked this IP for transcript requests. "
                "Consider using a proxy — see proxy fallback in config."
            )

    raise TimeoutError(
        f"Captions not ready after {max_wait_minutes} minutes for video {video_id}. "
        "Check YouTube Studio manually — long sessions can occasionally take longer."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Poll YouTube until auto-captions are ready."
    )
    parser.add_argument(
        "--video-id", required=True, help="YouTube video ID to poll for"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CAPTION_POLL_INTERVAL_SECONDS,
        help=f"Seconds between polls (default: {CAPTION_POLL_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=CAPTION_MAX_WAIT_MINUTES,
        help=f"Max minutes to wait (default: {CAPTION_MAX_WAIT_MINUTES})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        raw = wait_for_captions(
            args.video_id,
            poll_interval_s=args.interval,
            max_wait_minutes=args.max_wait,
        )
        print(f"Captions ready for {args.video_id}")
        return raw
    except (RuntimeError, TimeoutError) as exc:
        print(f"Error: {exc}")
        return None


if __name__ == "__main__":
    main()
