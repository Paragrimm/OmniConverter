import pytest

from omniconverter.core.errors import OptionError
from omniconverter.core.options import (
    Kind,
    Option,
    format_time,
    parse_bool,
    parse_time,
    resolve,
    when,
)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("90", 90.0),
        ("1:30", 90.0),
        ("0:01:30.5", 90.5),
        ("1:30,25", 90.25),
        ("1:00:00", 3600.0),
        (" 12.5 ", 12.5),
        ("", None),
        (None, None),
        (3, 3.0),
    ],
)
def test_parse_time(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["abc", "1:2:3:4", "-5", "1::2", "12s"])
def test_parse_time_rejects_garbage(text):
    with pytest.raises(OptionError):
        parse_time(text, "start")


@pytest.mark.parametrize("seconds", [0.0, 5.0, 90.5, 3725.125])
def test_format_time_roundtrip(seconds):
    assert parse_time(format_time(seconds)) == pytest.approx(seconds)


def test_format_time_style():
    assert format_time(90) == "1:30"
    assert format_time(3725.5) == "1:02:05.500"
    assert format_time(None) == ""


def test_parse_bool():
    assert parse_bool("ja") is True
    assert parse_bool("off") is False
    with pytest.raises(OptionError):
        parse_bool("maybe")


SCHEMA = [
    Option("quality", "Q", Kind.CHOICE, "medium",
           choices=(("high", "H"), ("medium", "M"), ("small", "S"))),
    Option("height", "H", Kind.CHOICE, "original",
           choices=(("original", "O"), (720, "720p"), (1080, "1080p"))),
    Option("colors", "C", Kind.INT, 256, minimum=2, maximum=256),
    Option("fast", "F", Kind.BOOL, False),
    Option("bg", "B", Kind.COLOR, "#ffffff"),
    Option("width", "W", Kind.INT, 640, visible_if=when("height", "custom")),
]


def test_resolve_fills_defaults():
    values = resolve(SCHEMA, {})
    assert values == {"quality": "medium", "height": "original", "colors": 256, "fast": False,
                      "bg": "#ffffff", "width": 640}


def test_resolve_parses_cli_strings():
    values = resolve(SCHEMA, {"quality": "HIGH", "height": "720", "colors": "64",
                              "fast": "yes", "bg": "#00FF00"})
    assert values["quality"] == "high"
    assert values["height"] == 720  # typed choice value, not the string
    assert values["colors"] == 64
    assert values["fast"] is True
    assert values["bg"] == "#00ff00"


@pytest.mark.parametrize(
    "raw", [{"colors": "1"}, {"colors": "999"}, {"quality": "ultra"}, {"bg": "red"},
            {"typo": "1"}],
)
def test_resolve_rejects_invalid(raw):
    with pytest.raises(OptionError):
        resolve(SCHEMA, raw)


def test_visible_if():
    width = SCHEMA[-1]
    assert not width.is_visible({"height": "original"})
    assert width.is_visible({"height": "custom"})
