"""Renders a backend's option schema as a form (main options + collapsible "Advanced")."""

from __future__ import annotations

import secrets
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omniconverter.core.errors import OptionError
from omniconverter.core.options import Kind, Option, format_time, parse_time
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = color
        self.clicked.connect(self._pick)
        self._update()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color), self)
        if chosen.isValid():
            self.color = chosen.name()
            self._update()
            self.changed.emit()

    def _update(self) -> None:
        self.setText(self.color)
        self.setStyleSheet(f"QPushButton {{ border-left: 18px solid {self.color}; }}")


class OptionsForm(QWidget):
    """Emits ``changed`` whenever a value changes; ``values()`` returns typed values."""

    changed = Signal()

    def __init__(self, options: list[Option], media: MediaInfo | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._widgets: dict[str, QWidget] = {}
        self._fields: dict[str, QWidget] = {}  # what sits in the form row (widget or a box)
        self._rows: dict[str, tuple[QFormLayout, int]] = {}
        self._media = media

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._main = self._make_form()
        layout.addLayout(self._main)

        advanced = [o for o in options if o.advanced]
        self._advanced_box = QWidget()
        self._advanced = self._make_form()
        self._advanced.setContentsMargins(0, 0, 0, 0)
        self._advanced_box.setLayout(self._advanced)
        self._advanced_box.setVisible(False)
        self._toggle = QToolButton()
        self._toggle.setObjectName("AdvancedToggle")
        self._toggle.setText(t("gui.advanced"))
        self._toggle.setCheckable(True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle.toggled.connect(self._toggle_advanced)
        if advanced:
            layout.addWidget(self._toggle)
            layout.addWidget(self._advanced_box)

        for opt in options:
            self._add(opt, self._advanced if opt.advanced else self._main)
        self._align_labels()
        self._update_visibility()

    def _align_labels(self) -> None:
        """Give both forms the same label column so the fields line up."""
        labels = [form.labelForField(self._fields[key]) for key, (form, _row) in
                  self._rows.items()]
        labels = [label for label in labels if label is not None]
        if labels:
            width = max(label.sizeHint().width() for label in labels)
            for label in labels:
                label.setMinimumWidth(width)

    @staticmethod
    def _make_form() -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        return form

    def _toggle_advanced(self, on: bool) -> None:
        self._advanced_box.setVisible(on)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _add(self, opt: Option, form: QFormLayout) -> None:
        widget: QWidget
        if opt.kind is Kind.CHOICE:
            combo = QComboBox()
            for value, label in opt.choices:
                combo.addItem(label, value)
            values = [v for v, _ in opt.choices]
            combo.setCurrentIndex(values.index(opt.default) if opt.default in values else 0)
            combo.currentIndexChanged.connect(self._on_change)
            widget = combo
        elif opt.kind is Kind.INT:
            spin = QSpinBox()
            spin.setRange(opt.minimum if opt.minimum is not None else -(2**31),
                          opt.maximum if opt.maximum is not None else 2**31 - 1)
            spin.setValue(int(opt.default or 0))
            spin.setSuffix(opt.suffix)
            spin.setMinimumWidth(110)
            spin.valueChanged.connect(self._on_change)
            widget = spin
        elif opt.kind is Kind.BOOL:
            box = QCheckBox(opt.label)
            box.setChecked(bool(opt.default))
            box.toggled.connect(self._on_change)
            widget = box
        elif opt.kind is Kind.TIME:
            edit = QLineEdit(format_time(opt.default))
            edit.setMaximumWidth(140)
            if opt.key == "end" and self._media and self._media.duration:
                edit.setPlaceholderText(format_time(round(self._media.duration, 3)))
            else:
                edit.setPlaceholderText("0:00")
            edit.textChanged.connect(self._on_change)
            widget = edit
        elif opt.kind is Kind.COLOR:
            button = ColorButton(opt.default or "#ffffff")
            button.changed.connect(self._on_change)
            widget = button
        else:
            edit = QLineEdit(str(opt.default or ""))
            edit.setPlaceholderText(opt.help)
            edit.textChanged.connect(self._on_change)
            widget = edit
        if opt.help:
            widget.setToolTip(opt.help)
        widget.setObjectName(f"opt_{opt.key}")
        self._widgets[opt.key] = widget
        field = widget
        if opt.kind is Kind.INT and opt.randomize:
            field = QWidget()
            row = QHBoxLayout(field)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget)
            dice = QToolButton()
            dice.setObjectName(f"random_{opt.key}")
            dice.setText("🎲")
            dice.setToolTip(t("gui.randomize"))
            dice.clicked.connect(lambda _=False, o=opt, w=widget: w.setValue(_random_value(o)))
            row.addWidget(dice)
        self._fields[opt.key] = field
        if opt.kind is Kind.BOOL:
            form.addRow(field)
        else:
            form.addRow(opt.label, field)
        self._rows[opt.key] = (form, form.rowCount() - 1)

    def _on_change(self, *_args: Any) -> None:
        self._update_visibility()
        self._validate()
        self.changed.emit()

    def _update_visibility(self) -> None:
        values = self.values()
        for opt in self._options:
            form, row = self._rows[opt.key]
            form.setRowVisible(row, opt.is_visible(values))

    def _validate(self) -> None:
        for opt in self._options:
            if opt.kind is Kind.TIME:
                widget = self._widgets[opt.key]
                widget.setProperty("invalid", self._time_value(opt) is _INVALID)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def _time_value(self, opt: Option) -> Any:
        text = self._widgets[opt.key].text()  # type: ignore[attr-defined]
        try:
            return parse_time(text, opt.key)
        except OptionError:
            return _INVALID

    def is_valid(self) -> bool:
        values = self.values()
        return not any(v is _INVALID for v in values.values())

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for opt in self._options:
            w = self._widgets.get(opt.key)
            if w is None:
                result[opt.key] = opt.default
            elif opt.kind is Kind.CHOICE:
                result[opt.key] = w.currentData()  # type: ignore[attr-defined]
            elif opt.kind is Kind.INT:
                result[opt.key] = w.value()  # type: ignore[attr-defined]
            elif opt.kind is Kind.BOOL:
                result[opt.key] = w.isChecked()  # type: ignore[attr-defined]
            elif opt.kind is Kind.TIME:
                result[opt.key] = self._time_value(opt)
            elif opt.kind is Kind.COLOR:
                result[opt.key] = w.color  # type: ignore[attr-defined]
            else:
                result[opt.key] = w.text()  # type: ignore[attr-defined]
        return result

    def conversion_values(self) -> dict[str, Any]:
        """Values ready for :meth:`Converter.convert` (only call when :meth:`is_valid`)."""
        return {k: v for k, v in self.values().items() if v is not _INVALID}

    def widget(self, key: str) -> QWidget:
        return self._widgets[key]


def _random_value(opt: Option) -> int:
    low = opt.minimum if opt.minimum is not None else 0
    high = min(opt.maximum if opt.maximum is not None else 999_999, low + 999_999)
    return low + secrets.randbelow(high - low + 1)


class _Invalid:
    def __repr__(self) -> str:
        return "<invalid>"


_INVALID = _Invalid()
