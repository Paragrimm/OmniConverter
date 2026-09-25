"""Declarative conversion options.

Backends describe their options with :class:`Option`; the GUI renders them as widgets and
the CLI parses ``--set key=value`` pairs with the very same schema.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from omniconverter.core.errors import OptionError


class Kind(StrEnum):
    CHOICE = "choice"
    INT = "int"
    BOOL = "bool"
    TIME = "time"  # seconds as float, None = unset
    COLOR = "color"  # "#rrggbb"
    TEXT = "text"


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    kind: Kind
    default: Any = None
    choices: tuple[tuple[Any, str], ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    suffix: str = ""
    advanced: bool = False
    # All conditions must hold for the option to be visible/relevant: ((key, (values...)), ...)
    visible_if: tuple[tuple[str, tuple[Any, ...]], ...] = ()
    help: str = ""

    def is_visible(self, values: Mapping[str, Any]) -> bool:
        return all(values.get(key) in allowed for key, allowed in self.visible_if)

    def parse(self, raw: Any) -> Any:
        """Convert a raw value (from CLI text or a widget) into the typed option value."""
        if self.kind is Kind.BOOL:
            return parse_bool(raw, self.key)
        if self.kind is Kind.INT:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise OptionError(self.key, f"not an integer: {raw!r}") from None
            if self.minimum is not None and value < self.minimum:
                raise OptionError(self.key, f"must be ≥ {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise OptionError(self.key, f"must be ≤ {self.maximum}")
            return value
        if self.kind is Kind.TIME:
            return parse_time(raw, self.key)
        if self.kind is Kind.COLOR:
            text = str(raw).strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
                raise OptionError(self.key, f"expected a color like #ffffff, got {raw!r}")
            return text.lower()
        if self.kind is Kind.CHOICE:
            for value, _label in self.choices:
                if raw == value or str(raw).lower() == str(value).lower():
                    return value
            allowed = ", ".join(str(v) for v, _ in self.choices)
            raise OptionError(self.key, f"{raw!r} is not one of: {allowed}")
        return "" if raw is None else str(raw)


def when(key: str, *values: Any) -> tuple[tuple[str, tuple[Any, ...]], ...]:
    """Shorthand for ``visible_if``: visible when option *key* has one of *values*."""
    return ((key, values),)


def parse_bool(raw: Any, key: str = "") -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "ja", "j"}:
        return True
    if text in {"0", "false", "no", "n", "off", "nein"}:
        return False
    raise OptionError(key, f"expected yes/no, got {raw!r}")


def parse_time(raw: Any, key: str = "") -> float | None:
    """Parse ``90``, ``1:30``, ``00:01:30.5`` or ``1:30,25`` into seconds."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        if raw < 0:
            raise OptionError(key, "time must not be negative")
        return float(raw)
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    if not re.fullmatch(r"\d+(\.\d+)?(:\d{1,2}(\.\d+)?){0,2}", text):
        raise OptionError(key, f"invalid time {raw!r} (use e.g. 1:30 or 00:01:30.5)")
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds: float | None) -> str:
    """Format seconds as ``h:mm:ss.mmm`` / ``m:ss`` (inverse of :func:`parse_time`)."""
    if seconds is None:
        return ""
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return f"{text}.{ms:03d}" if ms else text


def resolve(options: Iterable[Option], raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fill defaults, parse and validate raw values. Unknown keys raise :class:`OptionError`."""
    raw = dict(raw or {})
    result: dict[str, Any] = {}
    for opt in options:
        result[opt.key] = opt.parse(raw.pop(opt.key)) if opt.key in raw else opt.default
    if raw:
        unknown = ", ".join(sorted(raw))
        raise OptionError(unknown, "unknown option")
    return result
