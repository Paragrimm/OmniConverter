"""File-manager integration ("Convert with OmniConverter" in the context menu)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from omniconverter import runtime
from omniconverter.core.formats import FORMATS, Format

RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def supported_source_formats() -> list[Format]:
    """All formats that can be dropped onto OmniConverter (whatever tools are installed)."""
    from omniconverter.backends import default_backends

    ids = {conv.source for b in default_backends() for conv in b.conversions()}
    return [f for fid, f in FORMATS.items() if fid in ids and f.detect]


def launcher_command() -> list[str]:
    """Command that opens the GUI; file paths get appended."""
    appimage = runtime.appimage_path()
    if appimage:
        return [appimage]
    if runtime.is_frozen():
        exe = Path(sys.executable)
        gui = exe.with_name("OmniConverter.exe" if sys.platform == "win32" else "OmniConverter")
        return [str(gui if gui.exists() else exe)]
    found = shutil.which("omniconverter")
    if found:
        return [str(Path(found).resolve())]
    python = Path(sys.executable)
    if sys.platform == "win32" and python.with_name("pythonw.exe").exists():
        python = python.with_name("pythonw.exe")  # no console window
    return [str(python), "-m", "omniconverter"]


def install() -> list[str]:
    """Register the context-menu entries for the current user. Returns what was created."""
    if sys.platform == "win32":
        from omniconverter.integration import windows

        return windows.install()
    from omniconverter.integration import linux

    return linux.install()


def uninstall() -> list[str]:
    if sys.platform == "win32":
        from omniconverter.integration import windows

        return windows.uninstall()
    from omniconverter.integration import linux

    return linux.uninstall()


def is_installed() -> bool:
    if sys.platform == "win32":
        from omniconverter.integration import windows

        return windows.is_installed()
    from omniconverter.integration import linux

    return linux.is_installed()
