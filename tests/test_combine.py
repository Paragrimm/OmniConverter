"""Several pictures into one GIF or PDF."""

import pypdfium2 as pdfium
import pytest
from PIL import Image

from omniconverter.core.converter import COMBINE, combine_order, natural_key, shared_stem
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import get_format


@pytest.fixture
def pictures(tmp_path):
    paths = []
    for name, color, size in (("scan_10.png", "blue", (40, 80)), ("scan_2.jpg", "lime", (80, 60)),
                              ("scan_1.png", "red", (80, 60))):
        path = tmp_path / name
        Image.new("RGB", size, color).save(path)
        paths.append(path)
    return paths


def test_natural_order_and_shared_names():
    names = ["scan 10.png", "scan 2.png", "Scan 1.png", "a.png"]
    assert sorted(names, key=natural_key) == ["a.png", "Scan 1.png", "scan 2.png", "scan 10.png"]
    assert shared_stem(["IMG_2041", "IMG_2042"]) == "IMG"
    assert shared_stem(["urlaub-1", "urlaub-2"]) == "urlaub"
    assert shared_stem(["cat", "dog"]) == ""


def test_join_option_only_for_several_pictures_and_gif_or_pdf(converter, pictures):
    sources = [converter.inspect(p) for p in pictures]
    gif, pdf, png = get_format("gif"), get_format("pdf"), get_format("png")
    keys = [o.key for o in converter.options_for(sources, gif)]
    assert keys[0] == COMBINE and {"frame_ms", "loop", "resize"} <= set(keys)
    assert converter.options_for(sources, pdf)[0].key == COMBINE
    assert COMBINE not in [o.key for o in converter.options_for(sources, png)]
    assert COMBINE not in [o.key for o in converter.options_for(sources[:1], gif)]
    assert converter.wants_combine(sources, gif)
    assert not converter.wants_combine(sources, gif, {COMBINE: "no"})
    # GIF-only options appear only while joining
    by_key = {o.key: o for o in converter.options_for(sources, gif)}
    assert by_key["frame_ms"].is_visible({COMBINE: True})
    assert not by_key["frame_ms"].is_visible({COMBINE: False})


def test_pictures_become_one_gif_in_name_order(converter, pictures):
    sources = [converter.inspect(p) for p in pictures]
    gif = get_format("gif")
    out = converter.combined_output_path(sources, gif)
    assert out == pictures[0].parent / "scan.gif"
    converter.combine(sources, gif, out, {COMBINE: True, "frame_ms": 250, "loop": "once"})
    with Image.open(out) as im:
        assert im.n_frames == 3 and im.size == (80, 60)  # all frames in the first one's size
        assert "loop" not in im.info  # plays once
        colors = []
        for index in range(3):
            im.seek(index)
            assert im.info["duration"] == 250
            colors.append(im.convert("RGB").getpixel((40, 30)))
    assert colors[0][0] > 200 and colors[1][1] > 200 and colors[2][2] > 200  # red, lime, blue


def test_animated_gifs_keep_their_frames(converter, tmp_path, pictures):
    anim = tmp_path / "scan_0.gif"
    frames = [Image.new("RGB", (80, 60), c) for c in ("white", "black")]
    frames[0].save(anim, save_all=True, append_images=frames[1:], duration=70, loop=0)
    sources = [converter.inspect(p) for p in [*pictures, anim]]
    out = converter.combine(sources, get_format("gif"), tmp_path / "out.gif")
    with Image.open(out) as im:
        assert im.n_frames == 5 and im.info["loop"] == 0
        assert im.info["duration"] == 70  # the animation comes first and keeps its timing


def test_pictures_become_one_pdf_with_a_page_each(converter, pictures, tmp_path):
    sources = [converter.inspect(p) for p in pictures]
    pdf = get_format("pdf")
    out = converter.combine(sources, pdf, tmp_path / "all.pdf", {"resize": "percent",
                                                                 "percent": 50})
    doc = pdfium.PdfDocument(str(out))
    try:
        sizes = [tuple(round(v) for v in doc.get_page_size(i)) for i in range(len(doc))]
    finally:
        doc.close()
    assert sizes == [(30, 22), (30, 22), (15, 30)]  # 50 % of each picture, at 96 dpi
    preview = converter.preview_combined(sources, pdf, {}, tmp_path)
    assert preview.note == "3 pages"


def test_combine_never_overwrites_a_source_and_reports_bad_files(converter, pictures, tmp_path):
    sources = [converter.inspect(p) for p in pictures]
    with pytest.raises(ConversionError):
        converter.combine(sources, get_format("gif"), pictures[0])
    broken = tmp_path / "scan_3.png"
    broken.write_bytes(b"not a picture")
    sources.append(converter.inspect(broken))
    with pytest.raises(ConversionError, match=r"scan_3\.png"):
        converter.combine(sources, get_format("pdf"), tmp_path / "x.pdf")
    assert not (tmp_path / "x.pdf").exists()


def test_combine_order_uses_file_names(converter, pictures):
    sources = [converter.inspect(p) for p in pictures]
    assert [s.path.name for s in combine_order(sources)] == ["scan_1.png", "scan_2.jpg",
                                                              "scan_10.png"]
