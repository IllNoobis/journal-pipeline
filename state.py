"""
Pipeline state / idempotency tracking backed by processed_videos.json.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _load(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(state_path: Path, data: dict) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_video_state(state_path: Path, video_id: str) -> Optional[dict]:
    data = _load(state_path)
    return data.get(video_id)


def find_by_source_file(state_path: Path, source_file: str) -> Optional[str]:
    """Return video_id if this exact source file was already uploaded, else None."""
    data = _load(state_path)
    source_str = str(Path(source_file).resolve())
    for vid, info in data.items():
        if str(Path(info.get("source_file", "")).resolve()) == source_str:
            return vid
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_uploaded(state_path: Path, video_id: str, source_file: str) -> None:
    data = _load(state_path)
    data[video_id] = {
        "source_file": str(Path(source_file).resolve()),
        "status": "uploaded",
        "uploaded_at": _now_iso(),
    }
    _save(state_path, data)


def mark_transcript_ready(state_path: Path, video_id: str) -> None:
    data = _load(state_path)
    if video_id in data:
        data[video_id]["status"] = "transcript_ready"
        data[video_id]["transcript_fetched_at"] = _now_iso()
        _save(state_path, data)


def mark_extracted(state_path: Path, video_id: str) -> None:
    data = _load(state_path)
    if video_id in data:
        data[video_id]["status"] = "extracted"
        data[video_id]["extracted_at"] = _now_iso()
        _save(state_path, data)


def mark_logged(state_path: Path, video_id: str, offsets_logged: list[str]) -> None:
    data = _load(state_path)
    if video_id in data:
        existing = data[video_id].get("trade_offsets_logged", [])
        merged = list(set(existing + offsets_logged))
        data[video_id]["status"] = "logged"
        data[video_id]["logged_at"] = _now_iso()
        data[video_id]["trade_offsets_logged"] = merged
        _save(state_path, data)


def already_logged_offsets(state_path: Path, video_id: str) -> set[str]:
    state = get_video_state(state_path, video_id)
    return set(state.get("trade_offsets_logged", [])) if state else set()
