"""Main window: Drop → configure → progress → result."""

from __future__ import annotations

import dataclasses
import html
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omniconverter import APP_NAME
from omniconverter.config import Settings
from omniconverter.core.converter import Converter, SourceFile, unique_path
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import CATEGORY_ORDER, Category, Format
from omniconverter.core.registry import TargetChoice
from omniconverter.core.tools import TOOLS, install_hint
from omniconverter.gui.options_form import OptionsForm
from omniconverter.gui.settings_dialog import SettingsDialog
from omniconverter.gui.widgets import (
    DropArea,
    EmoteLabel,
    FlowLayout,
    app_icon,
    dropped_text,
    emote_credit,
    format_duration,
    format_size,
    generated_output_dir,
    hline,
    local_paths,
    open_file,
    show_in_folder,
)
from omniconverter.gui.worker import ConversionWorker, Job
from omniconverter.i18n import t
from omniconverter.integration import supported_source_formats

MERGE_WINDOW_S = 3.0  # files arriving this soon after the last ones are added to them


def file_filter() -> str:
    patterns = " ".join(f"*.{e}" for f in supported_source_formats() for e in f.extensions)
    return f"{t('gui.drop.supported')} ({patterns});;{t('gui.drop.all_files')} (*)"


def default_dir(source: SourceFile) -> Path | None:
    """Where results without a source file go by default (files: next to the original)."""
    return generated_output_dir() if source.path is None else None


# --------------------------------------------------------------------------------------------


class DropPage(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        self.drop = DropArea(file_filter())
        self.drop.files_chosen.connect(window.open_files)
        self.drop.text_dropped.connect(window.open_text)
        layout.addWidget(self.drop, 1)

        create = QHBoxLayout()
        create.setSpacing(6)
        self.qr_text = QLineEdit()
        self.qr_text.setPlaceholderText(t("gui.qr_placeholder"))
        self.qr_text.setClearButtonEnabled(True)
        self.qr_button = QPushButton(t("gui.qr_button"))
        self.qr_button.setEnabled(False)
        self.qr_text.textChanged.connect(
            lambda text: self.qr_button.setEnabled(bool(text.strip())))
        self.qr_text.returnPressed.connect(self._make_qr)
        self.qr_button.clicked.connect(self._make_qr)
        self.noise_button = QPushButton(t("gui.noise_button"))
        self.noise_button.clicked.connect(lambda: window.open_generator("noise"))
        create.addWidget(self.qr_text, 1)
        create.addWidget(self.qr_button)
        create.addSpacing(12)
        create.addWidget(self.noise_button)
        layout.addLayout(create)
        self._window = window

        self.error = QLabel()
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error.hide()
        layout.addWidget(self.error)

        footer = QHBoxLayout()
        privacy = QLabel(t("gui.privacy_footer"))
        privacy.setObjectName("Muted")
        footer.addWidget(privacy, 1)
        settings = QToolButton()
        settings.setObjectName("SettingsButton")
        settings.setText("⚙")
        settings.setToolTip(t("gui.settings.title"))
        settings.clicked.connect(window.open_settings)
        footer.addWidget(settings)
        layout.addLayout(footer)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def _make_qr(self) -> None:
        if self.qr_text.text().strip():
            self._window.open_text(self.qr_text.text())


class ConfigPage(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window_ = window
        self.sources: list[SourceFile] = []
        self.target: Format | None = None
        self.form: OptionsForm | None = None
        self.custom_output: Path | None = None  # single file: chosen file; many: folder

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        header = QHBoxLayout()
        back = QToolButton()
        back.setObjectName("BackButton")
        back.setText("←")
        back.setToolTip(t("gui.back"))
        back.clicked.connect(window.reset)
        header.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("FileTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        titles.addWidget(self.title)
        self.text_edit = QPlainTextEdit()  # content of a QR code typed or dropped in
        self.text_edit.setObjectName("QRText")
        self.text_edit.setMaximumHeight(84)
        self.text_edit.textChanged.connect(self._text_changed)
        self.text_edit.hide()
        titles.addWidget(self.text_edit)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        outer.addLayout(header)
        outer.addWidget(hline())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 6, 0)
        self.body_layout.setSpacing(10)
        scroll.setWidget(self.body)
        outer.addWidget(scroll, 1)

        self.targets_box = QWidget()
        self.targets_layout = QVBoxLayout(self.targets_box)
        self.targets_layout.setContentsMargins(0, 0, 0, 0)
        self.targets_layout.setSpacing(4)
        self.body_layout.addWidget(self.targets_box)
        self.missing_hint = QLabel()
        self.missing_hint.setObjectName("Muted")
        self.missing_hint.setWordWrap(True)
        self.missing_hint.setTextFormat(Qt.TextFormat.RichText)
        self.missing_hint.linkActivated.connect(lambda _link: window.open_settings())
        self.body_layout.addWidget(self.missing_hint)

        self.options_title = QLabel(t("gui.options"))
        self.options_title.setObjectName("Section")
        self.body_layout.addWidget(self.options_title)
        self.options_holder = QVBoxLayout()
        self.body_layout.addLayout(self.options_holder)
        self.body_layout.addStretch(1)

        outer.addWidget(hline())
        out_row = QHBoxLayout()
        out_caption = QLabel(t("gui.save_to"))
        out_caption.setObjectName("Muted")
        self.output_label = QLabel()
        self.output_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Preferred)
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.change_output = QPushButton(t("gui.change"))
        self.change_output.clicked.connect(self._choose_output)
        out_row.addWidget(out_caption)
        out_row.addWidget(self.output_label, 1)
        out_row.addWidget(self.change_output)
        outer.addLayout(out_row)

        actions = QHBoxLayout()
        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        actions.addWidget(self.note, 1)
        self.convert_button = QPushButton(t("gui.convert"))
        self.convert_button.setObjectName("Primary")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(window.start_conversion)
        actions.addWidget(self.convert_button)
        outer.addLayout(actions)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

    # -- population -----------------------------------------------------------------------

    def load(self, sources: list[SourceFile], choices: list[TargetChoice], note: str = "",
             keep_target: bool = False) -> None:
        previous = self.target.id if (keep_target and self.target) else None
        self.sources = sources
        self.target = None
        self.custom_output = None
        self.note.setText(note)
        self._fill_header()
        self._fill_targets(choices)
        self._set_form(None)
        if previous:
            for button in self.group.buttons():
                if button.property("format_id") == previous and button.isEnabled():
                    button.setChecked(True)
                    self._select(button.property("format"))
        self._update_output()

    def _fill_header(self) -> None:
        is_text = len(self.sources) == 1 and self.sources[0].format.id == "text"
        self.text_edit.setVisible(is_text)
        self.title.setToolTip("")
        if len(self.sources) == 1 and self.sources[0].path is None:
            s = self.sources[0]
            if is_text:
                self.title.setText(t("gui.qr_content"))
                if self.text_edit.toPlainText() != s.text:
                    self.text_edit.blockSignals(True)
                    self.text_edit.setPlainText(s.text or "")
                    self.text_edit.blockSignals(False)
                self.subtitle.setText(t("gui.qr_bytes", n=s.size))
            else:
                self.title.setText(s.format.label)
                self.subtitle.setText(t("gui.generated"))
        elif len(self.sources) == 1:
            s = self.sources[0]
            self.title.setText(s.path.name)
            parts = [s.format.label, format_size(s.size)]
            if s.media and s.media.duration:
                parts.append(format_duration(s.media.duration))
            if s.media and s.media.has_video and s.media.width:
                parts.append(f"{s.media.width}×{s.media.height}")
            self.subtitle.setText(" · ".join(parts))
        else:
            self.title.setText(t("gui.n_files", n=len(self.sources)))
            kinds = ", ".join(dict.fromkeys(s.format.label for s in self.sources))
            total = sum(s.size for s in self.sources)
            self.subtitle.setText(f"{kinds} · {format_size(total)}")
            self.title.setToolTip("\n".join(str(s.path) for s in self.sources))

    def _text_changed(self) -> None:
        if len(self.sources) == 1 and self.sources[0].format.id == "text":
            self.sources[0] = dataclasses.replace(self.sources[0],
                                                  text=self.text_edit.toPlainText())
            self.subtitle.setText(t("gui.qr_bytes", n=self.sources[0].size))
            self._update_convert_button()
            self._update_output()

    def _fill_targets(self, choices: list[TargetChoice]) -> None:
        for button in self.group.buttons():
            self.group.removeButton(button)
        while self.targets_layout.count():
            item = self.targets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        caption = QLabel(t("gui.convert_to"))
        caption.setObjectName("Section")
        self.targets_layout.addWidget(caption)
        missing: dict[str, None] = {}
        for category in CATEGORY_ORDER:
            in_cat = [c for c in choices if c.format.category is category]
            if not in_cat:
                continue
            label = QLabel(t(f"category.{category.value}"))
            label.setObjectName("CategoryLabel")
            self.targets_layout.addWidget(label)
            holder = QWidget()
            flow = FlowLayout(holder, spacing=6)
            for choice in in_cat:
                button = QPushButton(choice.format.label)
                button.setObjectName("TargetButton")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setProperty("format_id", choice.format.id)
                button.setProperty("format", choice.format)
                button.setAccessibleName(choice.format.label)
                if not choice.available:
                    button.setEnabled(False)
                    tools = ", ".join(TOOLS[x].label for x in choice.missing_tools)
                    hints = "\n".join(install_hint(x) for x in choice.missing_tools)
                    button.setToolTip(t("gui.needs_tool", tools=tools) + "\n" + hints)
                    missing.update(dict.fromkeys(choice.missing_tools))
                else:
                    button.clicked.connect(lambda _=False, f=choice.format: self._select(f))
                self.group.addButton(button)
                flow.addWidget(button)
            self.targets_layout.addWidget(holder)
        if missing:
            tools = ", ".join(TOOLS[x].label for x in missing)
            self.missing_hint.setText(t("gui.missing_hint", tools=tools))
            self.missing_hint.show()
        else:
            self.missing_hint.hide()

    def _select(self, fmt: Format) -> None:
        self.target = fmt
        if self.custom_output is not None and len(self.sources) == 1:
            self.custom_output = self.custom_output.with_suffix(f".{fmt.extension}")
        try:
            options = self.window_.converter.options(self.sources[0], fmt)
        except ConversionError as exc:
            self.note.setText(exc.message)
            options = []
        self._set_form(OptionsForm(options, self.sources[0].media))
        self._update_output()

    def _set_form(self, form: OptionsForm | None) -> None:
        if self.form is not None:
            self.form.setParent(None)
            self.form.deleteLater()
        self.form = form
        has_options = form is not None and bool(form.values())
        self.options_title.setVisible(has_options)
        if form is not None:
            form.changed.connect(self._update_convert_button)
            form.changed.connect(self._update_output)  # e.g. the seed is part of the name
            self.options_holder.addWidget(form)
        self._update_convert_button()

    def _update_convert_button(self) -> None:
        ok = self.target is not None and (self.form is None or self.form.is_valid())
        if ok and self.sources and self.sources[0].format.id == "text":
            ok = bool((self.sources[0].text or "").strip())
        self.convert_button.setEnabled(ok)

    def _values(self) -> dict:
        return self.form.conversion_values() if self.form and self.form.is_valid() else {}

    # -- output location --------------------------------------------------------------------

    def output_for_display(self) -> str:
        if len(self.sources) != 1:
            if self.custom_output:
                return str(self.custom_output)
            return t("gui.next_to_originals")
        source = self.sources[0]
        if self.target is None:
            return str(default_dir(source) or source.path.parent)
        return str(self.custom_output or self._default_output())

    def _default_output(self) -> Path:
        assert self.target is not None
        source = self.sources[0]
        return self.window_.converter.output_path(source, self.target, self._values(),
                                                  default_dir(source))

    def _update_output(self) -> None:
        text = self.output_for_display()
        metrics = self.output_label.fontMetrics()
        width = max(120, self.output_label.width())
        self.output_label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width))
        self.output_label.setToolTip(text)
        self.change_output.setEnabled(self.target is not None or len(self.sources) > 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_output()

    def _choose_output(self) -> None:
        if len(self.sources) == 1 and self.target is not None:
            start = self.custom_output or self._default_output()
            ext = self.target.extension
            path, _ = QFileDialog.getSaveFileName(
                self, t("gui.save_as"), str(start), f"{self.target.label} (*.{ext})"
            )
            if path:
                chosen = Path(path)
                if chosen.suffix.lower().lstrip(".") not in self.target.extensions:
                    chosen = chosen.with_name(f"{chosen.name}.{ext}")
                self.custom_output = chosen
        else:
            start = self.custom_output or self.sources[0].path.parent
            folder = QFileDialog.getExistingDirectory(self, t("gui.choose_folder"), str(start))
            if folder:
                self.custom_output = Path(folder)
        self._update_output()

    def jobs(self) -> list[Job]:
        assert self.target is not None
        values = self.form.conversion_values() if self.form else {}
        if len(self.sources) == 1:
            source = self.sources[0]
            return [Job(source, self.target, values, output=self.custom_output,
                        output_dir=default_dir(source))]
        return [Job(s, self.target, values, output_dir=self.custom_output) for s in self.sources]


class ProgressPage(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        self.emote = EmoteLabel("gif_owly_cook_slow")
        self.credit = emote_credit()
        layout.addWidget(self.emote, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        self.title = QLabel(t("gui.converting"))
        self.title.setObjectName("PageTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel()
        self.detail.setObjectName("Muted")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.cancel = QPushButton(t("gui.cancel"))
        self.cancel.clicked.connect(window.cancel_conversion)
        for w in (self.title, self.detail, self.bar):
            layout.addWidget(w)
        layout.addSpacing(12)
        layout.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self.credit)
        self.emote.setVisible(self.emote.is_valid())
        self.credit.setVisible(self.emote.is_valid())

    def set_job(self, text: str) -> None:
        self.detail.setText(text)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)

    def set_progress(self, fraction: float) -> None:
        if fraction < 0:
            self.bar.setRange(0, 0)  # busy indicator
        else:
            if self.bar.maximum() == 0:
                self.bar.setRange(0, 1000)
            self.bar.setValue(int(fraction * 1000))


class ResultPage(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window_ = window
        self.outputs: list[Path] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 24)
        layout.addStretch(1)
        self.icon = QLabel()
        self.icon.setObjectName("ResultIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emote = EmoteLabel("gif_owly_nerd")
        self.credit = emote_credit()
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_toggle = QToolButton()
        self.details_toggle.setText(t("gui.show_details"))
        self.details_toggle.setCheckable(True)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("Details")
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        layout.addWidget(self.emote, 0, Qt.AlignmentFlag.AlignCenter)
        for w in (self.icon, self.title, self.message):
            layout.addWidget(w)
        layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.details, 2)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        # Back to the same file's options, e.g. to try another format or other settings.
        self.again_button = QPushButton(t("gui.back_to_options"))
        self.again_button.clicked.connect(window.back_to_config)
        self.open_button = QPushButton(t("gui.open"))
        self.open_button.clicked.connect(lambda: open_file(self.outputs[0]))
        self.folder_button = QPushButton(t("gui.show_in_folder"))
        self.folder_button.clicked.connect(lambda: show_in_folder(self.outputs[0]))
        self.new_button = QPushButton(t("gui.new_file"))
        self.new_button.setObjectName("Primary")
        self.new_button.clicked.connect(window.reset)
        for b in (self.again_button, self.open_button, self.folder_button, self.new_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(self.credit)

    def show_result(self, outputs: list[Path], errors: list[tuple[str, str, str]]) -> None:
        self.outputs = outputs
        owl = not errors and self.emote.is_valid()
        self.emote.setVisible(owl)
        self.credit.setVisible(owl)
        self.icon.setVisible(not owl)
        details = "\n\n".join(f"{name}: {msg}\n{det}".strip() for name, msg, det in errors)
        rich = not errors and len(outputs) == 1
        self.message.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        if not errors:
            self.icon.setText("✓")
            self.icon.setProperty("state", "ok")
            self.title.setText(t("gui.done"))
            if len(outputs) == 1:
                self.message.setText(f"<b>{html.escape(outputs[0].name)}</b><br>"
                                     f"<span style='color: gray'>"
                                     f"{html.escape(str(outputs[0].parent))}</span>")
            else:
                self.message.setText(t("gui.done_many", n=len(outputs),
                                       folder=str(outputs[0].parent)))
        else:
            self.icon.setText("✗" if not outputs else "!")
            self.icon.setProperty("state", "error")
            if outputs:
                self.title.setText(t("gui.partial", ok=len(outputs), n=len(outputs) + len(errors)))
            else:
                self.title.setText(t("gui.failed"))
            self.message.setText("\n".join(f"{name}: {msg}" for name, msg, _ in errors))
        self.icon.style().unpolish(self.icon)
        self.icon.style().polish(self.icon)
        self.details.setPlainText(details)
        self.details_toggle.setChecked(False)
        self.details_toggle.setVisible(bool(details.strip()))
        self.open_button.setVisible(len(outputs) == 1)
        self.folder_button.setVisible(bool(outputs))


# --------------------------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, converter: Converter, settings: Settings) -> None:
        super().__init__()
        self.converter = converter
        self.settings = settings
        self.worker: ConversionWorker | None = None
        self._last_open = 0.0
        self._outputs: list[Path] = []
        self._errors: list[tuple[str, str, str]] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(680, 600)
        self.setMinimumSize(520, 460)

        self.stack = QStackedWidget()
        self.drop_page = DropPage(self)
        self.config_page = ConfigPage(self)
        self.progress_page = ProgressPage(self)
        self.result_page = ResultPage(self)
        for page in (self.drop_page, self.config_page, self.progress_page, self.result_page):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)

        QShortcut(QKeySequence.StandardKey.Open, self, activated=self.drop_page.drop.choose_files)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._escape)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste)

    # -- navigation -------------------------------------------------------------------------

    def busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def reset(self) -> None:
        if self.busy():
            return
        self.drop_page.show_error("")
        self.stack.setCurrentWidget(self.drop_page)

    def back_to_config(self) -> None:
        page = self.config_page
        if page.custom_output is not None and len(page.sources) == 1:
            # The chosen file holds the last result now; a second run must not overwrite it.
            page.custom_output = unique_path(page.custom_output)
        page._update_output()
        self.stack.setCurrentWidget(page)

    def _escape(self) -> None:
        if self.stack.currentWidget() is self.progress_page:
            self.cancel_conversion()
        elif self.stack.currentWidget() is not self.drop_page:
            self.reset()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.converter.locator, self)
        dialog.exec()
        if self.stack.currentWidget() is self.config_page and self.config_page.sources:
            # Tools may have been added: refresh which targets are available.
            try:
                sources = [self.converter.inspect(s.path) for s in self.config_page.sources]
            except ConversionError as exc:  # e.g. the file was deleted meanwhile
                self.config_page.note.setText(exc.message)
                return
            self.config_page.load(sources, self.converter.targets(sources), keep_target=True)

    # -- opening files ----------------------------------------------------------------------

    def open_files(self, paths: list[str]) -> None:
        self.raise_()
        self.activateWindow()
        if not paths:
            return
        if self.busy():
            self.statusBar().showMessage(t("gui.busy"), 4000)
            return
        merge = (self.stack.currentWidget() is self.config_page
                 and time.monotonic() - self._last_open < MERGE_WINDOW_S
                 and all(s.path is not None for s in self.config_page.sources))
        self._last_open = time.monotonic()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sources = list(self.config_page.sources) if merge else []
            known = {s.path for s in sources}
            skipped = []
            for p in paths:
                try:
                    source = self.converter.inspect(p)
                except ConversionError as exc:
                    skipped.append(exc.message)
                    continue
                if source.path not in known:
                    known.add(source.path)
                    sources.append(source)
            choices = self.converter.targets(sources) if sources else []
        finally:
            QApplication.restoreOverrideCursor()

        if not sources:
            self.drop_page.show_error("\n".join(skipped))
            self.stack.setCurrentWidget(self.drop_page)
            return
        if not choices:
            self.drop_page.show_error(t("error.no_common_target"))
            self.stack.setCurrentWidget(self.drop_page)
            return
        note = t("gui.skipped", n=len(skipped)) if skipped else ""
        self.config_page.note.setToolTip("\n".join(skipped))
        self.config_page.load(sources, choices, note, keep_target=merge)
        self.stack.setCurrentWidget(self.config_page)

    def open_text(self, text: str) -> None:
        """A link or text to turn into a QR code."""
        if text.strip():
            self._open_without_file(SourceFile.from_text(text.strip()))

    def open_generator(self, format_id: str) -> None:
        self._open_without_file(SourceFile.generator(format_id))

    def _open_without_file(self, source: SourceFile) -> None:
        self.raise_()
        self.activateWindow()
        if self.busy():
            self.statusBar().showMessage(t("gui.busy"), 4000)
            return
        self._last_open = 0.0  # files dropped next are not merged into this
        self.config_page.note.setToolTip("")
        self.config_page.load([source], self.converter.targets([source]))
        self.stack.setCurrentWidget(self.config_page)

    def _paste(self) -> None:
        if self.stack.currentWidget() is not self.drop_page or self.busy():
            return
        mime = QApplication.clipboard().mimeData()
        paths = local_paths(mime)
        if paths:
            self._last_open = 0.0
            self.open_files(paths)
        else:
            self.open_text(dropped_text(mime))

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if (mime.hasUrls() or mime.hasText()) and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = local_paths(event.mimeData())
        text = "" if paths else dropped_text(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._last_open = 0.0  # an explicit drop replaces the current selection
            self.open_files(paths)
        elif text:
            event.acceptProposedAction()
            self.open_text(text)

    # -- converting -------------------------------------------------------------------------

    def start_conversion(self) -> None:
        if self.busy() or self.config_page.target is None:
            return
        jobs = self.config_page.jobs()
        self._outputs, self._errors = [], []
        worker = ConversionWorker(self.converter, jobs)
        worker.job_started.connect(lambda i: self._on_job_started(jobs, i))
        worker.progress.connect(lambda _i, f: self.progress_page.set_progress(f))
        worker.job_finished.connect(lambda _i, path: self._outputs.append(Path(path)))
        worker.job_failed.connect(
            lambda i, msg, det: self._errors.append((jobs[i].source.name, msg, det))
        )
        worker.finished.connect(self._on_worker_finished)
        self.worker = worker
        self.progress_page.cancel.setEnabled(True)
        self.stack.setCurrentWidget(self.progress_page)
        worker.start()

    def _on_job_started(self, jobs: list[Job], index: int) -> None:
        job = jobs[index]
        target = job.target.label
        if job.target.category is Category.QR:  # "PNG" alone would be misleading
            target = f"{t('category.qr')} {target}"
        text = f"{job.source.name} → {target}"
        if len(jobs) > 1:
            text = f"{text}  ({index + 1}/{len(jobs)})"
        self.progress_page.set_job(text)

    def cancel_conversion(self) -> None:
        if self.worker is not None:
            self.progress_page.cancel.setEnabled(False)
            self.progress_page.detail.setText(t("gui.cancelling"))
            self.worker.cancel()

    def _on_worker_finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None and worker.cancelled and not self._outputs:
            self.config_page.note.setText(t("gui.cancelled"))
            self.stack.setCurrentWidget(self.config_page)
            self.config_page._update_output()
            return
        self.result_page.show_result(self._outputs, self._errors)
        self.stack.setCurrentWidget(self.result_page)
        # Default output names may have been taken now – refresh for a second run.
        QTimer.singleShot(0, self.config_page._update_output)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(10_000)
        super().closeEvent(event)
