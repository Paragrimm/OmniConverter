"""Media inspection via ffprobe (duration, streams, resolution)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from omniconverter.core import process
from omniconverter.core.errors import ConversionError
from omniconverter.core.tools import ToolLocator


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None = None
    has_video: bool = False
    has_audio: bool = False
    has_cover: bool = False  # attached picture, e.g. album art in an MP3
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None


def probe(path: str | Path, locator: ToolLocator) -> MediaInfo | None:
    """Inspect a media file. Returns ``None`` if ffprobe is missing or cannot read the file."""
    ffprobe = locator.find("ffprobe")
    if ffprobe is None:
        return None
    args = [
        ffprobe,
        "-v", "error",
        "-protocol_whitelist", "file",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(Path(path).resolve()),
    ]
    try:
        result = process.run(args, timeout=30)
        data = json.loads(result.stdout or "{}")
    except (ConversionError, ValueError):
        return None
    return parse_probe(data)


def parse_probe(data: dict) -> MediaInfo:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = audio = None
    has_cover = False
    for s in streams:
        kind = s.get("codec_type")
        if kind == "video":
            if (s.get("disposition") or {}).get("attached_pic"):
                has_cover = True
            elif video is None:
                video = s
        elif kind == "audio" and audio is None:
            audio = s

    duration = _float(fmt.get("duration"))
    if duration is None:
        for s in (video, audio):
            if s and _float(s.get("duration")) is not None:
                duration = _float(s.get("duration"))
                break
    return MediaInfo(
        duration=duration,
        has_video=video is not None,
        has_audio=audio is not None,
        has_cover=has_cover,
        width=_int(video.get("width")) if video else None,
        height=_int(video.get("height")) if video else None,
        fps=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=_int(audio.get("sample_rate")) if audio else None,
        channels=_int(audio.get("channels")) if audio else None,
    )


def _float(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return _float(value)
    num, _, den = value.partition("/")
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return n / d if n > 0 and d > 0 else None
