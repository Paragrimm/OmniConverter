import threading

import numpy as np
import pytest
from PIL import Image

from omniconverter.backends.noise import KINDS, render
from omniconverter.core.converter import SourceFile
from omniconverter.core.errors import Cancelled
from omniconverter.core.formats import get_format

NOISE = SourceFile.generator("noise")


def generate(converter, tmp_path, target="png", **options):
    fmt = get_format(target)
    options = converter.resolve_options(NOISE, fmt, options)
    out = converter.output_path(NOISE, fmt, options, tmp_path)
    return converter.convert(NOISE, fmt, out, options)


def pixels(path):
    with Image.open(path) as im:
        return np.asarray(im).astype(int)


@pytest.mark.parametrize("kind", KINDS)
def test_same_seed_same_image(converter, tmp_path, kind):
    a = generate(converter, tmp_path, kind=kind, seed=42, width=96, height=64, scale=32)
    b = generate(converter, tmp_path, kind=kind, seed=42, width=96, height=64, scale=32)
    c = generate(converter, tmp_path, kind=kind, seed=43, width=96, height=64, scale=32)
    assert a.name == "noise-42.png" and b.name == "noise-42 (1).png"
    assert a.read_bytes() == b.read_bytes()
    assert not np.array_equal(pixels(a), pixels(c))
    image = pixels(a)
    assert image.shape == (64, 96)
    assert image.min() < 60 and image.max() > 195  # uses the full range


@pytest.mark.parametrize("kind", ["fbm", "perlin", "ridged", "worley"])
def test_seamless_edges_match(kind):
    image = render({"kind": kind, "seed": 5, "width": 128, "height": 96, "scale": 32,
                    "seamless": True}).astype(int)
    inner = np.abs(np.diff(image, axis=1)).mean()
    across_edge = np.abs(image[:, 0] - image[:, -1]).mean()
    assert across_edge < inner * 2 + 2
    across_bottom = np.abs(image[0, :] - image[-1, :]).mean()
    assert across_bottom < np.abs(np.diff(image, axis=0)).mean() * 2 + 2


def test_strips_do_not_change_the_result(monkeypatch):
    options = {"kind": "fbm", "seed": 9, "width": 64, "height": 40, "scale": 16}
    whole = render(options)
    monkeypatch.setattr("omniconverter.backends.noise._STRIP_PIXELS", 64 * 3)
    assert np.array_equal(render(options), whole)


def test_colors_and_jpeg(converter, tmp_path):
    out = generate(converter, tmp_path, "jpg", seed=1, width=64, height=32,
                   color_low="#ff0000", color_high="#0000ff")
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.mode == "RGB" and im.size == (64, 32)
        rgb = np.asarray(im)
        assert rgb[..., 0].max() > 150 and rgb[..., 2].max() > 150


def test_random_default_seed_is_used_for_name_and_pixels(converter, tmp_path):
    fmt = get_format("png")
    options = converter.resolve_options(NOISE, fmt, {"width": "32", "height": "32"})
    out = converter.convert(NOISE, fmt, converter.output_path(NOISE, fmt, options, tmp_path),
                            options)
    assert out.name == f"noise-{options['seed']}.png"
    again = render({**options})
    assert np.array_equal(pixels(out), again)


def test_cancel(converter, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        converter.convert(NOISE, get_format("png"), tmp_path / "x.png", {"seed": 1},
                          cancel=cancel)
    assert list(tmp_path.iterdir()) == []
