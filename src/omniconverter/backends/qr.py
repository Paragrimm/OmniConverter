"""QR codes from typed text/links or from the content of small text files (segno)."""

from __future__ import annotations

import plistlib
import re
from collections.abc import Iterable
from pathlib import Path

from omniconverter.backends.preview import image_frames
from omniconverter.core.backend import (
    Backend,
    Conversion,
    ConversionContext,
    ConversionRequest,
    Preview,
)
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import Format
from omniconverter.core.options import Kind, Option, when
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

SOURCES = ("text", "txt", "md", "url", "vcf")
TARGETS = ("qr-png", "qr-svg")
MAX_FILE_BYTES = 64 * 1024  # far above what fits; only guards against reading huge files

# Byte capacity of the largest QR code (version 40) per error correction level.
CAPACITY = {"l": 2953, "m": 2331, "q": 1663, "h": 1273}


class QRBackend(Backend):
    id = "qr"

    def conversions(self) -> Iterable[Conversion]:
        for src in SOURCES:
            for dst in TARGETS:
                yield Conversion(src, dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        opts = [
            Option("error_correction", t("opt.qr_error_correction"), Kind.CHOICE, "m",
                   choices=tuple((level, t(f"opt.qr_error_correction.{level}"))
                                 for level in CAPACITY),
                   help=t("opt.qr_error_correction_help")),
        ]
        if target.id == "qr-png":
            opts.append(Option("size", t("opt.qr_size"), Kind.INT, 1024, minimum=64,
                               maximum=8192, suffix=" px", help=t("opt.qr_size_help")))
        opts += [
            Option("dark", t("opt.qr_dark"), Kind.COLOR, "#000000"),
            Option("transparent", t("opt.qr_transparent"), Kind.BOOL, False, advanced=True),
            Option("light", t("opt.qr_light"), Kind.COLOR, "#ffffff", advanced=True,
                   visible_if=when("transparent", False)),
            Option("border", t("opt.qr_border"), Kind.INT, 4, minimum=0, maximum=20,
                   advanced=True, help=t("opt.qr_border_help")),
        ]
        return opts

    def output_stem(self, request: ConversionRequest) -> str | None:
        return "qr-code"

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        kind = "svg" if request.target_format.id == "qr-svg" else "png"
        _save(request, output, kind)

    def can_preview(self, source: Format, target: Format) -> bool:
        return True

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        result = ctx.work_dir / f"result.{request.target_format.extension}"
        self.convert(request, result, ctx)
        shown = result
        if request.target_format.id == "qr-svg":  # the same code as PNG, for the preview only
            shown = ctx.work_dir / "shown.png"
            _save(request, shown, "png")
        frames, _durations, (width, height) = image_frames(shown, ctx, animated=False)
        vector = request.target_format.id == "qr-svg"
        return Preview(frames, width=None if vector else width,
                       height=None if vector else height, size_bytes=result.stat().st_size)


def _save(request: ConversionRequest, output: Path, kind: str) -> None:
    import segno

    payload = qr_payload(request)
    opts = request.options
    level = opts.get("error_correction", "m")
    try:
        code = segno.make(payload, error=level, micro=False)
    except segno.DataOverflowError:
        size = len(payload.encode("utf-8"))
        raise ConversionError(t("error.qr_too_large", size=size, limit=CAPACITY[level],
                                max=CAPACITY["l"])) from None
    border = int(opts.get("border", 4))
    light = None if opts.get("transparent") else opts.get("light", "#ffffff")
    width, _height = code.symbol_size(scale=1, border=border)
    scale = max(1, round(int(opts.get("size", 1024)) / width))
    try:
        code.save(str(output), kind=kind, scale=scale, border=border,
                  dark=opts.get("dark", "#000000"), light=light)
    except (OSError, ValueError) as exc:
        raise ConversionError(t("error.qr_failed"), str(exc)) from exc


def qr_payload(request: ConversionRequest) -> str:
    """What goes into the code: typed text, a shortcut's URL, or a text file's content."""
    if request.source is None:
        text = request.text or ""
    else:
        data = _read_small(request.source)
        text = shortcut_url(data) if request.source_format.id == "url" else decode_text(data)
    text = text.strip()
    if not text:
        raise ConversionError(t("error.qr_empty"))
    return text


def _read_small(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ConversionError(t("error.qr_too_large", size=size, limit=CAPACITY["m"],
                                    max=CAPACITY["l"]))
        return path.read_bytes()
    except OSError as exc:
        raise ConversionError(t("error.data_read", problem=exc.strerror or exc), str(exc)
                              ) from exc


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:  # e.g. an old Windows text file
        return data.decode("cp1252", errors="replace")


def shortcut_url(data: bytes) -> str:
    """URL of a Windows ``.url`` (INI) or macOS ``.webloc`` (property list) shortcut."""
    if data.lstrip().startswith((b"<?xml", b"<!DOCTYPE plist", b"<plist", b"bplist")):
        try:
            value = plistlib.loads(data).get("URL", "")
        except (plistlib.InvalidFileException, ValueError, AttributeError) as exc:
            raise ConversionError(t("error.qr_no_url"), str(exc)) from exc
        return str(value)
    match = re.search(r"^\s*URL\s*=\s*(\S.*?)\s*$", decode_text(data),
                      flags=re.MULTILINE | re.IGNORECASE)
    if match is None:
        raise ConversionError(t("error.qr_no_url"))
    return match.group(1)
