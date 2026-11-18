"""PDF pages as images, choosing/splitting pages, and joining PDFs and pictures (PDFium)."""

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from omniconverter.backends.pdf import parse_pages
from omniconverter.core.errors import ConversionError, OptionError
from omniconverter.core.formats import get_format

COLORS = ("red", "lime", "blue")


@pytest.fixture
def pdf_file(tmp_path):
    """Three A4-ish pages at 72 dpi (595×842 pt): red, green, blue."""
    pages = []
    for color in COLORS:
        page = Image.new("RGB", (595, 842), color)
        ImageDraw.Draw(page).rectangle((0, 0, 99, 99), fill="white")
        pages.append(page)
    path = tmp_path / "report.pdf"
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=72.0)
    return path


def page_count(path):
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def center(path):
    with Image.open(path) as im:
        return im.convert("RGB").getpixel((im.width // 2, im.height // 2))


@pytest.mark.parametrize(("text", "pages"), [
    ("", [0, 1, 2, 3, 4]),
    ("2", [1]),
    ("1-3, 5", [0, 1, 2, 4]),
    ("4-", [3, 4]),
    ("-2", [0, 1]),
    ("5,1", [4, 0]),
    ("2 – 3; 1", [1, 2, 0]),
])
def test_parse_pages(text, pages):
    assert parse_pages(text, 5) == pages


@pytest.mark.parametrize("text", ["0", "6", "3-2", "a", "1-2-3", "-", ","])
def test_parse_pages_rejects(text):
    with pytest.raises(OptionError):
        parse_pages(text, 5)


def test_pdf_is_a_source_with_image_and_pdf_targets(converter, pdf_file):
    source = converter.inspect(pdf_file)
    assert [c.format.id for c in converter.targets([source])] == ["png", "jpg", "webp", "pdf"]
    assert all(c.available for c in converter.targets([source]))


def test_all_pages_become_images_in_a_folder(converter, pdf_file):
    source = converter.inspect(pdf_file)
    png = get_format("png")
    out = converter.output_path(source, png)
    assert out == pdf_file.parent / "report"  # a folder named after the PDF
    result = converter.convert(source, png, out, {"dpi": 72})
    assert result == out and out.is_dir()
    names = sorted(p.name for p in out.iterdir())
    assert names == ["report-1.png", "report-2.png", "report-3.png"]
    for name, color in zip(names, COLORS, strict=True):
        with Image.open(out / name) as im:
            assert im.size == (595, 842)
        expected = Image.new("RGB", (1, 1), color).getpixel((0, 0))
        assert all(abs(a - b) <= 3 for a, b in zip(center(out / name), expected, strict=True))
    # a second run never touches the first folder
    assert converter.output_path(source, png) == pdf_file.parent / "report (1)"


def test_one_page_is_one_file_at_the_chosen_resolution(converter, pdf_file):
    source = converter.inspect(pdf_file)
    jpg = get_format("jpg")
    values = {"pages": "3", "dpi": 150}
    out = converter.output_path(source, jpg, values)
    assert out == pdf_file.with_suffix(".jpg")
    converter.convert(source, jpg, out, values)
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert abs(im.width - 595 * 150 / 72) <= 1
    r, g, b = center(out)
    assert b > 200 and r < 50 and g < 50


def test_choose_and_split_pages(converter, pdf_file):
    source = converter.inspect(pdf_file)
    pdf = get_format("pdf")
    out = converter.output_path(source, pdf, {"pages": "3,1"})
    assert out == pdf_file.parent / "report (1).pdf"  # never the source itself
    converter.convert(source, pdf, out, {"pages": "3,1"})
    assert page_count(out) == 2

    split = converter.output_path(source, pdf, {"split": True})
    converter.convert(source, pdf, split, {"split": True, "pages": "2-"})
    assert sorted(p.name for p in split.iterdir()) == ["report-2.pdf", "report-3.pdf"]
    assert all(page_count(p) == 1 for p in split.iterdir())


def test_bad_pages_and_broken_pdfs_give_friendly_errors(converter, pdf_file, tmp_path):
    source = converter.inspect(pdf_file)
    with pytest.raises(ConversionError, match="has 3 page"):
        converter.convert(source, get_format("png"), tmp_path / "x.png", {"pages": "7"})
    assert not (tmp_path / "x.png").exists()
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing here")
    with pytest.raises(ConversionError, match="Could not read the PDF"):
        converter.convert(converter.inspect(broken), get_format("png"), tmp_path / "y.png")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []  # no half-written files or folders


def test_preview_shows_the_first_chosen_page(converter, pdf_file, tmp_path):
    source = converter.inspect(pdf_file)
    preview = converter.preview(source, get_format("png"), {"pages": "2-3", "dpi": 72},
                                tmp_path)
    assert (preview.width, preview.height) == (595, 842)
    assert preview.note == "first of 2 pages, one file each"
    assert center(preview.frames[0])[1] > 200  # green: page 2
    preview = converter.preview(source, get_format("pdf"), {"pages": "1"}, tmp_path)
    assert preview.note == "" and preview.size_bytes


def test_pdfs_and_pictures_join_into_one_pdf(converter, pdf_file, tmp_path):
    picture = tmp_path / "zz-photo.png"
    Image.new("RGB", (40, 30), "orange").save(picture)
    sources = [converter.inspect(picture), converter.inspect(pdf_file)]
    pdf = get_format("pdf")
    assert converter.wants_combine(sources, pdf)
    out = converter.combined_output_path(sources, pdf)
    converter.combine(sources, pdf, out)
    assert page_count(out) == 4  # report.pdf first (name order), then the photo
    preview = converter.preview_combined(sources, pdf, {}, tmp_path)
    assert preview.note == "4 pages"
    assert center(preview.frames[0])[0] > 200  # the red first page

    # several PDFs only: merged as well
    copy = tmp_path / "report 2.pdf"
    copy.write_bytes(pdf_file.read_bytes())
    sources = [converter.inspect(copy), converter.inspect(pdf_file)]
    out = converter.combine(sources, pdf, tmp_path / "both.pdf")
    assert page_count(out) == 6
