import re
import string
from pathlib import Path

import pytest

import omniconverter
from omniconverter.i18n import MESSAGES, current_language, set_language, system_language, t

SRC = Path(omniconverter.__file__).parent


def used_keys():
    keys = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys |= set(re.findall(r"\bt\(\s*[\"']([a-z_.]+)[\"']", text))
        keys |= set(re.findall(r"MESSAGES\[\"([a-z_.]+)\"\]", text))
    return keys


def test_every_used_key_is_translated():
    missing = sorted(k for k in used_keys() if k not in MESSAGES)
    assert missing == []


def test_translations_complete_and_placeholders_match():
    fmt = string.Formatter()
    for key, (de, en) in MESSAGES.items():
        assert de.strip() and en.strip(), key
        names = lambda s: {f for _, f, _, _ in fmt.parse(s) if f}  # noqa: E731
        assert names(de) == names(en), key


def test_language_switch():
    set_language("de")
    assert t("gui.convert") == "Umwandeln"
    assert t("error.not_a_file", path="x") == "Datei nicht gefunden: x"
    set_language("en")
    assert t("gui.convert") == "Convert"
    assert t("does.not.exist") == "does.not.exist"


@pytest.mark.parametrize(("env", "lang"), [
    ({"LANG": "de_DE.UTF-8"}, "de"),
    ({"LANG": "en_GB.UTF-8"}, "en"),
    ({"LC_ALL": "de_AT.UTF-8", "LANG": "en_US.UTF-8"}, "de"),
])
def test_system_language(monkeypatch, env, lang):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert system_language() == lang
    set_language(None)
    assert current_language() == lang
