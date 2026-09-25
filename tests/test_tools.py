import stat
import sys

import pytest

from omniconverter.core.errors import ToolMissingError
from omniconverter.core.tools import TOOLS, ToolLocator, env_var_name, install_hint


def fake_exe(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_override_beats_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    exe = fake_exe(tmp_path / "my-ffmpeg")
    locator = ToolLocator({"ffmpeg": str(exe)})
    assert locator.find("ffmpeg") == str(exe)
    locator.set_override("ffmpeg", None)
    assert locator.find("ffmpeg") is None


def test_env_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    exe = fake_exe(tmp_path / "pandoc-custom")
    monkeypatch.setenv(env_var_name("pandoc"), str(exe))
    assert ToolLocator().find("pandoc") == str(exe)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable names")
def test_ffprobe_next_to_custom_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    ffmpeg = fake_exe(tmp_path / "ffmpeg")
    ffprobe = fake_exe(tmp_path / "ffprobe")
    locator = ToolLocator({"ffmpeg": str(ffmpeg)})
    assert locator.find("ffprobe") == str(ffprobe)


def test_found_on_path(tmp_path, monkeypatch):
    name = "soffice.exe" if sys.platform == "win32" else "soffice"
    fake_exe(tmp_path / name)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert ToolLocator().find("soffice") == str(tmp_path / name)


def test_missing_tool(monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv(env_var_name("ffmpeg"), raising=False)
    locator = ToolLocator()
    if sys.platform == "win32" and locator.find("ffmpeg"):
        pytest.skip("ffmpeg installed in a well-known Windows location")
    with pytest.raises(ToolMissingError) as err:
        locator.require("ffmpeg")
    assert "FFmpeg" in err.value.message


def test_rescan_clears_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv(env_var_name("pandoc"), raising=False)
    locator = ToolLocator()
    if locator.find("pandoc") is not None:
        pytest.skip("pandoc installed in a well-known location")
    name = "pandoc.exe" if sys.platform == "win32" else "pandoc"
    fake_exe(tmp_path / name)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert locator.find("pandoc") is None  # cached
    locator.rescan()
    assert locator.find("pandoc") == str(tmp_path / name)


def test_install_hints_mention_package():
    for tool_id, spec in TOOLS.items():
        hint = install_hint(tool_id)
        expected = spec.winget if sys.platform == "win32" else spec.linux_package
        assert expected in hint
