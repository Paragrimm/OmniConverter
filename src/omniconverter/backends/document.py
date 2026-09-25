"""Documents via Pandoc (markup formats) and LibreOffice headless (office formats, PDF)."""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections.abc import Iterable
from functools import partial
from pathlib import Path

from omniconverter.core import process
from omniconverter.core.backend import Backend, Conversion, ConversionContext, ConversionRequest
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import Format
from omniconverter.core.options import Kind, Option
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

PANDOC_READERS = {
    "md": "markdown", "html": "html", "docx": "docx", "odt": "odt", "epub": "epub",
    "rst": "rst", "tex": "latex", "rtf": "rtf",
}
PANDOC_WRITERS = {
    "md": "gfm", "html": "html", "docx": "docx", "odt": "odt", "epub": "epub3", "rtf": "rtf",
    "txt": "plain", "tex": "latex", "rst": "rst",
}
_STANDALONE = {"html", "rtf", "tex", "epub"}

# LibreOffice --convert-to specs ("extension:FilterName:FilterOptions").
LO_WRITER = {
    "pdf": "pdf",
    "docx": "docx:MS Word 2007 XML",
    "odt": "odt",
    "rtf": "rtf:Rich Text Format",
    "txt": "txt:Text (encoded):UTF8",
}
LO_CALC = {
    "pdf": "pdf",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "ods": "ods",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
}
LO_IMPRESS = {"pdf": "pdf", "pptx": "pptx:Impress MS PowerPoint 2007 XML", "odp": "odp"}
LO_GROUPS = (
    (("doc", "docx", "odt", "rtf", "txt"), LO_WRITER),
    (("html",), {"pdf": "pdf"}),
    (("xls", "xlsx", "ods", "csv"), LO_CALC),
    (("ppt", "pptx", "odp"), LO_IMPRESS),
)
# Markup that reaches PDF via Pandoc → DOCX → LibreOffice.
CHAIN_TO_PDF = ("md", "epub", "rst", "tex")

LO_TIMEOUT = 300
_pandoc_versions: dict[str, tuple[int, ...]] = {}
_version_lock = threading.Lock()
_sandbox_broken: set[str] = set()
_DEAD_PROXY = "http://127.0.0.1:9"
NO_NETWORK_ENV = {
    **{k: _DEAD_PROXY for k in ("http_proxy", "https_proxy", "all_proxy",
                                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")},
    "no_proxy": "",
    "NO_PROXY": "",
}


def pandoc_version(pandoc: str) -> tuple[int, ...]:
    with _version_lock:
        if pandoc not in _pandoc_versions:
            try:
                first = process.run([pandoc, "--version"], timeout=20).stdout.splitlines()[0]
                m = re.search(r"(\d+(?:\.\d+)+)", first)
                version = tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
            except (ConversionError, IndexError):
                version = (0,)
            _pandoc_versions[pandoc] = version
        return _pandoc_versions[pandoc]


def _pandoc_options() -> list[Option]:
    return [Option("allow_resources", t("opt.allow_resources"), Kind.BOOL, False,
                   advanced=True, help=t("opt.allow_resources_help"))]


class PandocBackend(Backend):
    """Markup and text documents (Markdown, HTML, DOCX, ODT, EPUB, …)."""

    id = "pandoc"

    def conversions(self) -> Iterable[Conversion]:
        for src in PANDOC_READERS:
            for dst in PANDOC_WRITERS:
                if src != dst:
                    yield Conversion(src, dst, ("pandoc",), priority=60)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        return _pandoc_options()

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        run_pandoc(ctx, request.source, request.source_format.id, request.target_format.id,
                   output, request.options)


class LibreOfficeBackend(Backend):
    """Office documents, spreadsheets and presentations, and anything → PDF.

    Preferred over Pandoc between office formats because it keeps the layout.
    """

    id = "libreoffice"

    def conversions(self) -> Iterable[Conversion]:
        for sources, targets in LO_GROUPS:
            for src in sources:
                for dst in targets:
                    if src != dst:
                        yield Conversion(src, dst, ("soffice",), priority=70)

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        run_libreoffice(ctx, request.source, request.target_format.id, output)


class MarkupToPdfBackend(Backend):
    """Markdown & co. → PDF: Pandoc renders DOCX, LibreOffice turns it into a PDF."""

    id = "pandoc+libreoffice"

    def conversions(self) -> Iterable[Conversion]:
        for src in CHAIN_TO_PDF:
            yield Conversion(src, "pdf", ("pandoc", "soffice"), priority=40)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        return _pandoc_options()

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        intermediate = ctx.work_dir / f"{request.source.stem}.docx"
        run_pandoc(ctx, request.source, request.source_format.id, "docx", intermediate,
                   request.options)
        ctx.check_cancelled()
        run_libreoffice(ctx, intermediate, request.target_format.id, output)


def run_pandoc(ctx: ConversionContext, source: Path, src: str, dst: str, output: Path,
               opts: dict) -> None:
    pandoc = ctx.locator.require("pandoc")
    args = [pandoc]
    if opts.get("allow_resources"):
        args.append(f"--resource-path={source.parent}")
    args += ["-f", PANDOC_READERS[src], "-t", PANDOC_WRITERS[dst]]
    if dst in _STANDALONE:
        args.append("--standalone")
    args += ["-o", str(output), str(source)]
    # Pandoc fetches remote images on its own; route that into a dead proxy in any case.
    env = {**os.environ, **NO_NETWORK_ENV}
    run = partial(process.run, cancel=ctx.cancel, env=env, timeout=LO_TIMEOUT,
                  error_message=t("error.pandoc_failed"))

    sandbox = (not opts.get("allow_resources") and pandoc not in _sandbox_broken
               and pandoc_version(pandoc) >= (2, 15))
    if sandbox:  # no network, no reading files besides the input
        try:
            run([pandoc, "--sandbox", *args[1:]])
            return
        except ConversionError as exc:
            # Distribution builds without embedded data files cannot write DOCX/ODT/EPUB
            # in sandbox mode; they still get the network block above.
            if "Could not find data file" not in exc.details:
                raise
            _sandbox_broken.add(pandoc)
    run(args)


def run_libreoffice(ctx: ConversionContext, source: Path, dst: str, output: Path) -> None:
    soffice = ctx.locator.require("soffice")
    spec = {**LO_WRITER, **LO_CALC, **LO_IMPRESS}[dst]
    profile = ctx.work_dir / "lo-profile"
    outdir = ctx.work_dir / "lo-out"
    outdir.mkdir(exist_ok=True)
    args = [
        soffice,
        f"-env:UserInstallation={profile.resolve().as_uri()}",  # isolated, throw-away profile
        "--headless", "--invisible", "--nologo", "--nodefault", "--nofirststartwizard",
        "--norestore", "--nolockcheck",
        "--convert-to", spec,
        "--outdir", str(outdir),
        str(source),
    ]
    result = process.run(args, cancel=ctx.cancel, timeout=LO_TIMEOUT,
                         error_message=t("error.libreoffice_failed"))
    produced = [p for p in outdir.iterdir() if p.is_file()]
    if not produced:
        raise ConversionError(t("error.libreoffice_failed"),
                              f"{result.stdout}\n{result.stderr_tail}".strip())
    shutil.move(str(produced[0]), str(output))
