import numpy as np
import pytest
from PIL import Image

from omniconverter.core.formats import get_format


def make(tmp_path, pixels, name="tex.png"):
    path = tmp_path / name
    Image.fromarray(np.asarray(pixels, dtype=np.uint8)).save(path)
    return path


def convert(converter, path, target, tmp_path, **options):
    source = converter.inspect(path)
    fmt = get_format(target)
    out = converter.output_path(source, fmt, directory=tmp_path)
    return converter.convert(source, fmt, out, options)


def test_flat_texture_points_straight_up(converter, tmp_path):
    flat = make(tmp_path, np.full((16, 16, 3), 120))
    out = convert(converter, flat, "normal-map", tmp_path)
    assert out.name == "tex_normal.png"
    with Image.open(out) as im:
        assert im.mode == "RGB" and im.size == (16, 16)
        assert (np.asarray(im) == (128, 128, 255)).all()


def test_slopes_tilt_the_normals(converter, tmp_path):
    # Brighter to the right: the surface rises to the right, so normals lean left (red < 128).
    ramp = np.tile(np.linspace(0, 255, 32), (32, 1))
    path = make(tmp_path, np.stack([ramp] * 3, axis=-1))
    out = convert(converter, path, "normal-map", tmp_path, seamless=False, blur=0)
    pixels = np.asarray(Image.open(out)).astype(int)
    assert pixels[16, 16, 0] < 110 and abs(pixels[16, 16, 1] - 128) <= 1
    inverted = convert(converter, path, "normal-map", tmp_path, seamless=False, blur=0,
                       invert=True)
    assert np.asarray(Image.open(inverted))[16, 16, 0] > 146


def test_directx_flips_green(converter, tmp_path):
    # Brighter towards the bottom: in OpenGL convention the normal leans up (green > 128).
    ramp = np.tile(np.linspace(0, 255, 32)[:, None], (1, 32))
    path = make(tmp_path, ramp)
    opengl = np.asarray(Image.open(convert(converter, path, "normal-map", tmp_path,
                                           seamless=False)))
    directx = np.asarray(Image.open(convert(converter, path, "normal-map", tmp_path,
                                            seamless=False, convention="directx")))
    assert opengl[16, 16, 1] > 146
    assert int(opengl[16, 16, 1]) + int(directx[16, 16, 1]) == pytest.approx(255, abs=1)
    assert opengl[16, 16, 0] == directx[16, 16, 0] == 128


def test_seamless_wraps_around_the_edges(converter, tmp_path):
    rng = np.random.default_rng(3)
    path = make(tmp_path, rng.integers(0, 256, (24, 24)))
    wrapped = np.asarray(Image.open(convert(converter, path, "normal-map", tmp_path)))
    # Shifting the texture by half its size gives the same map, shifted: no seams.
    shifted = make(tmp_path, np.roll(np.asarray(Image.open(path)), (12, 12), axis=(0, 1)),
                   "shifted.png")
    wrapped_shifted = np.asarray(Image.open(convert(converter, shifted, "normal-map",
                                                    tmp_path)))
    assert np.array_equal(np.roll(wrapped, (12, 12), axis=(0, 1)), wrapped_shifted)


def test_specular_levels_and_roughness(converter, tmp_path):
    path = make(tmp_path, [[[0, 0, 0], [255, 255, 255], [128, 128, 128]]])
    out = convert(converter, path, "specular-map", tmp_path)
    assert out.name == "tex_specular.png"
    with Image.open(out) as im:
        assert im.mode == "L" and np.asarray(im).tolist() == [[0, 255, 128]]
    rough = convert(converter, path, "specular-map", tmp_path, invert=True, contrast=200)
    assert np.asarray(Image.open(rough)).tolist() == [[255, 0, 126]]


def test_transparent_areas_count_as_low(converter, tmp_path):
    path = tmp_path / "decal.png"
    im = Image.new("RGBA", (4, 1), (255, 255, 255, 255))
    im.putpixel((0, 0), (255, 255, 255, 0))
    im.save(path)
    out = convert(converter, path, "specular-map", tmp_path)
    assert np.asarray(Image.open(out)).tolist() == [[0, 255, 255, 255]]


def test_image_sources_offer_texture_maps(converter, tmp_path):
    path = make(tmp_path, np.zeros((4, 4, 3)), "photo.jpg")
    ids = {c.format.id for c in converter.targets([converter.inspect(path)])}
    assert {"normal-map", "specular-map"} <= ids
