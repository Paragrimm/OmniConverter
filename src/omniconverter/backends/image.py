"""Image conversion with Pillow (+ pillow-heif for HEIC)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from omniconverter.core.backend import Backend, Conversion, ConversionContext, ConversionRequest
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
        if target.id in _NO_ALPHA:
            opts.append(Option("background", t("opt.background"), Kind.COLOR, "#ffffff",
                               advanced=True))
        if target.id != "ico":
            opts.append(Option("strip_metadata", t("opt.strip_metadata"), Kind.BOOL, True,
                               advanced=True, help=t("opt.strip_metadata_help")))
        return opts

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
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
                    durations.append(frame.info.get("duration", info.get("duration", 100)))
                    frames.append(_prepare(frame.copy(), target, opts))
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ConversionError(t("error.image_failed"), str(exc)) from exc

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
        try:
            frames[0].save(output, format=_PIL_FORMAT[target], **save)
        except (OSError, ValueError, KeyError) as exc:
            raise ConversionError(t("error.image_failed"), str(exc)) from exc


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
