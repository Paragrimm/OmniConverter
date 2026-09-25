"""How OmniConverter runs: from source, as a packaged build, portable or as an AppImage."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

# A file with this name next to the executable makes a packaged build keep its settings in
# its own folder (portable ZIP / tar.gz, e.g. on a USB stick).
PORTABLE_MARKER = "portable.txt"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder of the packaged executables (only meaningful when frozen)."""
    return Path(sys.executable).resolve().parent


def is_portable() -> bool:
    return is_frozen() and (app_dir() / PORTABLE_MARKER).is_file()


def appimage_path() -> str | None:
    """Path of the running ``.AppImage`` file – stable, unlike its temporary mount point."""
    path = os.environ.get("APPIMAGE")
    return path if is_frozen() and path else None


def child_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for external tools.

    A packaged Linux build points ``LD_LIBRARY_PATH`` at its bundled libraries; system
    programs like FFmpeg or LibreOffice must not load those, so the original value
    (saved by PyInstaller as ``LD_LIBRARY_PATH_ORIG``) is restored.
    """
    result = dict(os.environ if env is None else env)
    if is_frozen() and sys.platform.startswith("linux"):
        original = result.pop("LD_LIBRARY_PATH_ORIG", None)
        if original:
            result["LD_LIBRARY_PATH"] = original
        else:
            result.pop("LD_LIBRARY_PATH", None)
    return result
