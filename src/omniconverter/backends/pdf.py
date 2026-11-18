"""PDF pages as images, choosing and splitting pages, joining PDFs and images (PDFium)."""

from __future__ import annotations

import contextlib
import io
import re
import threading
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from omniconverter.backends.image import SOURCES as IMAGE_SOURCES
from omniconverter.backends.image import ImageBackend
from omniconverter.backends.preview import image_frames, save_image
from omniconverter.core import options as opts
from omniconverter.core.backend import (
    Backend,
    Conversion,
    ConversionContext,
    ConversionRequest,
    Preview,
)
from omniconverter.core.errors import ConversionError, OptionError
from omniconverter.core.formats import FORMATS, Format
from omniconverter.core.options import Kind, Option
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

IMAGE_TARGETS = ("png", "jpg", "webp")
DPI_CHOICES = (72, 150, 300, 600)
_QUALITY_DEFAULT = {"jpg": 90, "webp": 85}
_PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}
MAX_SIDE = 20_000  # pixels; a poster at 600 dpi would otherwise need gigabytes
PREVIEW_DPI = 100  # PDF targets show their first page at this resolution

# PDFium is not thread-safe, and the preview renders while the window lives on.
_LOCK = threading.Lock()
_PAGE_COUNTS: dict[tuple[str, int, int], int] = {}


class PdfBackend(Backend):
    id = "pdfium"

    def conversions(self) -> Iterable[Conversion]:
        for dst in (*IMAGE_TARGETS, "pdf"):
            yield Conversion("pdf", dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        result = [Option("pages", t("opt.pages"), Kind.TEXT, "", help=t("opt.pages_help"))]
        if target.id == "pdf":
            result.append(Option("split", t("opt.split"), Kind.BOOL, False,
                                 help=t("opt.split_help")))
            return result
        result.append(Option("dpi", t("opt.dpi"), Kind.CHOICE, 150,
                             choices=tuple((d, t(f"opt.dpi.{d}")) for d in DPI_CHOICES),
                             help=t("opt.dpi_help")))
        if target.id in _QUALITY_DEFAULT:
            result.append(Option("quality", t("opt.quality"), Kind.INT,
                                 _QUALITY_DEFAULT[target.id], minimum=1, maximum=100,
                                 suffix=" %"))
        return result

    def writes_folder(self, request: ConversionRequest) -> bool:
        if request.target_format.id == "pdf" and not request.options.get("split"):
            return False
        return len(_pages(request, page_count(request.source))) > 1

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        assert request.source is not None
        target = request.target_format.id
        with _open(request.source) as pdf:
            pages = _pages(request, len(pdf))
            folder = output.is_dir()
            digits = len(str(len(pdf)))
            stem = request.source.stem
            for done, index in enumerate(pages):
                ctx.check_cancelled()
                ctx.progress(done / len(pages))
                path = output / f"{stem}-{index + 1:0{digits}d}.{target}" if folder else output
                if target == "pdf":
                    _save_pdf(pdf, [index] if folder else pages, path)
                    if not folder:
                        break
                else:
                    _save_image(_render(pdf, index, request.options), target,
                                request.options, path)

    def can_preview(self, source: Format, target: Format) -> bool:
        return True

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        assert request.source is not None
        target = request.target_format.id
        with _open(request.source) as pdf:
            pages = _pages(request, len(pdf))
            if target == "pdf":
                im = _render(pdf, pages[0], {"dpi": PREVIEW_DPI})
                size = None
                if not request.options.get("split"):
                    result = ctx.work_dir / "result.pdf"
                    _save_pdf(pdf, pages, result)
                    size = result.stat().st_size
            else:
                im = _render(pdf, pages[0], request.options)
        ctx.check_cancelled()
        if target == "pdf":
            frame = save_image(im, ctx.work_dir / "frame-0000.png")
            key = "preview.files" if request.options.get("split") else "preview.pages"
            note = t(key, n=len(pages)) if len(pages) > 1 else ""
            return Preview([frame], size_bytes=size, note=note)
        result = ctx.work_dir / f"result.{target}"
        _save_image(im, target, request.options, result)
        frames, _durations, (width, height) = image_frames(result, ctx, animated=False)
        note = t("preview.first_of", n=len(pages)) if len(pages) > 1 else ""
        return Preview(frames, width=width, height=height, size_bytes=result.stat().st_size,
                       note=note)

    # -- PDFs and images into one PDF ---------------------------------------------------------

    def can_combine(self, sources: Sequence[Format], target: Format) -> bool:
        ids = {f.id for f in sources}
        return target.id == "pdf" and "pdf" in ids and ids <= {"pdf", *IMAGE_SOURCES}

    def combine(self, requests: Sequence[ConversionRequest], output: Path,
                ctx: ConversionContext) -> None:
        with _joined(requests, ctx) as pdf, _LOCK:
            _write(pdf, output)

    def preview_combined(self, requests: Sequence[ConversionRequest],
                         ctx: ConversionContext) -> Preview:
        result = ctx.work_dir / "result.pdf"
        with _joined(requests, ctx) as pdf, _LOCK:
            _write(pdf, result)
            count = len(pdf)
            im = _render_page(pdf, 0, PREVIEW_DPI)
        frame = save_image(im, ctx.work_dir / "frame-0000.png")
        return Preview([frame], size_bytes=result.stat().st_size,
                       note=t("preview.pages", n=count))


# --------------------------------------------------------------------------------------------


def parse_pages(text: str, count: int) -> list[int]:
    """``1-3, 5, 8-`` → zero-based page indices in that order; empty means all pages."""
    text = text.strip()
    if not text:
        return list(range(count))
    result: list[int] = []
    for part in re.split(r"[,;]", text):
        part = part.strip().replace("–", "-").replace(" ", "")
        if not part:
            continue
        match = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if match is None or part == "-":
            raise OptionError("pages", t("error.pages_invalid", text=part))
        if match.group(3):
            first = last = int(match.group(3))
        else:
            first = int(match.group(1) or 1)
            last = int(match.group(2) or count)
        if not 1 <= first <= last <= count:
            raise OptionError("pages", t("error.pages_range", text=part, n=count))
        result.extend(range(first - 1, last))
    if not result:
        raise OptionError("pages", t("error.pages_invalid", text=text))
    return result


def _pages(request: ConversionRequest, count: int) -> list[int]:
    try:
        return parse_pages(str(request.options.get("pages") or ""), count)
    except OptionError as exc:  # the message alone reads better than "pages: …"
        raise ConversionError(exc.message.removeprefix("pages: ")) from None


def page_count(path: Path | None) -> int:
    """Number of pages, remembered per file version.

    The GUI asks on every change of the options (is the result a folder?) and must not wait
    for the PDFium lock while a preview renders a big page.
    """
    assert path is not None
    try:
        stat = path.stat()
    except OSError as exc:
        raise ConversionError(t("error.pdf_failed"), str(exc)) from exc
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _PAGE_COUNTS:
        with _open(path) as pdf:
            _PAGE_COUNTS[key] = len(pdf)
    return _PAGE_COUNTS[key]


@contextlib.contextmanager
def _open(path: Path | None) -> Iterator[Any]:
    """The PDF, while holding the PDFium lock."""
    import pypdfium2 as pdfium

    with _LOCK:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError as exc:
            raise ConversionError(t("error.pdf_failed"), str(exc)) from exc
        try:
            if len(pdf) == 0:
                raise ConversionError(t("error.pdf_failed"))
            yield pdf
        finally:
            pdf.close()


def _render(pdf: Any, index: int, options: dict[str, Any]) -> Any:
    return _render_page(pdf, index, int(options.get("dpi", 150)))


def _render_page(pdf: Any, index: int, dpi: int) -> Any:
    """One page as a white-backed RGB Pillow image."""
    import pypdfium2 as pdfium

    page = pdf[index]
    try:
        width, height = page.get_size()  # in points (1/72 inch)
        scale = min(dpi / 72, MAX_SIDE / max(width, height, 1))
        return page.render(scale=scale, may_draw_forms=False).to_pil().convert("RGB")
    except pdfium.PdfiumError as exc:
        raise ConversionError(t("error.pdf_failed"), str(exc)) from exc
    finally:
        page.close()


def _save_image(im: Any, target: str, options: dict[str, Any], path: Path) -> None:
    save: dict[str, Any] = {}
    if target in _QUALITY_DEFAULT:
        save["quality"] = int(options.get("quality", _QUALITY_DEFAULT[target]))
    if target == "jpg":
        save.update(optimize=True, progressive=True)
    dpi = int(options.get("dpi", 150))
    if target in ("png", "jpg"):
        save["dpi"] = (dpi, dpi)
    try:
        im.save(path, format=_PIL_FORMAT[target], **save)
    except (OSError, ValueError) as exc:
        raise ConversionError(t("error.image_failed"), str(exc)) from exc


def _save_pdf(pdf: Any, pages: list[int], path: Path) -> None:
    import pypdfium2 as pdfium

    new = pdfium.PdfDocument.new()
    try:
        new.import_pages(pdf, pages)
        _write(new, path)
    finally:
        new.close()


def _write(pdf: Any, path: Path) -> None:
    import pypdfium2 as pdfium

    try:
        with path.open("wb") as fh:
            pdf.save(fh)
    except pdfium.PdfiumError as exc:
        raise ConversionError(t("error.pdf_failed"), str(exc)) from exc


@contextlib.contextmanager
def _joined(requests: Sequence[ConversionRequest], ctx: ConversionContext) -> Iterator[Any]:
    """A new PDF with all pages of the PDFs and one page per image, in order."""
    import pypdfium2 as pdfium

    images = ImageBackend()
    pdf_format = FORMATS["pdf"]
    with _LOCK:
        joined = pdfium.PdfDocument.new()
    try:
        for index, request in enumerate(requests):
            ctx.check_cancelled()
            ctx.progress(index / len(requests) * 0.9)
            if request.source_format.id == "pdf":
                with _open(request.source) as part:
                    joined.import_pages(part)
                continue
            # An image becomes a one-page PDF (Pillow) whose page is then copied over.
            schema = images.options(request.source_format, pdf_format)
            page = ConversionRequest(request.source, request.source_format, pdf_format,
                                     opts.resolve(schema))
            buffer = ctx.work_dir / f"image-{index}.pdf"
            images.convert(page, buffer, ctx)
            data = io.BytesIO(buffer.read_bytes())
            with _LOCK:
                part = pdfium.PdfDocument(data)
                try:
                    joined.import_pages(part)
                finally:
                    part.close()
        yield joined
    finally:
        with _LOCK:
            joined.close()
