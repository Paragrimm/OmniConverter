"""High-level API used by the CLI and the GUI."""

from __future__ import annotations

import os
import secrets
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniconverter.core import options as opts
from omniconverter.core import process
from omniconverter.core.backend import (
    Backend,
    ConversionContext,
    ConversionRequest,
    ProgressCallback,
)
from omniconverter.core.errors import ConversionError, UnsupportedConversion
from omniconverter.core.formats import Category, Format, detect_format
from omniconverter.core.probe import MediaInfo, probe
from omniconverter.core.registry import Registry, TargetChoice
from omniconverter.core.tools import ToolLocator
from omniconverter.i18n import t

_MEDIA_CATEGORIES = {Category.VIDEO, Category.AUDIO}


@dataclass(frozen=True)
class SourceFile:
    path: Path
    format: Format
    media: MediaInfo | None = None

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


class Converter:
    def __init__(
        self, locator: ToolLocator | None = None, backends: Iterable[Backend] | None = None
    ) -> None:
        if backends is None:
            from omniconverter.backends import default_backends

            backends = default_backends()
        self.locator = locator or ToolLocator()
        self.registry = Registry(backends, self.locator)

    # -- inspection -------------------------------------------------------------------------

    def inspect(self, path: str | Path) -> SourceFile:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise ConversionError(t("error.not_a_file", path=str(p)))
        fmt = detect_format(p)
        if fmt is None:
            raise UnsupportedConversion(t("error.unknown_format", name=p.name))
        media = None
        if fmt.category in _MEDIA_CATEGORIES or fmt.id == "gif":
            media = probe(p, self.locator)
        return SourceFile(p, fmt, media)

    def targets(self, sources: Sequence[SourceFile]) -> list[TargetChoice]:
        return self.registry.common_targets([(s.format, s.media) for s in sources])

    def options(self, source: SourceFile, target: Format) -> list[opts.Option]:
        backend = self._backend_for(source, target)
        return backend.options(source.format, target, source.media)

    def _backend_for(self, source: SourceFile, target: Format) -> Backend:
        backend, _conv = self.registry.resolve(source.format, target, source.media)
        return backend

    # -- conversion -------------------------------------------------------------------------

    def convert(
        self,
        source: SourceFile,
        target: Format,
        output: str | Path,
        raw_options: Mapping[str, Any] | None = None,
        *,
        on_progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
        lenient: bool = False,
    ) -> Path:
        """Convert *source* to *target* and write it to *output* (atomically).

        With *lenient*, option keys that the backend does not know are ignored – used when one
        set of options is applied to several files.
        """
        backend = self._backend_for(source, target)
        schema = backend.options(source.format, target, source.media)
        raw = dict(raw_options or {})
        if lenient:
            known = {o.key for o in schema}
            raw = {k: v for k, v in raw.items() if k in known}
        values = opts.resolve(schema, raw)
        request = ConversionRequest(source.path, source.format, target, values, source.media)

        out = Path(output).expanduser().resolve()
        if out == source.path:
            raise ConversionError(t("error.same_file"))
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.stem}.omni-{secrets.token_hex(4)}{out.suffix}")
        try:
            # Cleanup errors (e.g. a file still locked on Windows) must not fail a finished job.
            with tempfile.TemporaryDirectory(prefix="omniconverter-",
                                             ignore_cleanup_errors=True) as work:
                ctx = ConversionContext(self.locator, Path(work), cancel, on_progress)
                ctx.progress(0.0)
                backend.convert(request, tmp, ctx)
                ctx.check_cancelled()
                if not tmp.is_file():
                    raise ConversionError(t("error.no_output"))
                os.replace(tmp, out)
                ctx.progress(1.0)
        except PermissionError as exc:
            path = exc.filename or str(out.parent)
            raise ConversionError(t("error.permission", path=path), str(exc)) from exc
        finally:
            process.remove_quietly(tmp)  # must never mask the original error
        return out


def default_output_path(source: Path, target: Format, directory: Path | None = None) -> Path:
    """Same folder (or *directory*), same name, new extension – never overwriting anything."""
    folder = directory or source.parent
    return unique_path(folder / f"{source.stem}.{target.extension}")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(1, 10_000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"no free file name for {path}")
