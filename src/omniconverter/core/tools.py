"""Discovery of external command-line tools (FFmpeg, Pandoc, LibreOffice).

Nothing is bundled or downloaded: tools installed on the system are found automatically, and
for missing ones we show how to install them.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from omniconverter.core.errors import ToolMissingError

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class ToolSpec:
    id: str
    label: str
    executables: tuple[str, ...]
    windows_paths: tuple[str, ...] = ()  # glob patterns, environment variables are expanded
    winget: str = ""
    linux_package: str = ""
    url: str = ""


_WINGET_LINKS = r"%LOCALAPPDATA%\Microsoft\WinGet\Links"
_WINGET_PKGS = r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"

TOOLS: dict[str, ToolSpec] = {
    "ffmpeg": ToolSpec(
        "ffmpeg",
        "FFmpeg",
        ("ffmpeg",),
        (
            _WINGET_LINKS + r"\ffmpeg.exe",
            _WINGET_PKGS + r"\Gyan.FFmpeg*\*\bin\ffmpeg.exe",
            _WINGET_PKGS + r"\BtbN.FFmpeg*\*\bin\ffmpeg.exe",
            r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe",
            r"%SystemDrive%\ffmpeg\bin\ffmpeg.exe",
            r"%USERPROFILE%\scoop\shims\ffmpeg.exe",
            r"%ProgramData%\chocolatey\bin\ffmpeg.exe",
        ),
        winget="Gyan.FFmpeg",
        linux_package="ffmpeg",
        url="https://ffmpeg.org/download.html",
    ),
    "ffprobe": ToolSpec(
        "ffprobe",
        "FFprobe",
        ("ffprobe",),
        (
            _WINGET_LINKS + r"\ffprobe.exe",
            _WINGET_PKGS + r"\Gyan.FFmpeg*\*\bin\ffprobe.exe",
            _WINGET_PKGS + r"\BtbN.FFmpeg*\*\bin\ffprobe.exe",
            r"%ProgramFiles%\ffmpeg\bin\ffprobe.exe",
            r"%SystemDrive%\ffmpeg\bin\ffprobe.exe",
            r"%USERPROFILE%\scoop\shims\ffprobe.exe",
            r"%ProgramData%\chocolatey\bin\ffprobe.exe",
        ),
        winget="Gyan.FFmpeg",
        linux_package="ffmpeg",
        url="https://ffmpeg.org/download.html",
    ),
    "pandoc": ToolSpec(
        "pandoc",
        "Pandoc",
        ("pandoc",),
        (
            r"%LOCALAPPDATA%\Pandoc\pandoc.exe",
            r"%ProgramFiles%\Pandoc\pandoc.exe",
            r"%USERPROFILE%\scoop\shims\pandoc.exe",
            r"%ProgramData%\chocolatey\bin\pandoc.exe",
        ),
        winget="JohnMacFarlane.Pandoc",
        linux_package="pandoc",
        url="https://pandoc.org/installing.html",
    ),
    "soffice": ToolSpec(
        "soffice",
        "LibreOffice",
        ("soffice", "libreoffice"),
        (
            r"%ProgramFiles%\LibreOffice\program\soffice.exe",
            r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
            r"%USERPROFILE%\scoop\apps\libreoffice\current\LibreOffice\program\soffice.exe",
        ),
        winget="TheDocumentFoundation.LibreOffice",
        linux_package="libreoffice",
        url="https://www.libreoffice.org/download/",
    ),
}


def tool_label(tool_id: str) -> str:
    spec = TOOLS.get(tool_id)
    return spec.label if spec else tool_id


def env_var_name(tool_id: str) -> str:
    return f"OMNICONVERTER_{tool_id.upper()}"


def _linux_package_manager() -> str:
    """Best-effort guess of the distribution's package manager for install hints."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        text = ""
    ids = " ".join(
        line.split("=", 1)[1].strip('"')
        for line in text.splitlines()
        if line.startswith(("id=", "id_like="))
    )
    if any(x in ids for x in ("fedora", "rhel", "centos")):
        return "sudo dnf install {pkg}"
    if "arch" in ids:
        return "sudo pacman -S {pkg}"
    if "suse" in ids:
        return "sudo zypper install {pkg}"
    return "sudo apt install {pkg}"


def install_hint(tool_id: str) -> str:
    """Command line that installs the tool on the current OS."""
    spec = TOOLS[tool_id]
    if IS_WINDOWS:
        return f"winget install {spec.winget}"
    return _linux_package_manager().format(pkg=spec.linux_package)


class ToolLocator:
    """Finds tools: configured path → ``OMNICONVERTER_<TOOL>`` → PATH → well-known locations."""

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        self._overrides = dict(overrides or {})
        self._cache: dict[str, str | None] = {}
        self._lock = Lock()

    def set_override(self, tool_id: str, path: str | None) -> None:
        with self._lock:
            if path:
                self._overrides[tool_id] = path
            else:
                self._overrides.pop(tool_id, None)
            self._cache.clear()

    def rescan(self) -> None:
        with self._lock:
            self._cache.clear()

    def find(self, tool_id: str) -> str | None:
        with self._lock:
            if tool_id not in self._cache:
                self._cache[tool_id] = self._search(tool_id)
            return self._cache[tool_id]

    def available(self, tool_id: str) -> bool:
        return self.find(tool_id) is not None

    def require(self, tool_id: str) -> str:
        path = self.find(tool_id)
        if path is None:
            raise ToolMissingError(tool_id)
        return path

    def _search(self, tool_id: str) -> str | None:
        spec = TOOLS[tool_id]
        candidates = [self._overrides.get(tool_id), os.environ.get(env_var_name(tool_id))]
        if tool_id == "ffprobe":  # a custom FFmpeg usually ships ffprobe right next to it
            for ffmpeg in (self._overrides.get("ffmpeg"), os.environ.get(env_var_name("ffmpeg"))):
                if ffmpeg:
                    p = Path(ffmpeg)
                    candidates.append(str(p.with_name(p.name.replace("ffmpeg", "ffprobe"))))
        for candidate in candidates:
            if candidate and _is_executable(candidate):
                return str(Path(candidate))
        for name in spec.executables:
            found = shutil.which(name)
            if found:
                return found
        if IS_WINDOWS:
            for pattern in spec.windows_paths:
                expanded = os.path.expandvars(pattern)
                if "%" in expanded:  # an environment variable was not set
                    continue
                for match in sorted(glob.glob(expanded), reverse=True):
                    if _is_executable(match):
                        return match
        return None


def _is_executable(path: str) -> bool:
    p = Path(path)
    return p.is_file() and (IS_WINDOWS or os.access(p, os.X_OK))
