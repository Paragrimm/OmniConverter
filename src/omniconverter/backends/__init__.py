"""Conversion backends."""

from __future__ import annotations

from omniconverter.core.backend import Backend


def default_backends() -> list[Backend]:
    from omniconverter.backends.data import DataBackend
    from omniconverter.backends.document import (
        LibreOfficeBackend,
        MarkupToPdfBackend,
        PandocBackend,
    )
    from omniconverter.backends.ffmpeg import FFmpegAudioBackend, FFmpegVideoBackend
    from omniconverter.backends.image import ImageBackend

    return [
        FFmpegVideoBackend(),
        FFmpegAudioBackend(),
        ImageBackend(),
        LibreOfficeBackend(),
        PandocBackend(),
        MarkupToPdfBackend(),
        DataBackend(),
    ]
