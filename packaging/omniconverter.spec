# PyInstaller spec: one folder with the GUI (OmniConverter) and the CLI (omniconvert).
# Build with:  python packaging/build.py
# ruff: noqa
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
RESOURCES = SRC / "omniconverter" / "resources"
ICON = str(RESOURCES / "omniconverter.ico")
IS_WINDOWS = sys.platform == "win32"

common = dict(
    pathex=[str(SRC)],
    datas=[(str(RESOURCES), "omniconverter/resources")],
    hiddenimports=["pillow_heif"],
    excludes=[
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtPdf",
        "PySide6.QtOpenGL",
        "PySide6.QtSql",
        "PySide6.QtTest",
    ],
)

gui = Analysis([str(ROOT / "packaging" / "entry_gui.py")], **common)
cli = Analysis([str(ROOT / "packaging" / "entry_cli.py")], **common)

gui_exe = EXE(
    PYZ(gui.pure),
    gui.scripts,
    [],
    exclude_binaries=True,
    name="OmniConverter",
    console=False,
    icon=ICON,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="omniconvert",
    console=True,
    icon=ICON,
)

COLLECT(
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    name="OmniConverter",
)
