"""Helpers for previews: turn results and sources into images the GUI can show (Pillow)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniconverter.core.backend import ConversionContext
from omniconverter.core.errors import ConversionError
from omniconverter.i18n import t

MAX_STILL = 4096  # longest side of a still image in the preview (enough to judge at 100 %)
MAX_ANIMATED = 640  # … and of animation frames, which are all kept in memory
MAX_FRAMES = 300
MIN_DURATION_MS = 20  # browsers treat faster GIF frames as 100 ms; stay sane here too


def save_image(im: Any, path: Path, max_side: int = MAX_STILL) -> Path:
    """Save *im* as a quickly written PNG, scaled down to *max_side* if it is larger."""
    from PIL import Image

    if im.mode not in ("1", "L", "LA", "RGB", "RGBA"):
        im = im.convert("RGBA")
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    im.save(path, format="PNG", compress_level=1)
    return path


def image_frames(path: Path, ctx: ConversionContext, *, animated: bool = True,
                 prefix: str = "frame") -> tuple[list[Path], list[int], tuple[int, int]]:
    """An image file as preview frames: PNG paths, durations (empty for a still) and size."""
    from PIL import Image, ImageSequence, UnidentifiedImageError

    from omniconverter.backends.image import register_heif

    register_heif()
    frames: list[Path] = []
    durations: list[int] = []
    try:
        with Image.open(path) as im:
            size = im.size
            many = animated and getattr(im, "n_frames", 1) > 1
            max_side = MAX_ANIMATED if many else MAX_STILL
            for index, frame in enumerate(ImageSequence.Iterator(im) if many else [im]):
                if index >= MAX_FRAMES:
                    break
                ctx.check_cancelled()
                rgba = frame.convert("RGBA")  # loads the frame, which sets its duration
                durations.append(max(MIN_DURATION_MS, int(frame.info.get("duration") or 100)))
                name = ctx.work_dir / f"{prefix}-{index:04d}.png"
                frames.append(save_image(rgba, name, max_side))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ConversionError(t("error.image_failed"), str(exc)) from exc
    return frames, durations if len(frames) > 1 else [], size


def original_image(source: Path, ctx: ConversionContext,
                   adjust: Callable[[Any], Any] | None = None) -> Path:
    """The source's first frame, upright and optionally *adjust*-ed like the result."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    from omniconverter.backends.image import register_heif

    register_heif()
    try:
        with Image.open(source) as im:
            im.seek(0)
            upright = ImageOps.exif_transpose(im)  # always a loaded copy
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ConversionError(t("error.image_failed"), str(exc)) from exc
    if adjust is not None:
        upright = adjust(upright)
    return save_image(upright, ctx.work_dir / "original.png")
