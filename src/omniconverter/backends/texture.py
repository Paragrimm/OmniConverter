"""Normal and specular maps computed from an image texture (numpy + Pillow)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from omniconverter.backends.image import SOURCES, register_heif
from omniconverter.backends.preview import image_frames, original_image
from omniconverter.core.backend import (
    Backend,
    Conversion,
    ConversionContext,
    ConversionRequest,
    Preview,
)
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import Format
from omniconverter.core.options import Kind, Option
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

TARGETS = ("normal-map", "specular-map")


class TextureBackend(Backend):
    id = "texture"

    def conversions(self) -> Iterable[Conversion]:
        for src in SOURCES:
            for dst in TARGETS:
                yield Conversion(src, dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        if target.id == "normal-map":
            return [
                Option("strength", t("opt.tex_strength"), Kind.INT, 30, minimum=1,
                       maximum=100, help=t("opt.tex_strength_help")),
                Option("blur", t("opt.tex_blur"), Kind.INT, 1, minimum=0, maximum=20,
                       suffix=" px", help=t("opt.tex_blur_help")),
                Option("invert", t("opt.tex_invert_height"), Kind.BOOL, False,
                       help=t("opt.tex_invert_height_help")),
                Option("convention", t("opt.tex_convention"), Kind.CHOICE, "opengl",
                       choices=(("opengl", t("opt.tex_convention.opengl")),
                                ("directx", t("opt.tex_convention.directx")))),
                Option("seamless", t("opt.seamless"), Kind.BOOL, True, advanced=True,
                       help=t("opt.seamless_help")),
            ]
        return [
            Option("brightness", t("opt.tex_brightness"), Kind.INT, 0, minimum=-100,
                   maximum=100, suffix=" %"),
            Option("contrast", t("opt.tex_contrast"), Kind.INT, 100, minimum=0, maximum=400,
                   suffix=" %"),
            Option("invert", t("opt.tex_invert"), Kind.BOOL, False,
                   help=t("opt.tex_invert_help")),
        ]

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        import numpy as np
        from PIL import Image

        ctx.progress(None)
        assert request.source is not None
        height = load_height(request.source)
        ctx.check_cancelled()
        opts = request.options
        if request.target_format.id == "normal-map":
            pixels = normal_map(height, opts)
            result = Image.fromarray(pixels, "RGB")
        else:
            pixels = specular_map(height, opts)
            result = Image.fromarray(pixels, "L")
        ctx.check_cancelled()
        try:
            result.save(output, format="PNG", optimize=bool(np.prod(pixels.shape) < 4e6))
        except (OSError, ValueError) as exc:
            raise ConversionError(t("error.image_failed"), str(exc)) from exc

    def can_preview(self, source: Format, target: Format) -> bool:
        return True

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        assert request.source is not None
        result = ctx.work_dir / "result.png"
        self.convert(request, result, ctx)
        frames, _durations, (width, height) = image_frames(result, ctx, animated=False)
        return Preview(frames, original=original_image(request.source, ctx), width=width,
                       height=height, size_bytes=result.stat().st_size)


def load_height(path: Path) -> Any:
    """Brightness of the (first frame of the) image as float32 array in ``[0, 1]``."""
    import numpy as np
    from PIL import Image, ImageOps, UnidentifiedImageError

    register_heif()
    try:
        with Image.open(path) as im:
            im.seek(0)
            im = ImageOps.exif_transpose(im)
            if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):  # e.g. 16-bit height maps
                data = np.asarray(im, dtype=np.float32)
                top = 65535.0 if im.mode.startswith("I;16") or data.max() > 255 else 255.0
                return np.clip(data / top, 0.0, 1.0)
            rgba = np.asarray(im.convert("RGBA"), dtype=np.float32) / 255.0
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ConversionError(t("error.image_failed"), str(exc)) from exc
    luminance = rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722
    return luminance * rgba[..., 3]  # transparent areas count as low


def neighbor(a: Any, dy: int, dx: int, wrap: bool) -> Any:
    """``b[y, x] = a[y + dy, x + dx]``, wrapping around or repeating the border."""
    import numpy as np

    if wrap:
        return np.roll(a, (-dy, -dx), axis=(0, 1))
    h, w = a.shape
    padded = np.pad(a, 1, mode="edge")
    return padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]


def gaussian_blur(a: Any, sigma: float, wrap: bool) -> Any:
    import numpy as np

    if sigma <= 0:
        return a
    radius = max(1, math.ceil(sigma * 3))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-(x * x) / (2 * sigma * sigma))
    kernel /= kernel.sum()
    mode = "wrap" if wrap else "edge"
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(a, pad, mode=mode)
        size = a.shape[axis]
        out = np.zeros_like(a)
        for i, weight in enumerate(kernel):
            window = padded[i:i + size, :] if axis == 0 else padded[:, i:i + size]
            out += weight * window
        a = out
    return a


def normal_map(height: Any, opts: dict[str, Any]) -> Any:
    """Tangent-space normal map (RGB uint8) from a height field in ``[0, 1]``."""
    import numpy as np

    wrap = bool(opts.get("seamless", True))
    h = 1.0 - height if opts.get("invert") else height
    h = gaussian_blur(h, float(opts.get("blur", 1)), wrap)

    def n(dy: int, dx: int) -> Any:
        return neighbor(h, dy, dx, wrap)

    # Sobel operator, normalized so that a slope of 1 per pixel gives a gradient of 1.
    dx = ((n(-1, 1) + 2 * n(0, 1) + n(1, 1)) - (n(-1, -1) + 2 * n(0, -1) + n(1, -1))) / 8
    dy = ((n(1, -1) + 2 * n(1, 0) + n(1, 1)) - (n(-1, -1) + 2 * n(-1, 0) + n(-1, 1))) / 8
    strength = int(opts.get("strength", 30)) / 3
    # Image rows grow downwards; in OpenGL tangent space (Y+) green points up, DirectX flips it.
    y_sign = 1.0 if opts.get("convention", "opengl") == "opengl" else -1.0
    nx, ny, nz = -dx * strength, y_sign * dy * strength, np.ones_like(h)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx, ny, nz], axis=-1) / length[..., None]
    return np.clip(np.rint((rgb * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)


def specular_map(height: Any, opts: dict[str, Any]) -> Any:
    """Grayscale specular (or, inverted, roughness) map: brightness levels of the texture."""
    import numpy as np

    g = height
    g = (g - 0.5) * (int(opts.get("contrast", 100)) / 100) + 0.5
    g = g + int(opts.get("brightness", 0)) / 100
    g = np.clip(g, 0.0, 1.0)
    if opts.get("invert"):
        g = 1.0 - g
    return np.rint(g * 255).astype(np.uint8)
