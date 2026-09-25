"""Settings: language, external tools, context-menu integration."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omniconverter import integration
from omniconverter.config import Settings
from omniconverter.core.tools import TOOLS, ToolLocator, install_hint
from omniconverter.i18n import t


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, locator: ToolLocator,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.locator = locator
        self.setWindowTitle(t("gui.settings.title"))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        # Language
        lang_box = QGroupBox(t("gui.settings.language"))
        lang_layout = QHBoxLayout(lang_box)
        self.language = QComboBox()
        for value, label in (("auto", t("gui.settings.language_auto")), ("de", "Deutsch"),
                             ("en", "English")):
            self.language.addItem(label, value)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        lang_layout.addWidget(self.language)
        restart = QLabel(t("gui.settings.restart"))
        restart.setObjectName("Muted")
        lang_layout.addWidget(restart, 1)
        layout.addWidget(lang_box)

        # Tools
        tools_box = QGroupBox(t("gui.settings.tools"))
        self.tools_grid = QGridLayout(tools_box)
        self.tools_grid.setColumnStretch(1, 1)
        layout.addWidget(tools_box)
        rescan = QPushButton(t("gui.settings.rescan"))
        rescan.clicked.connect(self._rescan)
        tools_hint = QLabel(t("gui.settings.tools_hint"))
        tools_hint.setObjectName("Muted")
        tools_hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(tools_hint, 1)
        row.addWidget(rescan)
        layout.addLayout(row)

        # Context menu
        menu_box = QGroupBox(t("gui.settings.context_menu"))
        menu_layout = QHBoxLayout(menu_box)
        self.menu_status = QLabel()
        self.menu_button = QPushButton()
        self.menu_button.clicked.connect(self._toggle_menu)
        menu_layout.addWidget(self.menu_status, 1)
        menu_layout.addWidget(self.menu_button)
        layout.addWidget(menu_box)

        privacy = QLabel(t("gui.settings.privacy"))
        privacy.setWordWrap(True)
        privacy.setObjectName("Muted")
        layout.addWidget(privacy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._fill_tools()
        self._update_menu()

    def _fill_tools(self) -> None:
        while self.tools_grid.count():
            item = self.tools_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for row, (tool_id, spec) in enumerate(TOOLS.items()):
            path = self.locator.find(tool_id)
            name = QLabel(f"<b>{spec.label}</b>")
            if path:
                status = QLabel(f"✔ {path}")
                status.setObjectName("Ok")
            else:
                status = QLabel(f"✘ {t('gui.settings.not_found')}: <code>{install_hint(tool_id)}"
                                f"</code>")
                status.setObjectName("Error")
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            status.setWordWrap(True)
            browse = QPushButton(t("gui.settings.browse"))
            browse.clicked.connect(lambda _=False, tid=tool_id: self._browse(tid))
            self.tools_grid.addWidget(name, row, 0)
            self.tools_grid.addWidget(status, row, 1)
            self.tools_grid.addWidget(browse, row, 2)
            if tool_id in self.settings.tool_paths:
                reset = QPushButton(t("gui.settings.reset"))
                reset.clicked.connect(lambda _=False, tid=tool_id: self._set_tool(tid, None))
                self.tools_grid.addWidget(reset, row, 3)

    def _browse(self, tool_id: str) -> None:
        pattern = "*.exe" if sys.platform == "win32" else "*"
        path, _ = QFileDialog.getOpenFileName(
            self, TOOLS[tool_id].label, "", f"{TOOLS[tool_id].label} ({pattern})"
        )
        if path:
            self._set_tool(tool_id, path)

    def _set_tool(self, tool_id: str, path: str | None) -> None:
        if path:
            self.settings.tool_paths[tool_id] = path
        else:
            self.settings.tool_paths.pop(tool_id, None)
        self.locator.set_override(tool_id, path)
        self._fill_tools()

    def _rescan(self) -> None:
        self.locator.rescan()
        self._fill_tools()

    def _update_menu(self) -> None:
        installed = integration.is_installed()
        self.menu_status.setText(
            t("gui.settings.menu_on") if installed else t("gui.settings.menu_off")
        )
        self.menu_button.setText(
            t("gui.settings.menu_remove") if installed else t("gui.settings.menu_install")
        )

    def _toggle_menu(self) -> None:
        try:
            if integration.is_installed():
                integration.uninstall()
            else:
                integration.install()
        except OSError as exc:
            QMessageBox.warning(self, t("gui.settings.context_menu"), str(exc))
        self._update_menu()

    def done(self, result: int) -> None:
        self.settings.language = self.language.currentData()
        try:
            self.settings.save()
        except OSError as exc:
            QMessageBox.warning(self, t("gui.settings.title"), str(exc))
        super().done(result)
