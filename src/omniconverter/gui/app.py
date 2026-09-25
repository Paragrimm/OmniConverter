"""GUI entry point: ``omniconverter [FILE…]``."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from omniconverter import APP_ID, APP_NAME, __version__
    from omniconverter.config import Settings
    from omniconverter.core.converter import Converter
    from omniconverter.core.tools import ToolLocator
    from omniconverter.gui.main_window import MainWindow
    from omniconverter.gui.single_instance import SingleInstance
    from omniconverter.gui.style import STYLESHEET
    from omniconverter.gui.widgets import app_icon

    settings = Settings.load()
    settings.apply()

    args = list(sys.argv if argv is None else [sys.argv[0], *argv])
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLESHEET)

    paths = [a for a in app.arguments()[1:] if not a.startswith("-")]
    instance = SingleInstance()
    if not instance.acquire_or_forward(paths):
        return 0  # an OmniConverter window is already open and got our files

    window = MainWindow(Converter(ToolLocator(settings.tool_paths)), settings)
    instance.files_received.connect(window.open_files)
    app.aboutToQuit.connect(instance.close)
    window.show()
    if paths:
        window.open_files(paths)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
