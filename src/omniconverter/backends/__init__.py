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
    from omniconverter.backends.model3d import BlenderBackend, MeshBackend
    from omniconverter.backends.noise import NoiseBackend
    from omniconverter.backends.qr import QRBackend
    from omniconverter.backends.texture import TextureBackend

    return [
        FFmpegVideoBackend(),
        FFmpegAudioBackend(),
        ImageBackend(),
        TextureBackend(),
        NoiseBackend(),
        QRBackend(),
        MeshBackend(),
        BlenderBackend(),
        LibreOfficeBackend(),
        PandocBackend(),
        MarkupToPdfBackend(),
        DataBackend(),
    ]
