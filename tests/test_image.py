import pytest
from PIL import Image

from omniconverter.core.formats import get_format


@pytest.fixture
def gps_photo(tmp_path):
    """A 300×200 JPEG with EXIF: rotated (orientation 6), camera maker and GPS."""
    path = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "CamMaker"
    exif.get_ifd(0x8825)[2] = (52.0, 31.0, 12.0)
    Image.new("RGB", (300, 200), "orange").save(path, exif=exif.tobytes())
    return path


@pytest.fixture
def transparent_png(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGBA", (120, 60), (255, 0, 0, 0)).save(path)
    return path


def convert(converter, path, target, tmp_path, name="out", **options):
    source = converter.inspect(path)
    fmt = get_format(target)
    return converter.convert(source, fmt, tmp_path / f"{name}.{fmt.extension}", options)


def test_metadata_stripped_by_default_and_orientation_applied(converter, gps_photo, tmp_path):
    out = convert(converter, gps_photo, "webp", tmp_path)
    with Image.open(out) as im:
        assert im.size == (200, 300)  # rotated according to EXIF orientation
        assert dict(im.getexif()) == {}


def test_metadata_can_be_kept(converter, gps_photo, tmp_path):
    out = convert(converter, gps_photo, "png", tmp_path, strip_metadata=False)
    with Image.open(out) as im:
        exif = im.getexif()
        assert exif.get(0x010F) == "CamMaker"
        assert 0x0112 not in exif  # orientation already baked into the pixels
        assert exif.get_ifd(0x8825)


def test_transparency_flattened_for_jpeg(converter, transparent_png, tmp_path):
    out = convert(converter, transparent_png, "jpg", tmp_path, background="#00ff00")
    with Image.open(out) as im:
        assert im.mode == "RGB"
        r, g, b = im.getpixel((10, 10))
        assert g > 240 and r < 20 and b < 20


def test_ico_is_square_with_sizes(converter, transparent_png, tmp_path):
    out = convert(converter, transparent_png, "ico", tmp_path)
    with Image.open(out) as im:
        assert im.format == "ICO"
        assert {(16, 16), (32, 32), (64, 64)} <= set(im.info["sizes"])
        assert (128, 128) not in im.info["sizes"]  # never upscale beyond the source


@pytest.mark.parametrize(("mode", "opts", "size"), [
    ("percent", {"percent": 50}, (150, 100)),
    ("fit", {"max_width": 100, "max_height": 100}, (100, 67)),
    ("fit", {"max_width": 1000, "max_height": 1000}, (300, 200)),  # no upscaling
])
def test_resize(converter, tmp_path, mode, opts, size):
    src = tmp_path / "in.png"
    Image.new("RGB", (300, 200), "blue").save(src)
    out = convert(converter, src, "png", tmp_path, resize=mode, **opts)
    with Image.open(out) as im:
        assert im.size == size


def test_animated_gif_to_webp_keeps_frames(converter, tmp_path):
    src = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (40, 30), c) for c in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=120, loop=0)
    out = convert(converter, src, "webp", tmp_path)
    with Image.open(out) as im:
        assert im.n_frames == 3
    single = convert(converter, src, "jpg", tmp_path)
    with Image.open(single) as im:
        assert getattr(im, "n_frames", 1) == 1


@pytest.mark.parametrize("target", ["avif", "heic", "tiff", "bmp", "gif", "pdf"])
def test_other_targets(converter, transparent_png, tmp_path, target):
    out = convert(converter, transparent_png, target, tmp_path)
    assert out.stat().st_size > 0
    if target != "pdf":
        from omniconverter.backends.image import register_heif

        register_heif()
        with Image.open(out) as im:
            assert im.size == (120, 60)


def test_quality_changes_size(converter, tmp_path):
    src = tmp_path / "noise.png"
    Image.effect_noise((256, 256), 80).convert("RGB").save(src)
    small = convert(converter, src, "jpg", tmp_path, name="small", quality=20)
    big = convert(converter, src, "jpg", tmp_path, name="big", quality=95)
    assert small.stat().st_size < big.stat().st_size


def test_broken_image_gives_friendly_error(converter, tmp_path):
    from omniconverter.core.errors import ConversionError

    src = tmp_path / "broken.png"
    src.write_bytes(b"not a png")
    with pytest.raises(ConversionError):
        convert(converter, src, "jpg", tmp_path)


@pytest.fixture
def gradient_png(tmp_path):
    """Photo-like colors: thousands of them, which a palette has to approximate."""
    import numpy as np

    x = np.linspace(0, 255, 200)
    rg = np.stack(np.meshgrid(x, x[::-1]), axis=-1)
    rgb = np.concatenate([rg, rg.mean(axis=-1, keepdims=True)], axis=-1)
    grain = np.random.default_rng(7).normal(0, 12, rgb.shape)
    rgb = np.clip(rgb + grain, 0, 255).astype(np.uint8)
    path = tmp_path / "gradient.png"
    Image.fromarray(rgb, "RGB").save(path)
    return path


@pytest.mark.parametrize("dither", ["floyd_steinberg", "none"])
def test_png_colors_make_a_small_palette_image(converter, gradient_png, tmp_path, dither):
    full = convert(converter, gradient_png, "png", tmp_path, name="full")
    few = convert(converter, gradient_png, "png", tmp_path, name="few", colors=16, dither=dither)
    with Image.open(few) as im:
        assert im.mode == "P" and im.size == (200, 200)
        assert len(im.convert("RGB").getcolors(256)) <= 16
    assert few.stat().st_size < full.stat().st_size / 2
    with Image.open(full) as im:
        assert im.mode == "RGB"  # "all" (the default) stays lossless true color


def test_png_colors_keep_transparency(converter, tmp_path):
    import numpy as np

    rgba = np.zeros((40, 80, 4), dtype=np.uint8)
    rgba[..., 0] = np.linspace(0, 255, 80)
    rgba[:, 40:, 3] = 255  # left half transparent, right half opaque
    src = tmp_path / "half.png"
    Image.fromarray(rgba, "RGBA").save(src)
    out = convert(converter, src, "png", tmp_path, colors=8)
    with Image.open(out) as im:
        assert im.mode == "P" and "transparency" in im.info
        alpha = np.asarray(im.convert("RGBA"))[..., 3]
    assert alpha[:, :40].max() == 0 and alpha[:, 40:].min() == 255


def test_png_colors_keep_images_with_few_colors_exact(converter, tmp_path):
    src = tmp_path / "flags.png"
    im = Image.new("RGB", (30, 20), "red")
    im.paste((0, 128, 0), (10, 0, 20, 20))
    im.paste((0, 0, 255), (20, 0, 30, 20))
    im.save(src)
    out = convert(converter, src, "png", tmp_path, colors=4)
    with Image.open(out) as result:
        colors = {c for _n, c in result.convert("RGB").getcolors()}
    assert colors == {(255, 0, 0), (0, 128, 0), (0, 0, 255)}


def test_colors_option_only_for_png(converter, gradient_png):
    source = converter.inspect(gradient_png)
    keys = {o.key for o in converter.options(source, get_format("png"))}
    assert {"colors", "dither"} <= keys
    for target in ("jpg", "webp", "gif"):
        assert "colors" not in {o.key for o in converter.options(source, get_format(target))}
    values = converter.resolve_options(source, get_format("png"), {"colors": "64"})
    assert values["colors"] == 64  # as typed on the command line: -s colors=64
