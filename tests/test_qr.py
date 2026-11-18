import plistlib
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import segno
from PIL import Image

from omniconverter.core.converter import SourceFile
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import get_format

URL = "https://roamingowl.itch.io/owlish-emotes"


def modules(path, size, border=4):
    """Read a QR PNG with *size*×*size* modules back into a matrix of dark (True) modules."""
    with Image.open(path) as im:
        gray = np.asarray(im.convert("L"))
    count = size + 2 * border
    assert gray.shape[0] % count == 0  # whole pixels per module: sharp edges
    scale = gray.shape[0] // count
    centers = np.arange(border, count - border) * scale + scale // 2
    return (gray[np.ix_(centers, centers)] < 128).tolist()


def expected(payload, error="m"):
    return [[bool(v) for v in row] for row in segno.make(payload, error=error, micro=False).matrix]


def assert_encodes(path, payload, error="m"):
    matrix = expected(payload, error)
    assert modules(path, len(matrix)) == matrix


def test_link_becomes_scannable_png(converter, tmp_path):
    source = SourceFile.from_text(URL)
    out = converter.convert(source, get_format("qr"), tmp_path / "code.png",
                            {"size": "600", "error_correction": "h"})
    assert_encodes(out, URL, "h")
    with Image.open(out) as im:
        assert 500 <= im.size[0] <= 700  # the requested size, in whole pixels per module


def test_default_name_for_typed_text(converter, tmp_path):
    source = SourceFile.from_text(URL)
    assert converter.output_path(source, get_format("qr-png"), directory=tmp_path) == \
        tmp_path / "qr-code.png"
    note = tmp_path / "note.txt"
    note.write_text("hi")
    assert converter.output_path(converter.inspect(note), get_format("qr-svg")) == \
        tmp_path / "note_qr.svg"


def test_svg_output_and_colors(converter, tmp_path):
    out = converter.convert(SourceFile.from_text("hello"), get_format("qr-svg"),
                            tmp_path / "code.svg", {"dark": "#123456", "transparent": True})
    root = ET.parse(out).getroot()
    assert root.tag.endswith("svg")
    assert "#123456" in out.read_text()


@pytest.mark.parametrize(("name", "content"), [
    ("site.url", b"[InternetShortcut]\r\nURL=" + URL.encode() + b"\r\nIconIndex=0\r\n"),
    ("site.webloc", plistlib.dumps({"URL": URL})),
    ("site_binary.webloc", plistlib.dumps({"URL": URL}, fmt=plistlib.FMT_BINARY)),
])
def test_shortcut_files_encode_their_url(converter, tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    source = converter.inspect(path)
    assert source.format.id == "url"
    out = converter.convert(source, get_format("qr-png"), tmp_path / "code.png")
    assert_encodes(out, URL)


def test_text_files_and_vcards(converter, tmp_path):
    # Bytes, not write_text(): that would turn "\n" into "\r\n" on Windows only. vCards use
    # CRLF, and the content is encoded exactly as it is in the file.
    vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Mibo Owl\r\nEND:VCARD"
    path = tmp_path / "mibo.vcf"
    path.write_bytes((vcard + "\r\n").encode("utf-8"))
    out = converter.convert(converter.inspect(path), get_format("qr-png"), tmp_path / "v.png")
    assert_encodes(out, vcard)

    note = tmp_path / "note.txt"
    note.write_bytes("Grüße\n".encode("cp1252"))  # old Windows text files work, too
    out = converter.convert(converter.inspect(note), get_format("qr-png"), tmp_path / "n.png")
    assert_encodes(out, "Grüße")


def test_too_much_or_no_content(converter, tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 5000)
    with pytest.raises(ConversionError, match="5000 bytes"):
        converter.convert(converter.inspect(big), get_format("qr-png"), tmp_path / "a.png")
    with pytest.raises(ConversionError, match="empty"):
        converter.convert(SourceFile.from_text("  \n "), get_format("qr-png"),
                          tmp_path / "b.png")
    broken = tmp_path / "broken.url"
    broken.write_text("[InternetShortcut]\n")
    with pytest.raises(ConversionError, match="no address"):
        converter.convert(converter.inspect(broken), get_format("qr-png"), tmp_path / "c.png")
    assert not list(tmp_path.glob("*.png"))


def test_only_text_like_files_offer_qr_codes(converter, tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (4, 4)).save(photo)
    ids = {c.format.id for c in converter.targets([converter.inspect(photo)])}
    assert "qr-png" not in ids
    text_targets = {c.format.id for c in converter.targets([SourceFile.from_text("x")])}
    assert text_targets == {"qr-png", "qr-svg"}


# -- reading codes -----------------------------------------------------------------------------


def test_reading_a_qr_code_from_a_picture(converter, tmp_path):
    text = "WIFI:T:WPA;S:Eulennest;P:geheim;;"
    picture = tmp_path / "poster.jpg"
    code = tmp_path / "code.png"
    segno.make(text).save(code, scale=6)
    with Image.open(code) as im:  # a photo-like picture: code in a corner, JPEG
        canvas = Image.new("RGB", (600, 400), "#d0c8b0")
        canvas.paste(im.convert("RGB"), (380, 180))
        canvas.save(picture, quality=85)
    source = converter.inspect(picture)
    target = get_format("qr-text")
    assert target.id in {c.format.id for c in converter.targets([source])}
    out = converter.output_path(source, target)
    assert out == tmp_path / "poster_qr.txt"
    converter.convert(source, target, out)
    assert out.read_text(encoding="utf-8") == text + "\n"
    preview = converter.preview(source, target, {}, tmp_path)
    assert preview.note == text
    with Image.open(preview.frames[0]) as im:
        assert im.size == (600, 400)
        assert im.convert("RGB").getpixel((380 + 10, 180 + 3))[1] > 150  # outlined in green


def test_reading_several_codes_and_transparent_ones(converter, tmp_path):
    picture = tmp_path / "two.png"
    canvas = Image.new("RGBA", (700, 300), (0, 0, 0, 0))
    for index, text in enumerate(("first", "second")):
        path = tmp_path / f"{index}.png"
        segno.make(text).save(path, scale=8, light=None)
        with Image.open(path) as im:
            canvas.paste(im.convert("RGBA"), (20 + index * 350, 20))
    canvas.save(picture)
    out = converter.convert(converter.inspect(picture), get_format("qr-text"),
                            tmp_path / "out.txt")
    assert out.read_text(encoding="utf-8") == "first\n\nsecond\n"


def test_no_code_in_the_picture(converter, tmp_path):
    picture = tmp_path / "plain.png"
    Image.new("RGB", (200, 200), "white").save(picture)
    with pytest.raises(ConversionError, match="No QR code"):
        converter.convert(converter.inspect(picture), get_format("qr-text"), tmp_path / "x.txt")
    assert not (tmp_path / "x.txt").exists()
