"""Windows Explorer context menu via per-user registry keys (no admin rights needed).

For every supported extension we add
``HKCU\\Software\\Classes\\SystemFileAssociations\\.<ext>\\shell\\OmniConverter``.
Explorer starts one process per selected file; the GUI's single-instance handling collects
them into one window. On Windows 11 the entry lives under "Show more options".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from omniconverter.i18n import t

VERB = "OmniConverter"
BASE = r"Software\Classes\SystemFileAssociations"

RegEntry = tuple[str, str, str]  # (key path below HKCU, value name, value)


def extensions() -> list[str]:
    from omniconverter.integration import supported_source_formats

    return sorted({ext for f in supported_source_formats() for ext in f.extensions})


def verb_key(ext: str) -> str:
    return rf"{BASE}\.{ext}\shell\{VERB}"


def icon_location(command: list[str]) -> str:
    exe = Path(command[0])
    if exe.suffix.lower() == ".exe" and exe.stem.lower() not in ("python", "pythonw"):
        return f"{exe},0"
    from omniconverter.integration import RESOURCES

    return str(RESOURCES / "omniconverter.ico")


def registry_entries(command: list[str], label: str, exts: list[str]) -> list[RegEntry]:
    cmdline = subprocess.list2cmdline(command) + ' "%1"'
    icon = icon_location(command)
    entries: list[RegEntry] = []
    for ext in exts:
        key = verb_key(ext)
        entries += [
            (key, "", label),
            (key, "Icon", icon),
            (key, "MultiSelectModel", "Player"),
            (key + r"\command", "", cmdline),
        ]
    return entries


def install() -> list[str]:
    import winreg

    from omniconverter.integration import launcher_command

    entries = registry_entries(launcher_command(), t("integration.menu_label"), extensions())
    for key, name, value in entries:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    return sorted({rf"HKCU\{key}" for key, _, _ in entries if not key.endswith("command")})


def uninstall() -> list[str]:
    import winreg

    removed = []
    for ext in extensions():
        key = verb_key(ext)
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                continue
            if sub == key:
                removed.append(rf"HKCU\{key}")
    return removed


def is_installed() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, verb_key("mp4")))
    except OSError:
        return False
    return True
