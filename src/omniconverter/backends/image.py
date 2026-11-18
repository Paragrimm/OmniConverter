"""Image conversion with Pillow (+ pillow-heif for HEIC)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from omniconverter.backends.preview import image_frames, original_image, save_image
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

SOURCES = ("png", "jpg", "webp", "avif", "heic", "bmp", "tiff", "gif", "ico", "tga")
TARGETS = ("png", "jpg", "webp", "avif", "heic", "bmp", "tiff", "gif", "ico", "pdf")

_PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "avif": "AVIF", "heic": "HEIF", "bmp": "BMP",
    "tiff": "TIFF", "gif": "GIF", "ico": "ICO", "pdf": "PDF",
}
_QUALITY_DEFAULT = {"jpg": 90, "webp": 85, "avif": 70, "heic": 80}
_NO_ALPHA = {"jpg", "bmp", "pdf"}
_ANIMATED = {"gif", "webp", "png"}
_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
PALETTE_SIZES = (256, 128, 64, 32, 16, 8, 4, 2)  # "colors" for PNG; "all" keeps true color
_OPTIMIZE_PIXELS = 4_000_000  # smallest PNG encoding is slow for huge images
COMBINE_TARGETS = ("gif", "pdf")  # several images → one animation / one document

_heif_registered = False


def register_heif() -> None:
    global _heif_registered
    if not _heif_registered:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:  # HEIC stays unavailable, everything else works
            pass
        _heif_registered = True


class ImageBackend(Backend):
    id = "pillow"

    def conversions(self) -> Iterable[Conversion]:
        for src in SOURCES:
            for dst in TARGETS:
                yield Conversion(src, dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        opts = [
            Option("resize", t("opt.resize"), Kind.CHOICE, "original",
                   choices=(("original", t("opt.original")),
                            ("percent", t("opt.resize.percent")),
                            ("fit", t("opt.resize.fit")))),
            Option("percent", t("opt.percent"), Kind.INT, 50, minimum=1, maximum=1000,
                   suffix=" %", visible_if=when("resize", "percent")),
            Option("max_width", t("opt.max_width"), Kind.INT, 1920, minimum=1, maximum=65535,
                   suffix=" px", visible_if=when("resize", "fit")),
            Option("max_height", t("opt.max_height"), Kind.INT, 1080, minimum=1,
                   maximum=65535, suffix=" px", visible_if=when("resize", "fit")),
        ]
        if target.id in ("webp", "avif"):
            opts.append(Option("lossless", t("opt.lossless"), Kind.BOOL, False))
        if target.id in _QUALITY_DEFAULT:
            opts.append(Option(
                "quality", t("opt.quality"), Kind.INT, _QUALITY_DEFAULT[target.id], minimum=1,
                maximum=100, suffix=" %",
                visible_if=when("lossless", False) if target.id in ("webp", "avif") else (),
            ))
        if target.id == "png":
            opts += [
                Option("colors", t("opt.colors"), Kind.CHOICE, "all",
                       choices=(("all", t("opt.colors.all")),
                                *((n, str(n)) for n in PALETTE_SIZES)),
                       help=t("opt.colors_help")),
                Option("dither", t("opt.dither"), Kind.CHOICE, "floyd_steinberg", advanced=True,
                       choices=tuple((d, t(f"opt.dither.{d}"))
                                     for d in ("floyd_steinberg", "none")),
                       visible_if=when("colors", *PALETTE_SIZES), help=t("opt.png_dither_help")),
            ]
        if target.id in _NO_ALPHA:
            opts.append(Option("background", t("opt.background"), Kind.COLOR, "#ffffff",
                               advanced=True))
        if target.id != "ico":
            opts.append(Option("strip_metadata", t("opt.strip_metadata"), Kind.BOOL, True,
                               advanced=True, help=t("opt.strip_metadata_help")))
        return opts

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        frames, save = self._render(request, ctx)
        _save(frames, save, request.target_format.id, output)

    def can_preview(self, source: Format, target: Format) -> bool:
        return True

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        """The real result (exact file size), decoded again to show artifacts and palettes."""
        assert request.source is not None
        target = request.target_format.id
        frames, save = self._render(request, ctx)
        result = ctx.work_dir / f"result.{request.target_format.extension}"
        _save(frames, save, target, result)
        ctx.check_cancelled()
        note = ""
        if target == "pdf":  # Pillow cannot read PDFs: show the pages as they went in
            shown = [save_image(frames[0], ctx.work_dir / "frame-0000.png")]
            durations: list[int] = []
            width, height = frames[0].size
            if len(frames) > 1:
                note = t("preview.pages", n=len(frames))
        else:
            shown, durations, (width, height) = image_frames(result, ctx,
                                                             animated=target in _ANIMATED)
        opts = request.options
        original = original_image(request.source, ctx, lambda im: _resize(im, opts))
        return Preview(shown, durations, original=original, width=width, height=height,
                       size_bytes=result.stat().st_size, note=note)

    # -- several images into one GIF or PDF ----------------------------------------------------

    def can_combine(self, sources: Sequence[Format], target: Format) -> bool:
        return target.id in COMBINE_TARGETS and all(f.id in SOURCES for f in sources)

    def combine_options(self, sources: Sequence[Format], target: Format) -> list[Option]:
        opts = self.options(sources[0], target)
        if target.id == "gif":
            opts += [
                Option("frame_ms", t("opt.frame_ms"), Kind.INT, 500, minimum=20, maximum=60_000,
                       suffix=" ms", help=t("opt.frame_ms_help")),
                Option("loop", t("opt.loop"), Kind.CHOICE, "forever",
                       choices=tuple((v, t(f"opt.loop.{v}")) for v in ("forever", "once"))),
            ]
        return opts

    def combine(self, requests: Sequence[ConversionRequest], output: Path,
                ctx: ConversionContext) -> None:
        frames, save = self._render_many(requests, ctx)
        _save(frames, save, requests[0].target_format.id, output)

    def preview_combined(self, requests: Sequence[ConversionRequest],
                         ctx: ConversionContext) -> Preview:
        target = requests[0].target_format.id
        frames, save = self._render_many(requests, ctx)
        result = ctx.work_dir / f"result.{requests[0].target_format.extension}"
        _save(frames, save, target, result)
        ctx.check_cancelled()
        if target == "pdf":
            shown = [save_image(frames[0], ctx.work_dir / "frame-0000.png")]
            durations: list[int] = []
            width, height = frames[0].size
            note = t("preview.pages", n=len(frames))
        else:
            shown, durations, (width, height) = image_frames(result, ctx)
            note = t("preview.images", n=len(requests))
        return Preview(shown, durations, width=width, height=height,
                       size_bytes=result.stat().st_size, note=note)

    def _render_many(self, requests: Sequence[ConversionRequest], ctx: ConversionContext
                     ) -> tuple[list[Any], dict[str, Any]]:
        """All images (and the frames/pages of animations and TIFFs) one after another."""
        from PIL import Image, ImageSequence, UnidentifiedImageError

        register_heif()
        target = requests[0].target_format.id
        opts = requests[0].options
        still_ms = int(opts.get("frame_ms", 500))
        frames: list[Any] = []
        durations: list[int] = []
        for index, request in enumerate(requests):
            ctx.check_cancelled()
            ctx.progress(index / len(requests) * 0.8)
            try:
                with Image.open(request.source) as im:
                    many = getattr(im, "n_frames", 1) > 1 and (
                        target == "gif" or im.format == "TIFF")
                    for frame in ImageSequence.Iterator(im) if many else [im]:
                        ctx.check_cancelled()
                        frames.append(_prepare(frame.copy(), target, opts))
                        duration = frame.info.get("duration") if many else None
                        durations.append(int(duration or still_ms))
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                name = request.source.name if request.source else ""
                raise ConversionError(f"{t('error.image_failed')} ({name})", str(exc)) from exc
        save: dict[str, Any] = {"save_all": True, "append_images": frames[1:]}
        if target == "gif":
            frames = _same_size(frames)
            save.update(append_images=frames[1:], duration=durations, disposal=2)
            if opts.get("loop", "forever") == "forever":
                save["loop"] = 0  # without the loop extension, a GIF plays once
        else:
            save["resolution"] = 96.0
        return frames, save

    def _render(self, request: ConversionRequest, ctx: ConversionContext
                ) -> tuple[list[Any], dict[str, Any]]:
        """The frames to save and the arguments for Pillow's ``save``."""
        from PIL import Image, ImageSequence, UnidentifiedImageError

        register_heif()
        ctx.progress(None)
        target = request.target_format.id
        opts = request.options
        try:
            with Image.open(request.source) as im:
                info = dict(im.info)
                exif = im.getexif()
                n_frames = getattr(im, "n_frames", 1)
                multi = n_frames > 1 and (
                    target in _ANIMATED or (target in ("pdf", "tiff") and im.format == "TIFF")
                )
                source_frames = ImageSequence.Iterator(im) if multi else [im]
                frames, durations = [], []
                for frame in source_frames:
                    ctx.check_cancelled()
                    frames.append(_prepare(frame.copy(), target, opts))
                    # Only a loaded frame knows its duration (e.g. the first one of a WebP).
                    durations.append(frame.info.get("duration", info.get("duration", 100)))
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ConversionError(t("error.image_failed"), str(exc)) from exc
        colors = opts.get("colors", "all")
        if target == "png" and colors != "all" and len(frames) == 1:
            # Animated PNGs share one palette for all frames, so only still images are reduced.
            frames[0] = reduce_colors(frames[0], int(colors),
                                      opts.get("dither", "floyd_steinberg") != "none")

        save: dict[str, Any] = {}
        if "icc_profile" in info and target not in ("gif", "ico", "bmp"):
            save["icc_profile"] = info["icc_profile"]
        if not opts.get("strip_metadata", True) and target in ("jpg", "png", "webp", "avif",
                                                               "heic", "tiff"):
            exif.pop(0x0112, None)  # orientation was applied to the pixels already
            save["exif"] = exif.tobytes()
        if target in _QUALITY_DEFAULT:
            save["quality"] = int(opts.get("quality", _QUALITY_DEFAULT[target]))
        if opts.get("lossless") and target in ("webp", "avif"):
            save["lossless"] = True
            save.pop("quality", None)
        if target == "jpg":
            save.update(optimize=True, progressive=True)
        elif target == "png":
            width, height = frames[0].size
            save["optimize"] = width * height < _OPTIMIZE_PIXELS
        elif target == "tiff":
            save["compression"] = "tiff_lzw"
        elif target == "ico":
            first = frames[0]
            save["sizes"] = [(s, s) for s in _ICO_SIZES if s <= max(first.size)] or [(16, 16)]
        elif target == "pdf":
            save["resolution"] = float(info.get("dpi", (96, 96))[0] or 96)

        if len(frames) > 1:
            save.update(save_all=True, append_images=frames[1:])
            if target in _ANIMATED:
                save.update(duration=durations, loop=info.get("loop", 0))
                if target == "gif":
                    save["disposal"] = 2
        return frames, save


def _save(frames: list[Any], save: dict[str, Any], target: str, output: Path) -> None:
    try:
        frames[0].save(output, format=_PIL_FORMAT[target], **save)
    except (OSError, ValueError, KeyError) as exc:
        raise ConversionError(t("error.image_failed"), str(exc)) from exc


def _same_size(frames: list[Any]) -> list[Any]:
    """Fit every frame into the first one's size, centered on transparency (GIF frames)."""
    from PIL import Image, ImageOps

    size = frames[0].size
    result = [frames[0]]
    for frame in frames[1:]:
        if frame.size != size:
            fitted = ImageOps.contain(frame.convert("RGBA"), size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
            frame = canvas
        result.append(frame)
    return result


def _prepare(im: Any, target: str, opts: dict[str, Any]) -> Any:
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(im)
    im = _resize(im, opts)
    has_alpha = im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info
    )
    if target in _NO_ALPHA:
        if has_alpha:
            rgba = im.convert("RGBA")
            background = Image.new("RGBA", rgba.size, opts.get("background", "#ffffff"))
            im = Image.alpha_composite(background, rgba)
        return im.convert("RGB") if im.mode != "RGB" else im
    if target == "ico":
        im = im.convert("RGBA")
        side = max(im.size)
        if im.size[0] != im.size[1]:  # icons are square: pad with transparency
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square.paste(im, ((side - im.size[0]) // 2, (side - im.size[1]) // 2))
            im = square
        return im
    if target in ("png", "tiff") and im.mode in ("1", "L", "LA", "RGB", "RGBA", "I;16", "I"):
        return im
    if target == "gif" and im.mode in ("P", "L"):
        return im
    return im.convert("RGBA" if has_alpha else "RGB")


def reduce_colors(im: Any, colors: int, dither: bool) -> Any:
    """A palette image with at most *colors* colors (like pngquant, if a little simpler)."""
    from PIL import Image

    has_alpha = im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info
    )
    if has_alpha:  # Pillow can only dither to a palette without alpha
        return im.convert("RGBA").quantize(colors, method=Image.Quantize.FASTOCTREE)
    rgb = im.convert("RGB")
    palette = rgb.quantize(colors, method=Image.Quantize.MEDIANCUT)
    if not dither:
        return palette
    return rgb.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)


def _resize(im: Any, opts: dict[str, Any]) -> Any:
    from PIL import Image

    mode = opts.get("resize", "original")
    width, height = im.size
    if mode == "percent":
        factor = int(opts.get("percent", 100)) / 100
        size = (max(1, round(width * factor)), max(1, round(height * factor)))
    elif mode == "fit":
        box_w, box_h = int(opts.get("max_width", width)), int(opts.get("max_height", height))
        scale = min(box_w / width, box_h / height, 1.0)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
    else:
        return im
    if size == im.size:
        return im
    if im.mode == "P":
        im = im.convert("RGBA")
    return im.resize(size, Image.Resampling.LANCZOS)
