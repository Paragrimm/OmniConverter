import sys

import pytest

from omniconverter import runtime
from omniconverter.config import config_dir
from omniconverter.integration import launcher_command


@pytest.fixture
def frozen_app(tmp_path, monkeypatch):
    """Pretend to be a packaged build living in *tmp_path*."""
    exe = tmp_path / ("omniconvert.exe" if sys.platform == "win32" else "omniconvert")
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("OMNICONVERTER_CONFIG_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    return tmp_path


def test_source_checkout_is_not_frozen():
    assert not runtime.is_frozen()
    assert not runtime.is_portable()
    assert runtime.appimage_path() is None


def test_portable_marker_keeps_settings_next_to_the_app(frozen_app):
    assert config_dir() != frozen_app / "settings"
    (frozen_app / runtime.PORTABLE_MARKER).write_text("portable")
    assert runtime.is_portable()
    assert config_dir() == frozen_app / "settings"


def test_appimage_path_is_used_for_integration(frozen_app, monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/home/me/Apps/OmniConverter.AppImage")
    assert launcher_command() == ["/home/me/Apps/OmniConverter.AppImage"]


def test_frozen_launcher_prefers_gui_next_to_cli(frozen_app):
    gui = frozen_app / ("OmniConverter.exe" if sys.platform == "win32" else "OmniConverter")
    gui.write_text("")
    assert launcher_command() == [str(gui)]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux loader variables")
def test_child_env_restores_system_libraries(frozen_app, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = runtime.child_env()
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env

    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in runtime.child_env()
    # Extra variables survive (e.g. Pandoc's network block).
    assert runtime.child_env({"https_proxy": "x"})["https_proxy"] == "x"


def test_child_env_untouched_from_source(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/lib")
    assert runtime.child_env()["LD_LIBRARY_PATH"] == "/opt/lib"
