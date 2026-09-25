import os
import sys

import pytest

from omniconverter.integration import launcher_command, linux, supported_source_formats, windows


def test_supported_formats_cover_all_categories():
    ids = {f.id for f in supported_source_formats()}
    assert {"mp4", "mp3", "png", "docx", "md", "xlsx", "json", "pptx"} <= ids


def test_launcher_command_opens_gui():
    cmd = launcher_command()
    assert cmd
    assert cmd[-1] == "omniconverter" or cmd[0].lower().endswith(
        ("omniconverter", "omniconverter.exe"))


@pytest.mark.parametrize(("arg", "quoted"), [
    ("/usr/bin/omniconverter", "/usr/bin/omniconverter"),
    ("/opt/My Apps/omni", '"/opt/My Apps/omni"'),
    ("/x/$HOME/a", '"/x/\\\\$HOME/a"'),
    ("50%", "50%%"),
])
def test_exec_quoting(arg, quoted):
    assert linux.exec_quote(arg) == quoted


@pytest.mark.skipif(sys.platform == "win32", reason="Linux desktop files")
def test_linux_install_and_uninstall(tmp_path, monkeypatch):
    share = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(share))
    monkeypatch.setattr(linux, "_refresh", lambda _dir: None)
    created = linux.install(["/opt/Omni Converter/omniconverter"])
    assert linux.is_installed()

    desktop = (share / "applications" / "omniconverter.desktop").read_text()
    assert 'Exec="/opt/Omni Converter/omniconverter" %F' in desktop
    assert "video/mp4;" in desktop and "image/png;" in desktop
    assert "Name=OmniConverter" in desktop

    dolphin = share / "kio" / "servicemenus" / "omniconverter.desktop"
    assert os.access(dolphin, os.X_OK)  # Plasma 6 requires executable service menus
    assert "Name[de]=Mit OmniConverter umwandeln" in dolphin.read_text()

    script = share / "nautilus" / "scripts" / "Convert with OmniConverter"
    assert os.access(script, os.X_OK)
    assert script.read_text() == '#!/bin/sh\nexec \'/opt/Omni Converter/omniconverter\' "$@"\n'

    nemo = (share / "nemo" / "actions" / "omniconverter.nemo_action").read_text()
    assert "Selection=notnone" in nemo and "mp4;" in nemo

    assert (share / "icons" / "hicolor" / "scalable" / "apps" / "omniconverter.svg").exists()
    assert len(created) >= 5

    removed = linux.uninstall()
    assert set(removed) >= set(created)
    assert not linux.is_installed()


def test_windows_registry_entries(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = [r"C:\Program Files\OmniConverter\OmniConverter.exe"]
    entries = windows.registry_entries(cmd, "Mit OmniConverter umwandeln", ["mp4", "png"])
    base = r"Software\Classes\SystemFileAssociations\.mp4\shell\OmniConverter"
    assert (base, "", "Mit OmniConverter umwandeln") in entries
    assert (base, "Icon", r"C:\Program Files\OmniConverter\OmniConverter.exe,0") in entries
    assert (base + r"\command", "",
            r'"C:\Program Files\OmniConverter\OmniConverter.exe" "%1"') in entries
    assert len(entries) == 8


def test_windows_icon_for_python_launch():
    icon = windows.icon_location([r"C:\Python311\pythonw.exe", "-m", "omniconverter"])
    assert icon.endswith("omniconverter.ico")
    pip_launcher = [r"C:\Users\me\AppData\Roaming\Python\Scripts\omniconverter.exe"]
    assert windows.icon_location(pip_launcher, frozen=False).endswith("omniconverter.ico")


def test_windows_extensions_include_aliases():
    exts = windows.extensions()
    assert {"jpg", "jpeg", "mp4", "docx", "yml"} <= set(exts)
