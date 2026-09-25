"""Build release packages into ``dist/release/``.

    python packaging/build.py                    # everything for this platform
    python packaging/build.py portable deb       # only some formats
    python packaging/build.py --no-pyinstaller   # reuse an existing dist/OmniConverter

Windows: portable ZIP and Inno Setup installer. Linux: portable tar.gz, AppImage and .deb.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from omniconverter import __version__  # noqa: E402
from omniconverter.runtime import PORTABLE_MARKER  # noqa: E402

DIST = ROOT / "dist"
BUNDLE = DIST / "OmniConverter"
OUT = DIST / "release"
WORK = ROOT / "build" / "package"
RESOURCES = ROOT / "src" / "omniconverter" / "resources"
IS_WINDOWS = sys.platform == "win32"
MACHINE = platform.machine().lower()
ARCH = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(
    MACHINE, MACHINE
)
DEB_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(ARCH, ARCH)
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    f"appimagetool-{ARCH}.AppImage"
)
DEFAULT_TARGETS = ["portable", "installer"] if IS_WINDOWS else ["portable", "appimage", "deb"]

PORTABLE_TEXT = """\
OmniConverter – portable
========================
Diese Datei macht OmniConverter portabel: Die Einstellungen landen im Ordner "settings"
hier daneben statt im Benutzerprofil. Löschen, um das normale Verhalten zu bekommen.

This file makes OmniConverter portable: settings are stored in the "settings" folder next
to it instead of the user profile. Delete it to get the normal behaviour.
"""

DEB_DEPENDS = [
    "libc6 (>= 2.35)", "libegl1", "libgl1", "libfontconfig1", "libdbus-1-3",
    "libxkbcommon0", "libxkbcommon-x11-0", "libxcb-cursor0",
]
DEB_RECOMMENDS = [
    "ffmpeg", "pandoc", "libreoffice-writer", "libreoffice-calc", "libreoffice-impress",
]
DEB_SUGGESTS = ["blender"]  # only for FBX, and large


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def run(args: list[str], **kwargs) -> None:
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def fresh(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


# -- steps -----------------------------------------------------------------------------------


def pyinstaller() -> None:
    log("PyInstaller")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", DIST, "--workpath", ROOT / "build" / "pyinstaller",
         ROOT / "packaging" / "omniconverter.spec"])


def portable() -> Path:
    """The bundle plus the portable marker, as ZIP (Windows) or tar.gz (Linux)."""
    log("portable archive")
    stage = fresh(WORK / "portable") / "OmniConverter"
    shutil.copytree(BUNDLE, stage, symlinks=True)
    (stage / PORTABLE_MARKER).write_text(PORTABLE_TEXT, encoding="utf-8")
    if IS_WINDOWS:
        base, fmt = OUT / f"OmniConverter-{__version__}-windows-x64-portable", "zip"
    else:  # tar keeps the executable bits
        base, fmt = OUT / f"OmniConverter-{__version__}-linux-{ARCH}-portable", "gztar"
    return Path(shutil.make_archive(str(base), fmt, root_dir=stage.parent, base_dir=stage.name))


def find_iscc() -> Path:
    candidates = [shutil.which("iscc"), shutil.which("ISCC")]
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(str(Path(base) / "Inno Setup 6" / "ISCC.exe"))
            candidates.append(str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit("Inno Setup (ISCC.exe) not found – install it, e.g. `choco install innosetup`")


def installer() -> Path:
    log("Windows installer (Inno Setup)")
    run([find_iscc(), f"/DAppVersion={__version__}", f"/DRoot={ROOT}",
         f"/DSourceDir={BUNDLE}", f"/DOutputDir={OUT}",
         ROOT / "packaging" / "windows" / "omniconverter.iss"])
    return OUT / f"OmniConverter-{__version__}-windows-x64-setup.exe"


def desktop_file(command: list[str]) -> str:
    from omniconverter.integration.linux import desktop_entry

    return desktop_entry(command, "omniconverter")


def install_icons(share: Path) -> None:
    icons = share / "icons" / "hicolor"
    (icons / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
    (icons / "256x256" / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RESOURCES / "omniconverter.svg", icons / "scalable/apps/omniconverter.svg")
    shutil.copyfile(RESOURCES / "omniconverter.png", icons / "256x256/apps/omniconverter.png")


def appimagetool() -> Path:
    tool = WORK / f"appimagetool-{ARCH}.AppImage"
    if not tool.exists():
        log(f"downloading {APPIMAGETOOL_URL}")
        tool.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(APPIMAGETOOL_URL, timeout=120) as response:
            tool.write_bytes(response.read())
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    return tool


def appimage() -> Path:
    log("AppImage")
    appdir = fresh(WORK / "AppDir")
    shutil.copytree(BUNDLE, appdir / "usr" / "lib" / "omniconverter", symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text(
        '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/lib/omniconverter/OmniConverter" "$@"\n',
        encoding="utf-8",
    )
    apprun.chmod(0o755)
    (appdir / "omniconverter.desktop").write_text(desktop_file(["OmniConverter"]),
                                                  encoding="utf-8")
    shutil.copyfile(RESOURCES / "omniconverter.png", appdir / "omniconverter.png")
    shutil.copyfile(RESOURCES / "omniconverter.png", appdir / ".DirIcon")
    install_icons(appdir / "usr" / "share")

    out = OUT / f"OmniConverter-{__version__}-{ARCH}.AppImage"
    env = {**os.environ, "ARCH": ARCH, "APPIMAGE_EXTRACT_AND_RUN": "1"}
    run([appimagetool(), "--no-appstream", appdir, out], env=env)
    return out


def deb() -> Path:
    log(".deb package")
    root = fresh(WORK / "deb")
    shutil.copytree(BUNDLE, root / "opt" / "omniconverter", symlinks=True)
    bindir = root / "usr" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "omniconverter").symlink_to("../../opt/omniconverter/OmniConverter")
    (bindir / "omniconvert").symlink_to("../../opt/omniconverter/omniconvert")
    share = root / "usr" / "share"
    (share / "applications").mkdir(parents=True)
    (share / "applications" / "omniconverter.desktop").write_text(
        desktop_file(["omniconverter"]), encoding="utf-8")
    install_icons(share)
    docs = share / "doc" / "omniconverter"
    docs.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", docs / "copyright")

    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    control = root / "DEBIAN" / "control"
    control.parent.mkdir()
    control.write_text("\n".join([
        "Package: omniconverter",
        f"Version: {__version__}",
        f"Architecture: {DEB_ARCH}",
        "Maintainer: Paragrimm <paragrimm@users.noreply.github.com>",
        f"Installed-Size: {size // 1024}",  # KiB
        f"Depends: {', '.join(DEB_DEPENDS)}",
        f"Recommends: {', '.join(DEB_RECOMMENDS)}",
        f"Suggests: {', '.join(DEB_SUGGESTS)}",
        "Section: graphics",
        "Priority: optional",
        "Homepage: https://github.com/Paragrimm/OmniConverter",
        "Description: one simple, privacy-aware converter for many file types",
        " Converts videos, music, images, 3D models, documents, spreadsheets and data",
        " files locally with a drag-and-drop GUI, a command line and a file manager",
        " context menu, and creates QR codes, normal/specular maps and noise maps.",
        " Uses FFmpeg, Pandoc, LibreOffice and Blender when installed.",
        "",
    ]), encoding="utf-8")
    out = OUT / f"omniconverter_{__version__}_{DEB_ARCH}.deb"
    run(["dpkg-deb", "--build", "--root-owner-group", "-Zxz", root, out])
    return out


STEPS = {"portable": portable, "installer": installer, "appimage": appimage, "deb": deb}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("targets", nargs="*", metavar="TARGET",
                        help=f"one of {', '.join(STEPS)} (default: {' '.join(DEFAULT_TARGETS)})")
    parser.add_argument("--no-pyinstaller", action="store_true",
                        help="reuse dist/OmniConverter instead of building it")
    args = parser.parse_args()
    targets = args.targets or DEFAULT_TARGETS
    unknown = [t for t in targets if t not in STEPS]
    if unknown:
        parser.error(f"unknown target(s): {', '.join(unknown)}")

    if not args.no_pyinstaller:
        pyinstaller()
    if not BUNDLE.is_dir():
        raise SystemExit(f"{BUNDLE} missing – run without --no-pyinstaller first")
    OUT.mkdir(parents=True, exist_ok=True)
    built = [STEPS[t]() for t in targets]
    log("done")
    for path in built:
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
