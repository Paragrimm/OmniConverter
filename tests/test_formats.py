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
        for ext in fmt.extensions:
            assert ext not in seen, f"{ext} used by {seen.get(ext)} and {fmt.id}"
            seen[ext] = fmt.id
            assert ext == ext.lower()


def test_canonical_extension_is_first():
    assert get_format("jpg").extension == "jpg"
    assert get_format("yaml").extension == "yaml"
