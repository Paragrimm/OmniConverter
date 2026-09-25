from pathlib import Path

import pytest

from omniconverter.core.backend import Backend, Conversion
from omniconverter.core.errors import ToolMissingError, UnsupportedConversion
from omniconverter.core.formats import get_format
from omniconverter.core.probe import MediaInfo
from omniconverter.core.registry import Registry


class FakeLocator:
    def __init__(self, installed=()):
        self.installed = set(installed)

    def available(self, tool_id):
        return tool_id in self.installed


class Fake(Backend):
    def __init__(self, id_, pairs, requires=(), priority=50, audio_only_ok=True):
        self.id = id_
        self._pairs = pairs
        self._requires = requires
        self._priority = priority
        self._audio_only_ok = audio_only_ok

    def conversions(self):
        for s, d in self._pairs:
            yield Conversion(s, d, self._requires, self._priority)

    def supports(self, conversion, media):
        return self._audio_only_ok or media is None or media.has_video

    def convert(self, request, output: Path, ctx):
        output.write_text(self.id)


def fmt(x):
    return get_format(x)


def test_highest_available_priority_wins():
    fast = Fake("fast", [("docx", "pdf")], requires=("soffice",), priority=70)
    slow = Fake("slow", [("docx", "pdf")], requires=("pandoc",), priority=40)
    reg = Registry([slow, fast], FakeLocator({"soffice", "pandoc"}))
    assert reg.resolve(fmt("docx"), fmt("pdf"))[0] is fast

    reg = Registry([slow, fast], FakeLocator({"pandoc"}))
    assert reg.resolve(fmt("docx"), fmt("pdf"))[0] is slow


def test_missing_tools_are_reported():
    b = Fake("ff", [("mp4", "gif"), ("mp4", "mp3")], requires=("ffmpeg",))
    reg = Registry([b], FakeLocator())
    choices = reg.targets(fmt("mp4"))
    assert {c.format.id for c in choices} == {"gif", "mp3"}
    assert all(not c.available and c.missing_tools == ("ffmpeg",) for c in choices)
    with pytest.raises(ToolMissingError):
        reg.resolve(fmt("mp4"), fmt("gif"))
    with pytest.raises(UnsupportedConversion):
        reg.resolve(fmt("mp4"), fmt("docx"))


def test_media_info_filters_targets():
    b = Fake("ff", [("mp4", "gif")], audio_only_ok=False)
    reg = Registry([b], FakeLocator())
    assert reg.targets(fmt("mp4"), MediaInfo(has_video=False, has_audio=True)) == []
    assert len(reg.targets(fmt("mp4"), MediaInfo(has_video=True))) == 1


def test_common_targets_is_intersection():
    b = Fake("img", [("png", "jpg"), ("png", "webp"), ("jpg", "webp"), ("jpg", "png")])
    reg = Registry([b], FakeLocator())
    common = reg.common_targets([(fmt("png"), None), (fmt("jpg"), None)])
    assert [c.format.id for c in common] == ["webp"]


def test_targets_sorted_by_category_then_format_order():
    b = Fake("x", [("mp4", "mp3"), ("mp4", "gif"), ("mp4", "webm"), ("mp4", "mkv")])
    reg = Registry([b], FakeLocator())
    assert [c.format.id for c in reg.targets(fmt("mp4"))] == ["mkv", "webm", "mp3", "gif"]


def test_real_registry_has_sensible_targets(converter):
    ids = {c.format.id for c in converter.registry.targets(fmt("mov"))}
    assert {"mp4", "gif", "mp3", "webm"} <= ids
    ids = {c.format.id for c in converter.registry.targets(fmt("png"))}
    assert {"jpg", "webp", "ico", "pdf", "avif"} <= ids
    ids = {c.format.id for c in converter.registry.targets(fmt("md"))}
    assert {"docx", "html", "pdf"} <= ids
    ids = {c.format.id for c in converter.registry.targets(fmt("csv"))}
    assert {"xlsx", "json", "yaml"} <= ids
