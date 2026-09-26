"""Seed-based noise maps (Perlin, fractal clouds, ridges, cells, white noise) with numpy."""

from __future__ import annotations

import math
import secrets
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from omniconverter.backends.preview import image_frames, save_image
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

TARGETS = ("png", "jpg", "webp", "bmp", "tiff")
KINDS = ("fbm", "perlin", "ridged", "worley", "white")
MAX_SEED = 2**31 - 1
_PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF"}
_STRIP_PIXELS = 1 << 20  # rows are computed in strips of about a megapixel
_PREVIEW = 256  # samples per axis used to find the value range
PREVIEW_SIDE = 1024  # larger maps are previewed scaled down


class NoiseBackend(Backend):
    id = "noise"

    def conversions(self) -> Iterable[Conversion]:
        for dst in TARGETS:
            yield Conversion("noise", dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        not_white = when("kind", *[k for k in KINDS if k != "white"])
        fractal = when("kind", "fbm", "ridged")
        return [
            Option("kind", t("opt.noise_kind"), Kind.CHOICE, "fbm",
                   choices=tuple((k, t(f"opt.noise_kind.{k}")) for k in KINDS)),
            Option("seed", t("opt.seed"), Kind.INT, secrets.randbelow(1_000_000), minimum=0,
                   maximum=MAX_SEED, randomize=True, help=t("opt.seed_help")),
            Option("width", t("opt.width"), Kind.INT, 1024, minimum=16, maximum=8192,
                   suffix=" px"),
            Option("height", t("opt.height"), Kind.INT, 1024, minimum=16, maximum=8192,
                   suffix=" px"),
            Option("scale", t("opt.noise_scale"), Kind.INT, 256, minimum=2, maximum=8192,
                   suffix=" px", visible_if=not_white, help=t("opt.noise_scale_help")),
            Option("octaves", t("opt.noise_octaves"), Kind.INT, 6, minimum=1, maximum=10,
                   visible_if=fractal, help=t("opt.noise_octaves_help")),
            Option("roughness", t("opt.noise_roughness"), Kind.INT, 50, minimum=10,
                   maximum=90, suffix=" %", visible_if=fractal),
            Option("seamless", t("opt.seamless"), Kind.BOOL, True, visible_if=not_white,
                   help=t("opt.seamless_help")),
            Option("color_low", t("opt.noise_color_low"), Kind.COLOR, "#000000",
                   advanced=True),
            Option("color_high", t("opt.noise_color_high"), Kind.COLOR, "#ffffff",
                   advanced=True),
        ]

    def output_stem(self, request: ConversionRequest) -> str | None:
        return f"noise-{request.options.get('seed', 0)}"

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        from PIL import Image

        opts = request.options
        values = render(opts, ctx.progress, ctx.check_cancelled)
        image = colorize(values, opts.get("color_low", "#000000"),
                         opts.get("color_high", "#ffffff"))
        target = request.target_format.id
        save: dict[str, Any] = {}
        if target == "jpg":
            save.update(quality=95, optimize=True)
        elif target == "webp":
            save["quality"] = 90
        elif target == "tiff":
            save["compression"] = "tiff_lzw"
        try:
            Image.fromarray(image).save(output, format=_PIL_FORMAT[target], **save)
        except (OSError, ValueError) as exc:
            raise ConversionError(t("error.image_failed"), str(exc)) from exc

    def can_preview(self, source: Format, target: Format) -> bool:
        return True

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        from PIL import Image

        opts = request.options
        width, height = int(opts.get("width", 1024)), int(opts.get("height", 1024))
        factor = PREVIEW_SIDE / max(width, height)
        if factor >= 1:  # small enough to render exactly, with the real file size
            result = ctx.work_dir / f"result.{request.target_format.extension}"
            self.convert(request, result, ctx)
            frames, _durations, _size = image_frames(result, ctx, animated=False)
            return Preview(frames, width=width, height=height,
                           size_bytes=result.stat().st_size)
        # Everything scaled alike keeps the number of cells, so the pattern stays the same.
        small = {**opts, "width": max(1, round(width * factor)),
                 "height": max(1, round(height * factor)),
                 "scale": max(2, round(int(opts.get("scale", 256)) * factor))}
        values = render(small, None, ctx.check_cancelled)
        image = colorize(values, opts.get("color_low", "#000000"),
                         opts.get("color_high", "#ffffff"))
        frame = save_image(Image.fromarray(image), ctx.work_dir / "frame-0000.png")
        return Preview([frame], width=width, height=height, note=t("preview.scaled"))


# -- generation ----------------------------------------------------------------------------


def render(opts: dict[str, Any], progress: Callable[[float | None], None] | None = None,
           check_cancelled: Callable[[], None] | None = None) -> Any:
    """The noise as uint8 array (height × width). Same options and seed → same pixels."""
    import numpy as np

    width, height = int(opts.get("width", 1024)), int(opts.get("height", 1024))
    kind = opts.get("kind", "fbm")
    rng = np.random.default_rng(int(opts.get("seed", 0)))
    result = np.empty((height, width), dtype=np.uint8)
    rows = max(1, _STRIP_PIXELS // width)

    if kind == "white":
        for y0 in range(0, height, rows):
            if check_cancelled:
                check_cancelled()
            y1 = min(height, y0 + rows)
            result[y0:y1] = (rng.random((y1 - y0, width)) * 256).astype(np.uint8)
            if progress:
                progress(y1 / height)
        return result

    field = _field(kind, opts, width, height, rng)
    # The noise is a continuous function of the position, so a coarse grid gives its range.
    xs = np.linspace(0, width - 1, min(width, _PREVIEW))
    ys = np.linspace(0, height - 1, min(height, _PREVIEW))
    sample = field(*np.meshgrid(xs, ys))
    low, high = float(sample.min()), float(sample.max())
    span = high - low or 1.0
    xs = np.arange(width, dtype=np.float64)
    for y0 in range(0, height, rows):
        if check_cancelled:
            check_cancelled()
        y1 = min(height, y0 + rows)
        px, py = np.meshgrid(xs, np.arange(y0, y1, dtype=np.float64))
        values = (field(px, py) - low) / span
        result[y0:y1] = np.clip(np.rint(values * 255), 0, 255).astype(np.uint8)
        if progress:
            progress(y1 / height)
    return result


def _field(kind: str, opts: dict[str, Any], width: int, height: int, rng: Any
           ) -> Callable[[Any, Any], Any]:
    """Returns ``f(px, py)`` evaluating the noise at pixel coordinates."""
    scale = max(2, int(opts.get("scale", 256)))
    seamless = bool(opts.get("seamless", True))
    cells_x, cells_y = width / scale, height / scale
    if seamless:  # a whole number of cells per axis makes the pattern repeat at the edges
        cells_x, cells_y = max(1, round(cells_x)), max(1, round(cells_y))

    if kind == "worley":
        worley = _Worley(cells_x, cells_y, seamless, rng)
        return lambda px, py: worley(*_uv(px, py, width, height, cells_x, cells_y))

    octaves = int(opts.get("octaves", 6)) if kind in ("fbm", "ridged") else 1
    persistence = int(opts.get("roughness", 50)) / 100
    layers = [
        (persistence ** o, 2 ** o, _Perlin(cells_x * 2 ** o, cells_y * 2 ** o, seamless, rng))
        for o in range(octaves)
    ]

    def field(px: Any, py: Any) -> Any:
        total = 0.0
        for amplitude, freq, perlin in layers:
            u, v = _uv(px, py, width, height, cells_x * freq, cells_y * freq)
            value = perlin(u, v)
            if kind == "ridged":
                value = (1.0 - abs(value) * math.sqrt(2)) ** 2
            total = total + amplitude * value
        return total

    return field


def _uv(px: Any, py: Any, width: int, height: int, cells_x: float, cells_y: float
        ) -> tuple[Any, Any]:
    return (px + 0.5) * (cells_x / width), (py + 0.5) * (cells_y / height)


class _Perlin:
    """Classic 2D gradient noise on a lattice; periodic when *wrap* is set."""

    def __init__(self, cells_x: float, cells_y: float, wrap: bool, rng: Any) -> None:
        import numpy as np

        self.gx = int(cells_x) if wrap else math.ceil(cells_x) + 1
        self.gy = int(cells_y) if wrap else math.ceil(cells_y) + 1
        angles = rng.random((self.gy, self.gx)) * (2 * math.pi)
        self.grad_x, self.grad_y = np.cos(angles), np.sin(angles)

    def __call__(self, u: Any, v: Any) -> Any:
        import numpy as np

        i0, j0 = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
        fu, fv = u - i0, v - j0
        i0, j0 = i0 % self.gx, j0 % self.gy
        i1, j1 = (i0 + 1) % self.gx, (j0 + 1) % self.gy

        def dot(i: Any, j: Any, dx: Any, dy: Any) -> Any:
            return self.grad_x[j, i] * dx + self.grad_y[j, i] * dy

        n00 = dot(i0, j0, fu, fv)
        n10 = dot(i1, j0, fu - 1, fv)
        n01 = dot(i0, j1, fu, fv - 1)
        n11 = dot(i1, j1, fu - 1, fv - 1)
        su, sv = _fade(fu), _fade(fv)
        top = n00 + su * (n10 - n00)
        bottom = n01 + su * (n11 - n01)
        return top + sv * (bottom - top)


class _Worley:
    """Cellular noise: distance to the nearest of one random point per cell."""

    def __init__(self, cells_x: float, cells_y: float, wrap: bool, rng: Any) -> None:
        self.gx = int(cells_x) if wrap else math.ceil(cells_x) + 2
        self.gy = int(cells_y) if wrap else math.ceil(cells_y) + 2
        self.points = rng.random((self.gy, self.gx, 2))

    def __call__(self, u: Any, v: Any) -> Any:
        import numpy as np

        ci, cj = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
        nearest = np.full(u.shape, np.inf)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                i, j = ci + di, cj + dj
                point = self.points[j % self.gy, i % self.gx]
                dx, dy = i + point[..., 0] - u, j + point[..., 1] - v
                nearest = np.minimum(nearest, dx * dx + dy * dy)
        return np.sqrt(nearest)


def _fade(t_: Any) -> Any:
    return t_ * t_ * t_ * (t_ * (t_ * 6 - 15) + 10)


def colorize(values: Any, low: str, high: str) -> Any:
    """Grayscale stays single-channel; other colors become an RGB gradient."""
    import numpy as np

    if (low.lower(), high.lower()) == ("#000000", "#ffffff"):
        return values
    lo = np.array([int(low[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
    hi = np.array([int(high[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
    f = values.astype(np.float32)[..., None] / 255
    return np.rint(lo + (hi - lo) * f).astype(np.uint8)
