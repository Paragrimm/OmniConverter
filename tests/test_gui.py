"""GUI flows with pytest-qt (runs headless with QT_QPA_PLATFORM=offscreen)."""

import uuid

import pytest
from PIL import Image

pytest.importorskip("PySide6.QtWidgets")

from omniconverter.config import Settings
from omniconverter.core.options import Kind, Option, when
from omniconverter.gui.main_window import MainWindow
from omniconverter.gui.options_form import OptionsForm
from omniconverter.gui.single_instance import SingleInstance

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, converter):
    w = MainWindow(converter, Settings())
    qtbot.addWidget(w)
    w.show()
    return w


def target_button(window, fmt_id):
    for button in window.config_page.group.buttons():
        if button.property("format_id") == fmt_id:
            return button
    raise AssertionError(f"no button for {fmt_id}")


def test_starts_with_drop_area(window):
    assert window.stack.currentWidget() is window.drop_page
    assert window.drop_page.drop.acceptDrops()


def test_png_to_jpg_end_to_end(window, qtbot, tmp_path):
    src = tmp_path / "picture.png"
    Image.new("RGBA", (64, 32), (0, 0, 255, 128)).save(src)
    window.open_files([str(src)])
    page = window.config_page
    assert window.stack.currentWidget() is page
    assert page.title.text() == "picture.png"
    assert not page.convert_button.isEnabled()  # nothing chosen yet

    target_button(window, "jpg").click()
    assert page.convert_button.isEnabled()
    assert page.output_label.toolTip() == str(tmp_path / "picture.jpg")
    page.form.widget("quality").setValue(50)

    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    assert window.result_page.outputs == [tmp_path / "picture.jpg"]
    with Image.open(tmp_path / "picture.jpg") as im:
        assert im.mode == "RGB" and im.size == (64, 32)


def test_unsupported_file_shows_error(window, tmp_path):
    bad = tmp_path / "file.xyz"
    bad.write_text("?")
    window.open_files([str(bad)])
    assert window.stack.currentWidget() is window.drop_page
    assert "file.xyz" in window.drop_page.error.text()


def test_multiple_files_share_targets_and_merge(window, tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.yaml"
    a.write_text('[{"x": 1}]')
    b.write_text("- x: 2\n")
    window.open_files([str(a)])
    window.open_files([str(b)])  # arrives right after: merged, like an Explorer multi-select
    page = window.config_page
    assert len(page.sources) == 2
    ids = {btn.property("format_id") for btn in page.group.buttons()}
    # json→json and yaml→yaml are not offered, so only the common targets remain
    assert ids == {"csv", "tsv", "xlsx", "toml"}
    assert page.output_label.text()  # "next to the originals"


def test_conversion_error_is_shown(window, qtbot, tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{nope")
    window.open_files([str(bad)])
    target_button(window, "yaml").click()
    window.config_page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    page = window.result_page
    assert page.again_button.isVisibleTo(page)
    assert not page.open_button.isVisibleTo(page)
    assert "broken.json" in page.message.text()


def test_options_form_visibility_and_validation(qtbot):
    options = [
        Option("resolution", "Resolution", Kind.CHOICE, "original",
               choices=(("original", "Original"), ("custom", "Custom"))),
        Option("width", "Width", Kind.INT, 640, minimum=16, maximum=4000,
               visible_if=when("resolution", "custom")),
        Option("start", "Start", Kind.TIME, None),
        Option("fast", "Fast", Kind.BOOL, False, advanced=True),
    ]
    form = OptionsForm(options)
    qtbot.addWidget(form)
    form.show()
    width = form.widget("width")
    assert not width.isVisible()
    form.widget("resolution").setCurrentIndex(1)
    assert width.isVisible()

    form.widget("start").setText("1:3x")
    assert not form.is_valid()
    form.widget("start").setText("1:30")
    assert form.is_valid()
    assert form.conversion_values() == {"resolution": "custom", "width": 640, "start": 90.0,
                                        "fast": False}
    assert not form.widget("fast").isVisible()  # hidden in the collapsed "Advanced" section


def test_single_instance_forwards_files(qtbot, tmp_path):
    name = f"omniconverter-test-{uuid.uuid4().hex[:8]}"
    primary = SingleInstance(name)
    assert primary.acquire_or_forward([]) is True
    second = SingleInstance(name)
    with qtbot.waitSignal(primary.files_received, timeout=5000) as blocker:
        assert second.acquire_or_forward([str(tmp_path / "x.mp4")]) is False
    assert blocker.args[0] == [str((tmp_path / "x.mp4").resolve())]


def test_settings_dialog_tools_and_context_menu(qtbot, converter, tmp_path, monkeypatch):
    from omniconverter.gui.settings_dialog import SettingsDialog
    from omniconverter.integration import linux

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(linux, "_refresh", lambda _dir: None)
    monkeypatch.setattr("sys.platform", "linux")
    settings = Settings()
    dialog = SettingsDialog(settings, converter.locator)
    qtbot.addWidget(dialog)
    assert dialog.tools_grid.rowCount() >= 4

    assert dialog.menu_button.text() == "Install"
    dialog.menu_button.click()
    assert linux.is_installed()
    assert dialog.menu_button.text() == "Remove"
    dialog.menu_button.click()
    assert not linux.is_installed()

    fake = tmp_path / "ffmpeg-custom"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    dialog._set_tool("ffmpeg", str(fake))
    assert converter.locator.find("ffmpeg") == str(fake)
    dialog.language.setCurrentIndex(dialog.language.findData("de"))
    dialog.accept()
    saved = Settings.load()
    assert saved.language == "de" and saved.tool_paths == {"ffmpeg": str(fake)}
