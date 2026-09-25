"""Running external tools safely: argument lists only, cancellable, with stderr capture."""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from omniconverter.core.errors import Cancelled, ConversionError

_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr_tail: str


def run(
    args: Sequence[str],
    *,
    cancel: threading.Event | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    check: bool = True,
    error_message: str = "",
    tail_lines: int = 200,
) -> RunResult:
    """Run *args* and wait for it.

    Stdout is streamed line by line to *on_stdout_line* (or collected and returned); the last
    *tail_lines* lines of stderr are kept for error reporting. Setting *cancel* terminates the
    process and raises :class:`Cancelled`.
    """
    try:
        proc = subprocess.Popen(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATIONFLAGS,
        )
    except OSError as exc:
        raise ConversionError(error_message or str(exc), str(exc)) from exc

    stdout_lines: list[str] = []
    stderr_tail: deque[str] = deque(maxlen=tail_lines)

    def pump_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if on_stdout_line is not None:
                # A buggy progress callback must not kill the pipe reader.
                with contextlib.suppress(Exception):
                    on_stdout_line(line)
            else:
                stdout_lines.append(line)

    def pump_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip("\r\n"))

    readers = [threading.Thread(target=f, daemon=True) for f in (pump_stdout, pump_stderr)]
    for r in readers:
        r.start()

    started = time.monotonic()
    try:
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _terminate(proc)
                    raise Cancelled() from None
                if timeout is not None and time.monotonic() - started > timeout:
                    _terminate(proc)
                    raise ConversionError(
                        error_message or "timeout", "\n".join(stderr_tail)
                    ) from None
    except KeyboardInterrupt:
        _terminate(proc)
        raise
    finally:
        for r in readers:
            r.join(timeout=2)

    result = RunResult(proc.returncode, "\n".join(stdout_lines), "\n".join(stderr_tail))
    if check and proc.returncode != 0:
        details = f"$ {' '.join(args)}\n\n{result.stderr_tail}".strip()
        raise ConversionError(error_message or f"exit code {proc.returncode}", details)
    return result


def _terminate(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
