import zipfile

import pytest

from omniconverter.backends import document
from omniconverter.core import process
from omniconverter.core.formats import get_format
from tests.conftest import needs_pandoc, needs_soffice

MARKDOWN = (
    "# Überschrift\n\nText mit **fett** und Umlauten äöü.\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n"
)


@pytest.fixture
def md_file(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(MARKDOWN, encoding="utf-8")
    return path


def convert(converter, path, target):
    source = converter.inspect(path)
    fmt = get_format(target)
    return converter.convert(source, fmt, path.with_name(f"{path.stem}-out.{fmt.extension}"))


@needs_pandoc
def test_markdown_to_docx_and_html(converter, md_file):
    docx = convert(converter, md_file, "docx")
    with zipfile.ZipFile(docx) as z:
        assert "Überschrift" in z.read("word/document.xml").decode("utf-8")
    html = convert(converter, md_file, "html").read_text(encoding="utf-8")
    assert "<table" in html and "<html" in html  # standalone document


@needs_pandoc
def test_docx_back_to_markdown(converter, md_file):
    docx = convert(converter, md_file, "docx")
    md = convert(converter, docx, "md").read_text(encoding="utf-8")
    assert "Überschrift" in md and "**fett**" in md


def make_docx(path, text):
    """Smallest valid DOCX, so the LibreOffice test does not depend on Pandoc."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" '
            f'Type="{rel}" Target="word/document.xml"/></Relationships>'))
        z.writestr("word/document.xml", (
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>'
            f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'))
    return path


@needs_soffice
def test_docx_to_pdf_uses_libreoffice(converter, tmp_path):
    docx = make_docx(tmp_path / "letter.docx", "Hallo LibreOffice")
    pdf = convert(converter, docx, "pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    odt = convert(converter, docx, "odt")
    with zipfile.ZipFile(odt) as z:
        assert "Hallo LibreOffice" in z.read("content.xml").decode("utf-8")


@needs_pandoc
@needs_soffice
def test_markdown_to_pdf_chain(converter, md_file):
    pdf = convert(converter, md_file, "pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


@needs_soffice
def test_spreadsheet_via_libreoffice(converter, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["x", "y"])
    wb.active.append([1, 2])
    src = tmp_path / "sheet.xlsx"
    wb.save(src)
    ods = convert(converter, src, "ods")
    with zipfile.ZipFile(ods) as z:
        assert z.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"


def test_office_formats_prefer_libreoffice(converter):
    backend, _conv = converter.registry.resolve(get_format("docx"), get_format("odt"))
    locator = converter.locator
    if locator.available("soffice"):
        assert backend.id == "libreoffice"
    backend, _conv = converter.registry.resolve(get_format("csv"), get_format("xlsx"))
    assert backend.id == "data"  # no LibreOffice needed for csv ↔ xlsx


class Recorder:
    def __init__(self, fail_sandbox=False):
        self.calls = []
        self.fail_sandbox = fail_sandbox

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.fail_sandbox and "--sandbox" in args:
            raise document.ConversionError("Pandoc failed.",
                                           "Could not find data file data/docx/x.xml")
        return process.RunResult(0, "", "")


class Ctx:
    def __init__(self, tmp_path):
        from omniconverter.core.tools import ToolLocator

        self.locator = ToolLocator({"pandoc": __file__})
        self.cancel = None
        self.work_dir = tmp_path


@pytest.fixture
def fake_pandoc(monkeypatch):
    monkeypatch.setattr(document, "pandoc_version", lambda _p: (3, 1))
    document._sandbox_broken.clear()
    yield
    document._sandbox_broken.clear()


def test_pandoc_runs_sandboxed_without_network(monkeypatch, tmp_path, fake_pandoc):
    rec = Recorder()
    monkeypatch.setattr(document.process, "run", rec)
    monkeypatch.setattr("omniconverter.core.tools._is_executable", lambda _p: True)
    document.run_pandoc(Ctx(tmp_path), tmp_path / "a.md", "md", "docx", tmp_path / "o.docx", {})
    (args, kwargs), = rec.calls
    assert "--sandbox" in args
    assert kwargs["env"]["https_proxy"] == "http://127.0.0.1:9"
    assert kwargs["env"]["no_proxy"] == ""


def test_pandoc_sandbox_fallback_keeps_network_block(monkeypatch, tmp_path, fake_pandoc):
    rec = Recorder(fail_sandbox=True)
    monkeypatch.setattr(document.process, "run", rec)
    monkeypatch.setattr("omniconverter.core.tools._is_executable", lambda _p: True)
    ctx = Ctx(tmp_path)
    document.run_pandoc(ctx, tmp_path / "a.md", "md", "docx", tmp_path / "o.docx", {})
    assert len(rec.calls) == 2
    retry_args, retry_kwargs = rec.calls[1]
    assert "--sandbox" not in retry_args
    assert retry_kwargs["env"]["HTTPS_PROXY"] == "http://127.0.0.1:9"
    # remembered: the next run skips the doomed sandbox attempt
    document.run_pandoc(ctx, tmp_path / "a.md", "md", "docx", tmp_path / "o.docx", {})
    assert "--sandbox" not in rec.calls[2][0]


def test_libreoffice_uses_private_profile(monkeypatch, tmp_path):
    rec = Recorder()
    monkeypatch.setattr(document.process, "run", rec)
    monkeypatch.setattr("omniconverter.core.tools._is_executable", lambda _p: True)
    ctx = Ctx(tmp_path)
    ctx.locator.set_override("soffice", __file__)
    (tmp_path / "lo-out").mkdir()
    (tmp_path / "lo-out" / "a.pdf").write_bytes(b"%PDF")
    document.run_libreoffice(ctx, tmp_path / "a.docx", "pdf", tmp_path / "result.pdf")
    (args, _kw), = rec.calls
    assert args[1].startswith("-env:UserInstallation=file:")
    assert str(tmp_path) in args[1] or tmp_path.as_uri() in args[1]
    assert "--headless" in args and "--norestore" in args
    assert (tmp_path / "result.pdf").read_bytes() == b"%PDF"
