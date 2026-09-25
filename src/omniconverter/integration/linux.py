"""Linux desktop integration for the current user.

* ``applications/omniconverter.desktop`` – app launcher and "Open with" for supported types
* Nautilus (GNOME Files) script, Dolphin (KDE) service menu, Nemo (Cinnamon) action
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from omniconverter import APP_ID, APP_NAME
from omniconverter.i18n import MESSAGES
from omniconverter.runtime import child_env

_LABEL_DE, _LABEL_EN = MESSAGES["integration.menu_label"]
_COMMENT_DE, _COMMENT_EN = MESSAGES["integration.comment"]


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def targets() -> dict[str, Path]:
    home = data_home()
    return {
        "desktop": home / "applications" / f"{APP_ID}.desktop",
        "icon": home / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
        "nautilus_de": home / "nautilus" / "scripts" / _LABEL_DE,
        "nautilus_en": home / "nautilus" / "scripts" / _LABEL_EN,
        "dolphin6": home / "kio" / "servicemenus" / f"{APP_ID}.desktop",
        "dolphin5": home / "kservices5" / "ServiceMenus" / f"{APP_ID}.desktop",
        "nemo": home / "nemo" / "actions" / f"{APP_ID}.nemo_action",
    }


def exec_quote(arg: str) -> str:
    """Quote one argument for an ``Exec=`` key (Desktop Entry spec)."""
    if re.search(r"[\s\"'\\><~|&;$*?#()`]", arg):
        arg = '"' + re.sub(r'(["`$\\])', r"\\\1", arg) + '"'
        arg = arg.replace("\\", "\\\\")  # string-level escaping of the value itself
    return arg.replace("%", "%%")


def exec_line(command: list[str]) -> str:
    return " ".join(exec_quote(a) for a in command) + " %F"


def mime_types() -> list[str]:
    from omniconverter.integration import supported_source_formats

    return sorted({m for f in supported_source_formats() for m in f.mime})


def desktop_entry(command: list[str], icon: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={APP_NAME}",
        "GenericName=File Converter",
        "GenericName[de]=Dateikonverter",
        f"Comment={_COMMENT_EN}",
        f"Comment[de]={_COMMENT_DE}",
        f"Exec={exec_line(command)}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=Utility;AudioVideo;Graphics;Office;",
        "Keywords=convert;converter;video;audio;image;pdf;ffmpeg;",
        f"MimeType={';'.join(mime_types())};",
        "",
    ])


def dolphin_menu(command: list[str], icon: str, plasma5: bool) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Service",
        f"MimeType={';'.join(mime_types())};",
        "Actions=omniconverter;",
        "X-KDE-Priority=TopLevel",
    ]
    if plasma5:
        lines.append("X-KDE-ServiceTypes=KonqPopupMenu/Plugin")
    lines += [
        "",
        "[Desktop Action omniconverter]",
        f"Name={_LABEL_EN}",
        f"Name[de]={_LABEL_DE}",
        f"Icon={icon}",
        f"Exec={exec_line(command)}",
        "",
    ]
    return "\n".join(lines)


def nemo_action(command: list[str], icon: str) -> str:
    from omniconverter.integration import supported_source_formats

    exts = sorted({e for f in supported_source_formats() for e in f.extensions})
    return "\n".join([
        "[Nemo Action]",
        f"Name={_LABEL_EN}",
        f"Name[de]={_LABEL_DE}",
        f"Comment={_COMMENT_EN}",
        f"Icon-Name={icon}",
        f"Exec={exec_line(command)}",
        "Selection=notnone",
        f"Extensions={';'.join(exts)};",
        "",
    ])


def nautilus_script(command: list[str]) -> str:
    return f'#!/bin/sh\nexec {shlex.join(command)} "$@"\n'


def install(command: list[str] | None = None) -> list[str]:
    from omniconverter.i18n import current_language
    from omniconverter.integration import RESOURCES, launcher_command

    command = command or launcher_command()
    paths = targets()
    icon_src = RESOURCES / "omniconverter.svg"
    icon = APP_ID
    if icon_src.exists():
        paths["icon"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon_src, paths["icon"])
    else:
        icon = "applications-utilities"

    nautilus = paths["nautilus_de" if current_language() == "de" else "nautilus_en"]
    files = {
        paths["desktop"]: (desktop_entry(command, icon), 0o644),
        nautilus: (nautilus_script(command), 0o755),
        paths["dolphin6"]: (dolphin_menu(command, icon, plasma5=False), 0o755),
        paths["dolphin5"]: (dolphin_menu(command, icon, plasma5=True), 0o755),
        paths["nemo"]: (nemo_action(command, icon), 0o644),
    }
    for path, (content, mode) in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
    _refresh(paths["desktop"].parent)
    return [str(p) for p in [*files, paths["icon"]] if p.exists()]


def uninstall() -> list[str]:
    removed = []
    for path in targets().values():
        if path.exists():
            path.unlink()
            removed.append(str(path))
    _refresh(targets()["desktop"].parent)
    return removed


def is_installed() -> bool:
    return targets()["desktop"].exists()


def _refresh(applications: Path) -> None:
    tool = shutil.which("update-desktop-database")
    if tool and applications.is_dir():
        subprocess.run([tool, "-q", str(applications)], check=False, env=child_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
