import pytest

from omniconverter.core.formats import FORMATS, Category, detect_format, get_format


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("clip.MP4", "mp4"),
        ("photo.jpeg", "jpg"),
        ("photo.JPG", "jpg"),
        ("scan.tif", "tiff"),
        ("page.htm", "html"),
        ("config.yml", "yaml"),
        ("iphone.HEIF", "heic"),
        ("movie.mpg", "mpeg"),
        ("stream.m2ts", "ts"),
        ("song.aif", "aiff"),
        ("model.GLB", "glb"),
        ("scene.fbx", "fbx"),
        ("print.stl", "stl"),
        ("Website.url", "url"),
        ("Website.webloc", "url"),
        ("contact.vcf", "vcf"),
        ("archive.tar.gz", None),
        ("no_extension", None),
    ],
)
def test_detect_by_extension(name, expected):
    fmt = detect_format(name)
    assert (fmt.id if fmt else None) == expected


def test_get_format_accepts_ids_and_extensions():
    assert get_format("JPEG").id == "jpg"
    assert get_format(".tif").id == "tiff"
    assert get_format("mp4").category is Category.VIDEO
    with pytest.raises(KeyError):
        get_format("nope")


def test_extensions_are_unique():
    seen = {}
    for fmt in FORMATS.values():
        if not fmt.detect:
            continue
        for ext in fmt.extensions:
            assert ext not in seen, f"{ext} used by {seen.get(ext)} and {fmt.id}"
            seen[ext] = fmt.id
            assert ext == ext.lower()


def test_canonical_extension_is_first():
    assert get_format("jpg").extension == "jpg"
    assert get_format("yaml").extension == "yaml"


def test_derived_targets_and_generators_are_never_detected():
    # A PNG stays a PNG even though Normal-Map and QR-Code also produce .png files.
    assert detect_format("wall.png").id == "png"
    assert detect_format("code.svg") is None
    normal = get_format("normal-map")
    assert (normal.category, normal.extension, normal.name_suffix) == (
        Category.TEXTURE, "png", "_normal")
    assert get_format("qr").id == "qr-png"  # aliases
    assert get_format("specular").id == "specular-map"
    for generator in ("text", "noise"):
        fmt = get_format(generator)
        assert fmt.category is Category.GENERATOR and fmt.extension == ""
