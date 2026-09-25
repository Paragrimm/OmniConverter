"""Backend interface. A backend wraps one conversion engine (FFmpeg, Pillow, Pandoc, …)."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from omniconverter.core.errors import Cancelled
from omniconverter.core.formats import Format
from omniconverter.core.options import Option
from omniconverter.core.probe import MediaInfo
from omniconverter.core.tools import ToolLocator

ProgressCallback = Callable[[float | None], None]


@dataclass(frozen=True)
class Conversion:
    """One source → target pair a backend can handle."""

    source: str
    target: str
    requires: tuple[str, ...] = ()  # tool ids that must be installed
    priority: int = 50  # the highest-priority *available* backend wins


@dataclass
class ConversionRequest:
    source: Path | None  # None for sources without a file (typed text, generators)
    source_format: Format
    target_format: Format
    options: dict[str, Any] = field(default_factory=dict)
    media: MediaInfo | None = None
    text: str | None = None  # content of a text source


class ConversionContext:
    """What a running conversion may use: tools, a private work dir, progress and cancel."""

    def __init__(
        self,
        locator: ToolLocator,
        work_dir: Path,
        cancel: threading.Event | None = None,
        on_progress: ProgressCallback | None = None,
        final_path: Path | None = None,
    ) -> None:
        self.locator = locator
        self.work_dir = work_dir
        self.cancel = cancel or threading.Event()
        self._on_progress = on_progress
        # Where the result ends up; the backend itself writes to a temporary name.
        self.final_path = final_path
        # Extra files saved next to the result, e.g. an OBJ's .mtl: {file name: content}.
        self.companions: dict[str, bytes] = {}

    def progress(self, fraction: float | None) -> None:
        """Report progress in ``[0, 1]``; ``None`` means indeterminate."""
        if self._on_progress is not None:
            if fraction is not None:
                fraction = min(1.0, max(0.0, fraction))
            self._on_progress(fraction)

    def check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


class Backend(ABC):
    id: ClassVar[str]

    @abstractmethod
    def conversions(self) -> Iterable[Conversion]:
        """All pairs this backend can convert (also those whose tools are missing)."""

    def supports(self, conversion: Conversion, media: MediaInfo | None) -> bool:
        """Refine support using the inspected file, e.g. no video targets for audio-only MP4."""
        return True

    def options(
        self, source: Format, target: Format, media: MediaInfo | None = None
    ) -> list[Option]:
        return []

    def output_stem(self, request: ConversionRequest) -> str | None:
        """File name (without extension) for sources without a file, e.g. ``noise-42``."""
        return None

    @abstractmethod
    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        """Convert ``request.source`` and write the result to *output*."""
