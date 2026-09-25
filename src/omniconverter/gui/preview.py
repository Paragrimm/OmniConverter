"""Live preview next to the options: rendered in the background, stills and animations."""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omniconverter.core.backend import Preview
from omniconverter.core.converter import Converter, SourceFile
from omniconverter.core.errors import Cancelled, ConversionError
from omniconverter.core.formats import Format
from omniconverter.gui.widgets import format_size
from omniconverter.i18n import current_language, t

DEBOUNCE_MS = 350  # changes arriving this quickly (typing, spinning) make one preview
BUSY_AFTER_MS = 300  # only then say "rendering", so quick previews do not flicker
END_PAUSE_MS = 700  # videos rest on their last frame: that is where the cut is
MAX_UPSCALE = 8.0  # tiny images (icons, QR codes) are enlarged, but not endlessly


@dataclass
class Rendered:
    """A preview whose files have been read into memory (the temp folder is gone already)."""

    preview: Preview
    frames: list[bytes]  # encoded PNG/JPEG: small, decoded only for display
    original: bytes | None


class PreviewWorker(QThread):
    rendered = Signal(int, object)  # generation, Rendered
    failed = Signal(int, str)  # generation, message

    def __init__(self, converter: Converter, source: SourceFile, target: Format,
                 values: dict[str, Any], generation: int) -> None:
        super().__init__()
        self.converter = converter
        self.source = source
        self.target = target
        self.values = values
        self.generation = generation
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        work = Path(tempfile.mkdtemp(prefix="omniconverter-preview-"))
        try:
            preview = self.converter.preview(self.source, self.target, self.values, work,
                                             cancel=self._cancel)
            frames = [p.read_bytes() for p in preview.frames]
            original = preview.original.read_bytes() if preview.original else None
            if not frames:
                raise ConversionError(t("error.no_output"))
            if QImage.fromData(frames[0]).isNull():  # e.g. a Qt without its JPEG plugin
                frames = [as_png(data) for data in frames]
        except Cancelled:
            return
        except ConversionError as exc:
            self.failed.emit(self.generation, exc.message)
        except Exception as exc:  # a preview must never take the window down
            self.failed.emit(self.generation, str(exc) or type(exc).__name__)
        else:
            self.rendered.emit(self.generation, Rendered(preview, frames, original))
        finally:
            shutil.rmtree(work, ignore_errors=True)  # nothing of the preview stays on disk


class PreviewCanvas(QFrame):
    """Shows one image: fitted into the frame, or at 100 % and dragged around."""

    actual_size_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewCanvas")
        self.setContentsMargins(4, 4, 4, 4)
        self.setMinimumSize(220, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image: QImage | None = None
        self.actual_size = False
        self._fitted: QPixmap | None = None
        self._offset = QPoint(0, 0)  # scroll position at 100 %
        self._drag_from: QPoint | None = None

    def set_image(self, image: QImage | None) -> None:
        self.image = image if image is not None and not image.isNull() else None
        self._fitted = None
        self._clamp()
        self._update_cursor()
        self.update()

    def set_actual_size(self, on: bool) -> None:
        if on == self.actual_size:
            return
        self.actual_size = on
        if on and self.image is not None:  # start in the middle
            area = self.contentsRect()
            self._offset = QPoint((self.image.width() - area.width()) // 2,
                                  (self.image.height() - area.height()) // 2)
        self._clamp()
        self._update_cursor()
        self.update()
        self.actual_size_changed.emit(on)

    # -- geometry -----------------------------------------------------------------------------

    def _image_rect(self) -> QRect:
        assert self.image is not None
        area = self.contentsRect()
        width, height = self.image.width(), self.image.height()
        if self.actual_size:
            x = area.x() + (area.width() - width) // 2 if width <= area.width() else (
                area.x() - self._offset.x())
            y = area.y() + (area.height() - height) // 2 if height <= area.height() else (
                area.y() - self._offset.y())
            return QRect(x, y, width, height)
        scale = min(area.width() / width, area.height() / height, MAX_UPSCALE)
        size = QSize(max(1, round(width * scale)), max(1, round(height * scale)))
        return QRect(area.x() + (area.width() - size.width()) // 2,
                     area.y() + (area.height() - size.height()) // 2,
                     size.width(), size.height())

    def _clamp(self) -> None:
        if self.image is None:
            self._offset = QPoint(0, 0)
            return
        area = self.contentsRect()
        max_x = max(0, self.image.width() - area.width())
        max_y = max(0, self.image.height() - area.height())
        self._offset = QPoint(min(max(0, self._offset.x()), max_x),
                              min(max(0, self._offset.y()), max_y))

    def _pannable(self) -> bool:
        if not self.actual_size or self.image is None:
            return False
        area = self.contentsRect()
        return self.image.width() > area.width() or self.image.height() > area.height()

    def _update_cursor(self) -> None:
        if self._pannable():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    # -- painting -----------------------------------------------------------------------------

    def _checker(self) -> QPixmap:
        dark = self.palette().window().color().lightness() < 128
        a, b = (QColor("#3a3a3a"), QColor("#2e2e2e")) if dark else (QColor("#ffffff"),
                                                                  QColor("#dcdcdc"))
        tile = QPixmap(16, 16)
        tile.fill(a)
        painter = QPainter(tile)
        painter.fillRect(0, 0, 8, 8, b)
        painter.fillRect(8, 8, 8, 8, b)
        painter.end()
        return tile

    def _fitted_pixmap(self, size: QSize) -> QPixmap:
        """The image scaled for the screen (in device pixels, so it stays sharp on HiDPI)."""
        assert self.image is not None
        ratio = self.devicePixelRatioF()
        device = QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
        if self._fitted is None or self._fitted.size() != device:
            smooth = device.width() < self.image.width()  # enlarged pixels stay crisp
            mode = (Qt.TransformationMode.SmoothTransformation if smooth
                    else Qt.TransformationMode.FastTransformation)
            scaled = self.image.scaled(device, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
            self._fitted = QPixmap.fromImage(scaled)
            self._fitted.setDevicePixelRatio(ratio)
        return self._fitted

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.image is None:
            return
        painter = QPainter(self)
        painter.setClipRect(self.contentsRect())
        rect = self._image_rect()
        if self.image.hasAlphaChannel():
            painter.setBrushOrigin(rect.topLeft())
            painter.fillRect(rect, QBrush(self._checker()))
        if self.actual_size:
            painter.drawImage(rect.topLeft(), self.image)
        else:
            painter.drawPixmap(rect.topLeft(), self._fitted_pixmap(rect.size()))
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp()
        self._update_cursor()

    # -- mouse ------------------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.image is not None:
            self.set_actual_size(not self.actual_size)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pannable():
            self._drag_from = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            now = event.position().toPoint()
            self._offset -= now - self._drag_from
            self._drag_from = now
            self._clamp()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self._update_cursor()

    def wheelEvent(self, event) -> None:
        if not self._pannable():
            super().wheelEvent(event)
            return
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        self._offset -= QPoint(delta.x(), delta.y())
        self._clamp()
        self.update()


class PreviewPanel(QWidget):
    """The preview column: canvas, result/original switch, player and a line of facts.

    Requests are bundled for a moment and the newest one wins: a running preview is cancelled
    (which stops FFmpeg at once), and only the latest request is rendered after it.
    """

    def __init__(self, converter: Converter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.converter = converter
        self.rendered: Rendered | None = None
        self._worker: PreviewWorker | None = None
        self._pending: tuple[SourceFile, Format, dict[str, Any]] | None = None
        self._last: tuple[SourceFile, Format, dict[str, Any], str] | None = None
        self._interrupted = False  # stop() came before the last request was shown
        self._generation = 0
        self._index = 0
        self._playing = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel(t("gui.preview"))
        title.setObjectName("Section")
        self.name = QLabel()
        self.name.setObjectName("Muted")
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.zoom = QToolButton()
        self.zoom.setObjectName("PreviewToggle")
        self.zoom.setText("1:1")
        self.zoom.setCheckable(True)
        self.zoom.setToolTip(t("gui.preview_actual_size"))
        header.addWidget(title)
        header.addWidget(self.name, 1)
        header.addWidget(self.zoom)
        layout.addLayout(header)

        self.canvas = PreviewCanvas()
        self.zoom.toggled.connect(self.canvas.set_actual_size)
        self.canvas.actual_size_changed.connect(self.zoom.setChecked)
        layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.result_button = QToolButton()
        self.original_button = QToolButton()
        self.compare = QButtonGroup(self)
        for button, key in ((self.result_button, "gui.preview_result"),
                            (self.original_button, "gui.preview_original")):
            button.setObjectName("PreviewToggle")
            button.setText(t(key))
            button.setCheckable(True)
            self.compare.addButton(button)
            controls.addWidget(button)
        self.result_button.setChecked(True)
        self.compare.buttonToggled.connect(lambda *_: self._show_frame())
        self.play = QToolButton()
        self.play.setObjectName("PreviewToggle")
        self.play.clicked.connect(self._toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(self._pause)
        self.slider.valueChanged.connect(self._seek)
        self.time = QLabel()
        self.time.setObjectName("Muted")
        for w in (self.play, self.slider, self.time):
            controls.addWidget(w, 10 if w is self.slider else 0)
        controls.addStretch(1)  # keeps the buttons together when there is no slider
        layout.addLayout(controls)

        self.info = QLabel()
        self.info.setObjectName("PreviewInfo")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)

        self._debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start)
        self._busy = QTimer(self, singleShot=True, interval=BUSY_AFTER_MS)
        self._busy.timeout.connect(lambda: self._set_info(t("gui.preview_busy")))
        self._frame_timer = QTimer(self, singleShot=True)
        self._frame_timer.timeout.connect(self._next_frame)
        self._update_controls()

    # -- requests ---------------------------------------------------------------------------

    def request(self, source: SourceFile, target: Format, values: dict[str, Any] | None,
                label: str = "") -> None:
        """Preview *target* for *source*; ``values=None`` means the options are half-typed."""
        self.name.setText(label)
        self.name.setToolTip(label)
        if values is None:
            self._pending = None
            self._debounce.stop()
            self._set_info(t("gui.preview_invalid"))
            return
        self._pending = (source, target, dict(values))
        self._last = (source, target, dict(values), label)
        self._debounce.start()

    def stop(self) -> None:
        """Forget what is waiting and cancel what is running; the picture stays."""
        self._interrupted = self._interrupted or self.busy()
        self._pending = None
        self._debounce.stop()
        self._busy.stop()
        if self._worker is not None:
            self._worker.cancel()

    def resume(self) -> None:
        """Render the last request again if :meth:`stop` interrupted it."""
        if self._interrupted and self._last is not None:
            self._interrupted = False
            self.request(*self._last)

    def clear(self) -> None:
        """Nothing to show any more, e.g. another file was opened."""
        self.stop()
        self._last, self._interrupted = None, False
        self._generation += 1  # a result still on its way is outdated
        self.rendered = None
        self._index = 0
        self.canvas.set_image(None)
        self.canvas.set_actual_size(False)
        self._set_info("")
        self._update_controls()

    def shutdown(self) -> None:
        self.stop()
        if self._worker is not None:
            self._worker.wait(10_000)

    def busy(self) -> bool:
        return self._worker is not None or self._pending is not None

    def _start(self) -> None:
        if self._pending is None:
            return
        if self._worker is not None:  # the newest request starts once this one has stopped
            self._worker.cancel()
            return
        source, target, values = self._pending
        self._pending = None
        self._generation += 1
        worker = PreviewWorker(self.converter, source, target, values, self._generation)
        worker.rendered.connect(self._on_rendered)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self._busy.start()
        worker.start()

    def _on_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait()  # "finished" comes just before the thread ends; never delete it early
        if self._pending is not None:
            self._start()

    def _current(self, generation: int) -> bool:
        return generation == self._generation and self._pending is None

    def _on_rendered(self, generation: int, rendered: Rendered) -> None:
        if not self._current(generation):
            return
        self._busy.stop()
        self._interrupted = False
        self.rendered = rendered
        self._index = min(self._index, len(rendered.frames) - 1)
        if not rendered.preview.durations_ms:
            self._index = 0
        if rendered.original is None:
            self.result_button.setChecked(True)
        self._set_info(describe(rendered.preview))
        self._update_controls()
        self._show_frame()
        self._schedule()

    def _on_failed(self, generation: int, message: str) -> None:
        if not self._current(generation):
            return
        self._busy.stop()
        self._interrupted = False
        self.rendered = None
        self.canvas.set_image(None)
        self._update_controls()
        self._set_info(message, error=True)

    # -- showing ----------------------------------------------------------------------------

    def _set_info(self, text: str, error: bool = False) -> None:
        self.info.setText(text)
        self.info.setProperty("error", error)
        self.info.style().unpolish(self.info)
        self.info.style().polish(self.info)

    def _animated(self) -> bool:
        return self.rendered is not None and len(self.rendered.frames) > 1

    def _update_controls(self) -> None:
        has_original = self.rendered is not None and self.rendered.original is not None
        for button in (self.result_button, self.original_button):
            button.setVisible(has_original)
        animated = self._animated()
        for w in (self.play, self.slider, self.time):
            w.setVisible(animated)
        if animated:
            assert self.rendered is not None
            self.slider.blockSignals(True)
            self.slider.setRange(0, len(self.rendered.frames) - 1)
            self.slider.blockSignals(False)
        icon = (QStyle.StandardPixmap.SP_MediaPause if self._playing
                else QStyle.StandardPixmap.SP_MediaPlay)
        self.play.setIcon(self.style().standardIcon(icon))
        self.play.setToolTip(t("gui.preview_pause" if self._playing else "gui.preview_play"))

    def _show_frame(self) -> None:
        if self.rendered is None:
            return
        if self.original_button.isChecked() and self.rendered.original is not None:
            data = self.rendered.original
        else:
            data = self.rendered.frames[self._index]
        self.canvas.set_image(QImage.fromData(data))
        if self._animated():
            self.slider.blockSignals(True)
            self.slider.setValue(self._index)
            self.slider.blockSignals(False)
            stamps = self.rendered.preview.timestamps
            self.time.setText(clock(stamps[self._index]) if stamps else
                              f"{self._index + 1}/{len(self.rendered.frames)}")

    def _schedule(self) -> None:
        self._frame_timer.stop()
        if not (self._playing and self._animated() and self.isVisible()):
            return
        assert self.rendered is not None
        preview = self.rendered.preview
        wait = preview.durations_ms[self._index]
        if preview.span is not None and self._index == len(self.rendered.frames) - 1:
            wait += END_PAUSE_MS
        self._frame_timer.start(wait)

    def _next_frame(self) -> None:
        if self._animated():
            assert self.rendered is not None
            self._index = (self._index + 1) % len(self.rendered.frames)
            self._show_frame()
        self._schedule()

    def _toggle_play(self) -> None:
        self._playing = not self._playing
        self._update_controls()
        self._schedule()

    def _pause(self) -> None:
        if self._playing:
            self._toggle_play()

    def _seek(self, index: int) -> None:
        if self._animated() and index != self._index:
            self._pause()
            self._index = index
            self._show_frame()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._frame_timer.stop()


def as_png(data: bytes) -> bytes:
    """Re-encode an image Qt cannot read as PNG, which Qt always can."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        out = io.BytesIO()
        im.save(out, format="PNG", compress_level=1)
    return out.getvalue()


def clock(seconds: float) -> str:
    """``1:05.3`` – minutes, seconds and tenths, as in the trim fields."""
    minutes, secs = divmod(max(0.0, seconds), 60)
    if round(secs, 1) >= 60:
        minutes, secs = minutes + 1, 0.0
    text = f"{int(minutes)}:{secs:04.1f}"
    return text.replace(".", ",") if current_language() == "de" else text


def describe(preview: Preview) -> str:
    """The facts line under the picture: part, size in pixels, file size, notes."""
    parts = []
    if preview.span is not None:
        parts.append(f"{clock(preview.span[0])}–{clock(preview.span[1])}")
    if preview.width and preview.height:
        parts.append(f"{preview.width}×{preview.height}")
    if preview.size_bytes is not None:
        prefix = "≈ " if preview.estimated else ""
        parts.append(prefix + format_size(preview.size_bytes))
    if preview.note:
        parts.append(preview.note)
    return " · ".join(parts)
