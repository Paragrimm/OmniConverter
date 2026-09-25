import threading
from pathlib import Path

import pytest

from omniconverter.core.backend import Backend, Conversion
from omniconverter.core.converter import Converter, SourceFile, default_output_path, unique_path
from omniconverter.core.errors import Cancelled, ConversionError
from omniconverter.core.formats import get_format
from omniconverter.core.options import Kind, Option
from omniconverter.core.tools import ToolLocator


class Scripted(Backend):
    id = "scripted"

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.seen = None

    def conversions(self):
        yield Conversion("txt", "md")

    def options(self, source, target, media=None):
        return [Option("level", "L", Kind.INT, 1, minimum=0, maximum=9)]

    def convert(self, request, output: Path, ctx):
        self.seen = (request, output)
        ctx.progress(0.5)
        if self.behaviour == "partial-then-fail":
            output.write_text("half")
            raise ConversionError("boom", "details")
        if self.behaviour == "cancel":
            output.write_text("half")
            ctx.cancel.set()
            ctx.check_cancelled()
        output.write_text(f"level={request.options['level']}")


def make(tmp_path, behaviour="ok"):
    backend = Scripted(behaviour)
    conv = Converter(ToolLocator(), [backend])
    src = tmp_path / "in.txt"
    src.write_text("hello")
    return conv, backend, conv.inspect(src)


def leftovers(folder: Path):
    return sorted(p.name for p in folder.iterdir() if ".omni-" in p.name)


def test_convert_writes_atomically_and_reports_progress(tmp_path):
    conv, backend, source = make(tmp_path)
    seen = []
    out = conv.convert(source, get_format("md"), tmp_path / "out.md", {"level": "3"},
                       on_progress=seen.append)
    assert out.read_text() == "level=3"
    assert seen[0] == 0.0 and seen[-1] == 1.0 and 0.5 in seen
    _request, tmp_output = backend.seen
    assert tmp_output != out and tmp_output.parent == out.parent  # temp file next to target
    assert leftovers(tmp_path) == []


def test_failure_leaves_no_partial_file(tmp_path):
    conv, _b, source = make(tmp_path, "partial-then-fail")
    with pytest.raises(ConversionError) as err:
        conv.convert(source, get_format("md"), tmp_path / "out.md")
    assert err.value.details == "details"
    assert not (tmp_path / "out.md").exists()
    assert leftovers(tmp_path) == []


def test_cancel_leaves_no_file(tmp_path):
    conv, _b, source = make(tmp_path, "cancel")
    with pytest.raises(Cancelled):
        conv.convert(source, get_format("md"), tmp_path / "out.md", cancel=threading.Event())
    assert not (tmp_path / "out.md").exists()
    assert leftovers(tmp_path) == []


def test_refuses_to_overwrite_source(tmp_path):
    conv, _b, source = make(tmp_path)
    with pytest.raises(ConversionError):
        conv.convert(source, get_format("md"), source.path)


def test_unknown_options_rejected_unless_lenient(tmp_path):
    conv, _b, source = make(tmp_path)
    with pytest.raises(ConversionError):
        conv.convert(source, get_format("md"), tmp_path / "a.md", {"bogus": 1})
    out = conv.convert(source, get_format("md"), tmp_path / "b.md", {"bogus": 1}, lenient=True)
    assert out.exists()


def test_inspect_errors(tmp_path):
    conv = Converter(ToolLocator(), [])
    with pytest.raises(ConversionError):
        conv.inspect(tmp_path / "missing.mp4")
    (tmp_path / "file.xyz").write_text("x")
    with pytest.raises(ConversionError):
        conv.inspect(tmp_path / "file.xyz")


def test_default_output_path_never_overwrites(tmp_path):
    src = tmp_path / "video.mov"
    src.write_text("x")
    mp4 = get_format("mp4")
    assert default_output_path(src, mp4) == tmp_path / "video.mp4"
    (tmp_path / "video.mp4").write_text("x")
    assert default_output_path(src, mp4) == tmp_path / "video (1).mp4"
    (tmp_path / "video (1).mp4").write_text("x")
    assert default_output_path(src, mp4) == tmp_path / "video (2).mp4"
    # Same format as the source (e.g. just trimming): must not return the source itself.
    assert default_output_path(src, get_format("mov")) == tmp_path / "video (1).mov"
    other = tmp_path / "out"
    assert default_output_path(src, mp4, other) == other / "video.mp4"


def test_unique_path_keeps_free_names(tmp_path):
    assert unique_path(tmp_path / "free.txt") == tmp_path / "free.txt"


def test_derived_targets_get_a_suffix(tmp_path):
    src = tmp_path / "wall.jpg"
    src.write_text("x")
    assert default_output_path(src, get_format("normal-map")) == tmp_path / "wall_normal.png"
    assert default_output_path(src, get_format("qr-svg")) == tmp_path / "wall_qr.svg"


class Generator(Backend):
    id = "generator"

    def conversions(self):
        yield Conversion("noise", "png")

    def options(self, source, target, media=None):
        return [Option("seed", "Seed", Kind.INT, 7, minimum=0, maximum=99)]

    def output_stem(self, request):
        return f"made-{request.options['seed']}"

    def convert(self, request, output: Path, ctx):
        assert request.source is None
        output.write_text(str(request.options["seed"]))


def test_sources_without_a_file(tmp_path, monkeypatch):
    conv = Converter(ToolLocator(), [Generator()])
    source = SourceFile.generator("noise")
    assert source.name == "Noise-Map" and source.size == 0
    png = get_format("png")
    assert conv.output_path(source, png, {"seed": 3}, tmp_path) == tmp_path / "made-3.png"
    assert conv.output_path(source, png, {"seed": "bad"}, tmp_path) == tmp_path / "made-7.png"
    monkeypatch.chdir(tmp_path)
    assert conv.output_path(source, png) == tmp_path / "made-7.png"  # CLI: current folder
    out = conv.convert(source, png, tmp_path / "made-3.png", {"seed": 3})
    assert out.read_text() == "3"
    with pytest.raises(ValueError):
        SourceFile.generator("png")
    assert SourceFile.from_text("äb").size == 3


class WithCompanions(Scripted):
    def convert(self, request, output: Path, ctx):
        output.write_text("main")
        ctx.companions[f"{ctx.final_path.stem}.side"] = b"side"
        if self.behaviour == "bad-name":
            ctx.companions["../escape.txt"] = b"x"


def test_companion_files(tmp_path):
    conv = Converter(ToolLocator(), [WithCompanions("ok")])
    src = tmp_path / "in.txt"
    src.write_text("x")
    source = conv.inspect(src)
    out = conv.convert(source, get_format("md"), tmp_path / "out.md")
    assert out.read_text() == "main" and (tmp_path / "out.side").read_bytes() == b"side"

    (tmp_path / "again.side").write_text("keep me")  # never overwritten …
    with pytest.raises(ConversionError):
        conv.convert(source, get_format("md"), tmp_path / "again.md")
    assert (tmp_path / "again.side").read_text() == "keep me"
    assert not (tmp_path / "again.md").exists()  # … and then nothing is saved at all

    bad = Converter(ToolLocator(), [WithCompanions("bad-name")])
    with pytest.raises(ConversionError):
        bad.convert(source, get_format("md"), tmp_path / "bad.md")
    assert not (tmp_path.parent / "escape.txt").exists()
    assert leftovers(tmp_path) == []
