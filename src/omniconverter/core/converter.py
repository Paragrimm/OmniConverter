"""High-level API used by the CLI and the GUI."""

from __future__ import annotations

import dataclasses
import os
import re
import secrets
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniconverter.core import options as opts
from omniconverter.core import process
from omniconverter.core.backend import (
    Backend,
    ConversionContext,
    ConversionRequest,
    Preview,
    ProgressCallback,
)
from omniconverter.core.errors import ConversionError, OptionError, UnsupportedConversion
from omniconverter.core.formats import FORMATS, Category, Format, detect_format
from omniconverter.core.probe import MediaInfo, probe
from omniconverter.core.registry import Registry, TargetChoice
from omniconverter.core.tools import ToolLocator
from omniconverter.i18n import t

_MEDIA_CATEGORIES = {Category.VIDEO, Category.AUDIO}
COMBINE = "combine"  # option offered for several files whose target can hold them all


@dataclass(frozen=True)
class SourceFile:
    """A file to convert – or, with ``path=None``, typed text or a generator like noise."""

    path: Path | None
    format: Format
    media: MediaInfo | None = None
    text: str | None = None

    @classmethod
    def from_text(cls, text: str) -> SourceFile:
        return cls(None, FORMATS["text"], text=text)

    @classmethod
    def generator(cls, format_id: str) -> SourceFile:
        fmt = FORMATS[format_id]
        if fmt.category is not Category.GENERATOR:
            raise ValueError(f"{format_id} is not a generator")
        return cls(None, fmt)

    @property
    def name(self) -> str:
        return self.path.name if self.path else self.format.label

    @property
    def size(self) -> int:
        if self.path is None:
            return len((self.text or "").encode("utf-8"))
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

    def resolve_options(self, source: SourceFile, target: Format,
                        raw_options: Mapping[str, Any] | None = None, *,
                        lenient: bool = False) -> dict[str, Any]:
        """Typed option values with defaults filled in (see :meth:`convert` for *lenient*)."""
        schema = self.options(source, target)
        raw = dict(raw_options or {})
        raw.pop(COMBINE, None)  # about several files, not about how each one is converted
        if lenient:
            known = {o.key for o in schema}
            raw = {k: v for k, v in raw.items() if k in known}
        return opts.resolve(schema, raw)

    def output_path(self, source: SourceFile, target: Format,
                    options: Mapping[str, Any] | None = None,
                    directory: Path | None = None) -> Path:
        """Default output: next to the source (or in *directory*), never overwriting anything.

        Sources without a file are named by their backend (e.g. ``noise-42.png``) and saved in
        *directory*, or the current directory. Results that are a folder (the pages of a PDF)
        are named like the source, without an extension.
        """
        if source.path is not None:
            if self.writes_folder(source, target, options):
                return unique_path((directory or source.path.parent) / source.path.stem,
                                   folder=True)
            return default_output_path(source.path, target, directory)
        backend = self._backend_for(source, target)
        request = self._lenient_request(source, target, options)
        stem = backend.output_stem(request) or source.format.id
        return unique_path((directory or Path.cwd()) / f"{stem}.{target.extension}")

    def writes_folder(self, source: SourceFile, target: Format,
                      options: Mapping[str, Any] | None = None) -> bool:
        """Whether the result is a folder of files (e.g. one image per page)."""
        try:
            backend = self._backend_for(source, target)
            return backend.writes_folder(self._lenient_request(source, target, options))
        except ConversionError:  # unsupported, a tool is missing, an unreadable file
            return False

    def _lenient_request(self, source: SourceFile, target: Format,
                         options: Mapping[str, Any] | None) -> ConversionRequest:
        try:
            values = self.resolve_options(source, target, options, lenient=True)
        except OptionError:  # e.g. a half-typed value in the GUI
            values = self.resolve_options(source, target)
        return ConversionRequest(source.path, source.format, target, values, source.media,
                                 source.text)

    # -- several files into one -------------------------------------------------------------

    def combiner(self, sources: Sequence[SourceFile], target: Format) -> Backend | None:
        """The backend that can join *sources* into one *target* file, if any."""
        if len(sources) < 2 or any(s.path is None for s in sources):
            return None
        formats = [s.format for s in sources]
        return next((b for b in self.registry.backends if b.can_combine(formats, target)), None)

    def options_for(self, sources: Sequence[SourceFile], target: Format) -> list[opts.Option]:
        """Options for converting *sources* to *target* – with "join into one file" if possible.

        The per-file options stay for the "off" state; the joined result's own options appear
        when it is on. Options both share are always shown.
        """
        per_file = self.options(sources[0], target)
        backend = self.combiner(sources, target)
        if backend is None:
            return per_file
        joined = backend.combine_options([s.format for s in sources], target)
        joined_keys = {o.key for o in joined}
        per_file_keys = {o.key for o in per_file}
        result = [opts.Option(COMBINE, t("opt.combine"), opts.Kind.BOOL, True,
                              help=t("opt.combine_help"))]
        result += [o if o.key in joined_keys else _only_if(o, False) for o in per_file]
        result += [_only_if(o, True) for o in joined if o.key not in per_file_keys]
        return result

    def wants_combine(self, sources: Sequence[SourceFile], target: Format,
                      raw_options: Mapping[str, Any] | None = None) -> bool:
        if self.combiner(sources, target) is None:
            return False
        raw = (raw_options or {}).get(COMBINE, True)
        return opts.parse_bool(raw, COMBINE)

    def combined_output_path(self, sources: Sequence[SourceFile], target: Format,
                             directory: Path | None = None) -> Path:
        """Next to the first file (in name order), named after what the names share."""
        ordered = combine_order(sources)
        first = ordered[0].path
        assert first is not None
        stem = shared_stem([s.path.stem for s in ordered if s.path]) or first.stem
        return unique_path((directory or first.parent) / f"{stem}.{target.extension}")

    def _combine_requests(self, sources: Sequence[SourceFile], target: Format,
                          raw_options: Mapping[str, Any] | None
                          ) -> tuple[Backend, list[ConversionRequest]]:
        backend = self.combiner(sources, target)
        if backend is None:
            raise UnsupportedConversion(f"{len(sources)} × → {target.label}")
        schema = backend.combine_options([s.format for s in sources], target)
        known = {o.key for o in schema}
        values = opts.resolve(schema, {k: v for k, v in (raw_options or {}).items()
                                       if k in known})
        requests = [ConversionRequest(s.path, s.format, target, values, s.media)
                    for s in combine_order(sources)]
        return backend, requests

    def combine(self, sources: Sequence[SourceFile], target: Format, output: str | Path,
                raw_options: Mapping[str, Any] | None = None, *,
                on_progress: ProgressCallback | None = None,
                cancel: threading.Event | None = None) -> Path:
        """Join *sources* (in name order) into the single file *output* (atomically)."""
        backend, requests = self._combine_requests(sources, target, raw_options)
        out = Path(output).expanduser().resolve()
        if any(r.source == out for r in requests):
            raise ConversionError(t("error.same_file"))
        return self._write(out, lambda tmp, ctx: backend.combine(requests, tmp, ctx),
                           on_progress=on_progress, cancel=cancel)

    def preview_combined(self, sources: Sequence[SourceFile], target: Format,
                         raw_options: Mapping[str, Any] | None, work_dir: Path, *,
                         cancel: threading.Event | None = None) -> Preview:
        backend, requests = self._combine_requests(sources, target, raw_options)
        return backend.preview_combined(
            requests, ConversionContext(self.locator, Path(work_dir), cancel))

    def _backend_for(self, source: SourceFile, target: Format) -> Backend:
        backend, _conv = self.registry.resolve(source.format, target, source.media)
        return backend

    # -- preview ----------------------------------------------------------------------------

    def can_preview(self, source: SourceFile, target: Format) -> bool:
        try:
            backend = self._backend_for(source, target)
        except ConversionError:  # unsupported, or a tool is missing
            return False
        return backend.can_preview(source.format, target)

    def preview(self, source: SourceFile, target: Format, raw_options: Mapping[str, Any] | None,
                work_dir: Path, *, cancel: threading.Event | None = None) -> Preview:
        """Render a quick look at the result into *work_dir* (the caller removes it)."""
        backend = self._backend_for(source, target)
        values = self.resolve_options(source, target, raw_options)
        request = ConversionRequest(source.path, source.format, target, values, source.media,
                                    source.text)
        return backend.preview(request, ConversionContext(self.locator, Path(work_dir), cancel))

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
        values = self.resolve_options(source, target, raw_options, lenient=lenient)
        request = ConversionRequest(source.path, source.format, target, values, source.media,
                                    source.text)

        out = Path(output).expanduser().resolve()
        if source.path is not None and out == source.path:
            raise ConversionError(t("error.same_file"))
        return self._write(out, lambda tmp, ctx: backend.convert(request, tmp, ctx),
                           folder=backend.writes_folder(request), on_progress=on_progress,
                           cancel=cancel)

    def _write(self, out: Path, produce: Callable[[Path, ConversionContext], None], *,
               folder: bool = False, on_progress: ProgressCallback | None = None,
               cancel: threading.Event | None = None) -> Path:
        """Let *produce* write a temporary file (or folder) and move it to *out* at the end."""
        out.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(4)
        tmp = (out.with_name(f".{out.name}.omni-{token}") if folder
               else out.with_name(f".{out.stem}.omni-{token}{out.suffix}"))
        try:
            if folder:
                tmp.mkdir()
            # Cleanup errors (e.g. a file still locked on Windows) must not fail a finished job.
            with tempfile.TemporaryDirectory(prefix="omniconverter-",
                                             ignore_cleanup_errors=True) as work:
                ctx = ConversionContext(self.locator, Path(work), cancel, on_progress, out)
                ctx.progress(0.0)
                produce(tmp, ctx)
                ctx.check_cancelled()
                done = any(tmp.iterdir()) if folder else tmp.is_file()
                if not done:
                    raise ConversionError(t("error.no_output"))
                if folder and out.exists():  # a folder would be moved *into* it
                    raise ConversionError(t("error.folder_exists", path=str(out)))
                companions = _write_companions(out.parent, ctx.companions)
                try:
                    os.replace(tmp, out)
                except BaseException:
                    for path in companions:
                        process.remove_quietly(path)
                    raise
                ctx.progress(1.0)
        except PermissionError as exc:
            path = exc.filename or str(out.parent)
            raise ConversionError(t("error.permission", path=path), str(exc)) from exc
        finally:  # must never mask the original error
            if folder:
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                process.remove_quietly(tmp)
        return out


def _write_companions(folder: Path, files: Mapping[str, bytes]) -> list[Path]:
    """Save a result's extra files atomically; refuses to overwrite existing files."""
    paths = []
    for name in files:
        if not name or Path(name).name != name or name.startswith("."):
            raise ConversionError(f"invalid file name {name!r}")
        path = folder / name
        if path.exists():
            raise ConversionError(t("error.companion_exists", name=name))
        paths.append(path)
    written: list[Path] = []
    try:
        for path, data in zip(paths, files.values(), strict=True):
            tmp = path.with_name(f".{path.stem}.omni-{secrets.token_hex(4)}{path.suffix}")
            try:
                tmp.write_bytes(data)
                os.replace(tmp, path)
            finally:
                process.remove_quietly(tmp)
            written.append(path)
    except BaseException:
        for path in written:
            process.remove_quietly(path)
        raise
    return written


def default_output_path(source: Path, target: Format, directory: Path | None = None) -> Path:
    """Same folder (or *directory*), same name, new extension – never overwriting anything.

    Derived targets add a suffix, e.g. ``wall.jpg`` → ``wall_normal.png``.
    """
    folder = directory or source.parent
    return unique_path(folder / f"{source.stem}{target.name_suffix}.{target.extension}")


def unique_path(path: Path, *, folder: bool = False) -> Path:
    """*path*, or ``name (1).ext`` … if it is taken. A *folder* name has no extension."""
    if not path.exists():
        return path
    stem, suffix = (path.name, "") if folder else (path.stem, path.suffix)
    for n in range(1, 10_000):
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"no free file name for {path}")


def _only_if(option: opts.Option, combine: bool) -> opts.Option:
    return dataclasses.replace(option, visible_if=(*option.visible_if, (COMBINE, (combine,))))


def natural_key(name: str) -> list[Any]:
    """Sort key that puts ``scan 2`` before ``scan 10``."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
            for part in re.split(r"(\d+)", name) if part]


def combine_order(sources: Sequence[SourceFile]) -> list[SourceFile]:
    """The order in which files are joined: by file name, numbers counted as numbers."""
    return sorted(sources, key=lambda s: natural_key(s.path.name if s.path else s.name))


def shared_stem(stems: Sequence[str]) -> str:
    """What all names begin with, without trailing numbers and separators (``scan_``…)."""
    prefix = os.path.commonprefix(list(stems))
    prefix = re.sub(r"[\s\d_\-.(#]+$", "", prefix)
    return prefix if len(prefix) >= 2 else ""
