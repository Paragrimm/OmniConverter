"""Background thread running a queue of conversions."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from omniconverter.core.converter import Converter, SourceFile
from omniconverter.core.errors import Cancelled, ConversionError
from omniconverter.core.formats import Format


@dataclass
class Job:
    source: SourceFile
    target: Format
    options: dict[str, Any] = field(default_factory=dict)
    output: Path | None = None  # explicit file; otherwise computed right before converting
    output_dir: Path | None = None  # folder for computed names (None = next to the source)


class ConversionWorker(QThread):
    job_started = Signal(int)
    progress = Signal(int, float)  # job index, fraction in [0, 1] or -1 for "unknown"
    job_finished = Signal(int, str)  # job index, output path
    job_failed = Signal(int, str, str)  # job index, message, details

    def __init__(self, converter: Converter, jobs: list[Job]) -> None:
        super().__init__()
        self.converter = converter
        self.jobs = jobs
        self.cancelled = False
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        lenient = len(self.jobs) > 1
        for index, job in enumerate(self.jobs):
            if self._cancel.is_set():
                self.cancelled = True
                return
            self.job_started.emit(index)
            try:
                output = job.output or self.converter.output_path(
                    job.source, job.target, job.options, job.output_dir)
            except ConversionError as exc:
                self.job_failed.emit(index, exc.message, exc.details)
                continue

            def report(fraction: float | None, index: int = index) -> None:
                self.progress.emit(index, -1.0 if fraction is None else fraction)

            try:
                result = self.converter.convert(job.source, job.target, output, job.options,
                                                on_progress=report, cancel=self._cancel,
                                                lenient=lenient)
            except Cancelled:
                self.cancelled = True
                return
            except ConversionError as exc:
                self.job_failed.emit(index, exc.message, exc.details)
            except Exception as exc:  # never let an unexpected bug kill the thread silently
                self.job_failed.emit(index, str(exc) or type(exc).__name__,
                                     traceback.format_exc())
            else:
                self.job_finished.emit(index, str(result))
