import threading
from pathlib import Path

import pytest

from omniconverter.core.backend import Backend, Conversion
from omniconverter.core.converter import Converter, default_output_path, unique_path
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
