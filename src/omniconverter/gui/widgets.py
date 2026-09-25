"""Small reusable widgets and helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from omniconverter.i18n import current_language, t
from omniconverter.integration import RESOURCES
from omniconverter.runtime import child_env

EMOTE_CREDIT_URL = "https://roamingowl.itch.io/owlish-emotes"
EMOTE_CREDIT_HTML = f'Emotes by <a href="{EMOTE_CREDIT_URL}">RoamingOwl</a>'


def app_icon() -> QIcon:
    icon = QIcon()
    for name in ("omniconverter.svg", "omniconverter.png"):
        path = RESOURCES / name
        if path.exists():
            icon.addFile(str(path))
    return icon


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            text = f"{value:.0f}" if unit == "B" else f"{value:.1f}"
            if current_language() == "de":
                text = text.replace(".", ",")
            return f"{text} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def format_duration(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def open_file(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path: Path) -> None:
    """Open the file manager with *path* selected (falls back to opening the folder)."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{path}"')
            return
        gdbus = shutil.which("gdbus")
        if gdbus:
            result = subprocess.run(
                [gdbus, "call", "--session", "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems",
                 f"['{path.as_uri()}']", ""],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False,
                env=child_env(),
            )
            if result.returncode == 0:
                return
    except (OSError, subprocess.SubprocessError):
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class FlowLayout(QLayout):
    """Lays out children left to right, wrapping into new lines (like text)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def generated_output_dir() -> Path:
    """Default folder for results without a source file (QR codes, noise maps)."""
    from platformdirs import user_pictures_dir

    pictures = Path(user_pictures_dir())
    return pictures if pictures.is_dir() else Path.home()


class EmoteLabel(QLabel):
    """An animated owl emote (see resources/emotes), crisp on HiDPI, playing while visible."""

    def __init__(self, name: str, size: int = 128, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(size, size)
        self._size = size
        self._frames: dict[tuple[int, float], QPixmap] = {}
        self.movie_ = QMovie(str(RESOURCES / "emotes" / f"{name}.gif"), parent=self)
        self.movie_.setCacheMode(QMovie.CacheMode.CacheAll)
        self.movie_.frameChanged.connect(self._show_frame)

    def is_valid(self) -> bool:
        return self.movie_.isValid()

    def _show_frame(self, number: int) -> None:
        ratio = self.devicePixelRatioF()
        key = (number, ratio)
        if key not in self._frames:
            side = round(self._size * ratio)
            pixmap = self.movie_.currentPixmap().scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            self._frames[key] = pixmap
        self.setPixmap(self._frames[key])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.is_valid():
            self.movie_.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.movie_.stop()


def emote_credit() -> QLabel:
    label = QLabel(EMOTE_CREDIT_HTML)
    label.setObjectName("Credit")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class DropArea(QFrame):
    """The big "drop a file here or click" area on the start page."""

    files_chosen = Signal(list)
    text_dropped = Signal(str)  # a link from the browser or dragged text

    def __init__(self, file_filter: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropArea")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._filter = file_filter

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(72, 72))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(t("gui.drop.title"))
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(t("gui.drop.hint"))
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (icon, title, hint):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(w)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose_files()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, t("gui.drop.dialog"), "", self._filter)
        if paths:
            self.files_chosen.emit(paths)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        paths = local_paths(event.mimeData())
        text = "" if paths else dropped_text(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.files_chosen.emit(paths)
        elif text:
            event.acceptProposedAction()
            self.text_dropped.emit(text)


def local_paths(mime) -> list[str]:
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]


def dropped_text(mime) -> str:
    """Web links or plain text (not files) from a drop or the clipboard."""
    links = [u.toString() for u in mime.urls() if not u.isLocalFile()]
    if links:
        return "\n".join(links)
    return mime.text().strip() if mime.hasText() and not mime.hasUrls() else ""


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setObjectName("Separator")
    return line
