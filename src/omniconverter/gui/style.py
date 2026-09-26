"""Stylesheet. Colors come from the palette so light and dark system themes both work."""

STYLESHEET = """
QLabel#DropTitle { font-size: 18px; font-weight: 600; }
QLabel#FileTitle { font-size: 16px; font-weight: 600; }
QLabel#PageTitle { font-size: 20px; font-weight: 600; }
QLabel#Section { font-weight: 600; margin-top: 6px; }
QLabel#CategoryLabel { color: palette(placeholder-text); margin-top: 4px; }
QLabel#Muted { color: palette(placeholder-text); }
QLabel#Credit { color: palette(placeholder-text); font-size: 11px; }
QLabel#Error { color: #d0453a; }
QLabel#Ok { color: #2e9d57; }
QLabel#ResultIcon { font-size: 48px; font-weight: 700; }
QLabel#ResultIcon[state="ok"] { color: #2e9d57; }
QLabel#ResultIcon[state="error"] { color: #d0453a; }

QFrame#DropArea {
    border: 2px dashed palette(mid);
    border-radius: 18px;
    background: palette(base);
}
QFrame#DropArea:hover, QFrame#DropArea[active="true"] {
    border-color: palette(highlight);
}

QPushButton#TargetButton {
    padding: 6px 14px;
    border: 1px solid palette(mid);
    border-radius: 14px;
    background: palette(button);
    min-width: 44px;
}
QPushButton#TargetButton:hover { border-color: palette(highlight); }
QPushButton#TargetButton:checked {
    background: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
QPushButton#TargetButton:disabled {
    color: palette(placeholder-text);
    border-style: dashed;
}

QPushButton#Primary {
    padding: 8px 22px;
    border-radius: 8px;
    border: 1px solid palette(highlight);
    background: palette(highlight);
    color: palette(highlighted-text);
    font-weight: 600;
}
QPushButton#Primary:disabled {
    background: palette(button);
    color: palette(placeholder-text);
    border-color: palette(mid);
}

QToolButton#BackButton, QToolButton#SettingsButton {
    font-size: 18px;
    border: none;
    padding: 2px 8px;
}
QToolButton#AdvancedToggle { border: none; font-weight: 600; padding: 4px 0; }
QLineEdit[invalid="true"] { border: 1px solid #d0453a; }
QPlainTextEdit#QRText { font-family: monospace; }
QPlainTextEdit#Details { font-family: monospace; font-size: 11px; }
QFrame#Separator { color: palette(midlight); }

QFrame#PreviewCanvas {
    border: 1px solid palette(midlight);
    border-radius: 8px;
    background: palette(base);
}
QToolButton#PreviewToggle { padding: 2px 8px; border: 1px solid palette(mid); border-radius: 6px; }
QToolButton#PreviewToggle:checked {
    background: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
QLabel#PreviewInfo { color: palette(placeholder-text); }
QLabel#PreviewInfo[error="true"] { color: #d0453a; }
"""
