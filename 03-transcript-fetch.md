# Feature: Wait for Captions + Fetch Transcript

## Goal
Reliably get the auto-generated transcript for a freshly uploaded unlisted video, without a blind fixed-length sleep.

## Files
`wait_for_captions.py`, `fetch_transcript.py`

## Library — current API (verified against PyPI, `youtube-transcript-api` v1.2.4, Jan 2026)

This is **instance-based**, not static methods. Do not use the old `YouTubeTranscriptApi.get_transcript(...)` pattern from the original blueprint docs — it's from an older version of this library.

```python
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, RequestBlocked, IpBlocked
)

ytt_api = YouTubeTranscriptApi()

def try_fetch(video_id: str, languages=("en",)):
    try:
        fetched = ytt_api.fetch(video_id, languages=list(languages))
        return fetched.to_raw_data()  # list[{"text","start","duration"}]
    except NoTranscriptFound:
        return None  # not ready yet or no captions in this language
    except TranscriptsDisabled:
        raise RuntimeError(f"Captions disabled for video {video_id} — cannot proceed")
    except (RequestBlocked, IpBlocked):
        raise RuntimeError(
            "YouTube blocked this IP for transcript requests. "
            "See proxy fallback note below before retrying."
        )
```

### Proxy fallback (only if you hit `RequestBlocked`/`IpBlocked`)
At your personal-use volume from a residential IP this is unlikely, but build the hook so it's a config flip, not a rewrite:

```python
from youtube_transcript_api.proxies import WebshareProxyConfig
ytt_api = YouTubeTranscriptApi(
    proxy_config=WebshareProxyConfig(
        proxy_username=os.environ["WEBSHARE_USERNAME"],
        proxy_password=os.environ["WEBSHARE_PASSWORD"],
    )
)
```
Leave this unconfigured/unused by default — just make sure `fetch_transcript.py` accepts an optional pre-configured `YouTubeTranscriptApi` instance so a proxy-enabled one can be swapped in later without touching call sites.

## Polling logic (`wait_for_captions.py`)

```python
import time

def wait_for_captions(video_id, poll_interval_s, max_wait_minutes):
    elapsed = 0
    max_seconds = max_wait_minutes * 60
    while elapsed < max_seconds:
        raw = try_fetch(video_id)
        if raw:
            return raw
        print(f"Captions not ready yet for {video_id}, waiting {poll_interval_s}s...")
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s
    raise TimeoutError(
        f"Captions not ready after {max_wait_minutes} minutes for video {video_id}. "
        f"Check YouTube Studio manually — long sessions can occasionally take longer."
    )
```
Use `CAPTION_POLL_INTERVAL_SECONDS` and `CAPTION_MAX_WAIT_MINUTES` from `config.py` (defaults: poll every 10 minutes, give up after 90 minutes). This should run as a background wait in the orchestrator, not block you from doing anything else — print progress, don't spin silently.

## Formatting (`fetch_transcript.py`)
Convert raw snippets into the same `[HH:MM:SS] text` format both source blueprints used, since it's a good compact representation for the LLM stage:

```python
import time as _time

def format_transcript(raw_snippets):
    lines = []
    for seg in raw_snippets:
        ts = _time.strftime("%H:%M:%S", _time.gmtime(seg["start"]))
        text = seg["text"].replace("\n", " ")
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)
```

Save the formatted transcript to `logs/{video_id}_transcript.txt` for debugging/re-use — this also means if the LLM extraction stage fails, you can re-run Stage 4 without re-fetching or re-polling.

## CLI usage
```
python fetch_transcript.py --video-id abc123 --wait
```
`--wait` triggers the polling loop; without it, does a single fetch attempt and reports ready/not-ready.

## Acceptance check
On a real freshly-uploaded unlisted test video, the script correctly reports "not ready" for the first several polls, then successfully returns and formats the transcript once YouTube finishes processing captions — verified by eyeballing the saved `.txt` file against what was actually said in the video.
