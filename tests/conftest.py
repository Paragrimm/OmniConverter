from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from omniconverter.core.converter import Converter
from omniconverter.core.tools import ToolLocator
from omniconverter.i18n import set_language

_LOCATOR = ToolLocator()
HAVE_FFMPEG = _LOCATOR.available("ffmpeg") and _LOCATOR.available("ffprobe")
HAVE_PANDOC = _LOCATOR.available("pandoc")
HAVE_SOFFICE = _LOCATOR.available("soffice")

needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")
needs_pandoc = pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc not installed")
needs_soffice = pytest.mark.skipif(not HAVE_SOFFICE, reason="LibreOffice not installed")


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    """English messages, private config dir, and no network access from Python code."""
    set_language("en")
    monkeypatch.setenv("OMNICONVERTER_CONFIG_DIR", str(tmp_path / "config"))

    def refuse(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    set_language(None)


@pytest.fixture
def converter() -> Converter:
    return Converter(ToolLocator())


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def sample_video(media_dir) -> Path:
    """2 s, 320×240, 25 fps test pattern with a 440 Hz tone."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg not installed")
    out = media_dir / "sample.mp4"
    if not out.exists():
        ffmpeg("-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out))
    return out


@pytest.fixture(scope="session")
def sample_audio(media_dir) -> Path:
    """3 s quiet sine – well below typical loudness targets."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg not installed")
    out = media_dir / "quiet.wav"
    if not out.exists():
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3,volume=0.05", str(out))
    return out


def measure_lufs(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null",
         "-"], capture_output=True, text=True, check=True,
    )
    summary = result.stderr.rsplit("Summary:", 1)[-1]
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            return float(line.split()[1])
    raise AssertionError("no loudness in ffmpeg output")


def ffprobe_json(path: Path) -> dict:
    import json

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)
