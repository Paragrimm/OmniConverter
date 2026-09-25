"""GUI flows with pytest-qt (runs headless with QT_QPA_PLATFORM=offscreen)."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QToolButton

from omniconverter.config import Settings
from omniconverter.core.options import Kind, Option, when
from omniconverter.gui.main_window import MainWindow
from omniconverter.gui.options_form import OptionsForm
from omniconverter.gui.single_instance import SingleInstance
from tests.conftest import ffmpeg, needs_ffmpeg

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


def test_back_to_options_after_export_tries_another_format(window, qtbot, tmp_path):
    src = tmp_path / "picture.png"
    Image.new("RGB", (16, 16), "teal").save(src)
    window.open_files([str(src)])
    target_button(window, "jpg").click()
    window.config_page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    result = window.result_page
    assert result.again_button.isVisibleTo(result)

    result.again_button.click()  # same file, same choices – no need to open it again
    page = window.config_page
    assert window.stack.currentWidget() is page
    assert [s.path for s in page.sources] == [src]
    assert page.target.id == "jpg" and target_button(window, "jpg").isChecked()
    assert page.output_label.toolTip() == str(tmp_path / "picture (1).jpg")

    target_button(window, "webp").click()
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    assert window.result_page.outputs == [tmp_path / "picture.webp"]
    assert (tmp_path / "picture.jpg").is_file()


def test_back_to_options_never_overwrites_a_chosen_file(window, qtbot, tmp_path):
    src = tmp_path / "picture.png"
    Image.new("RGB", (16, 16), "teal").save(src)
    window.open_files([str(src)])
    target_button(window, "jpg").click()
    page = window.config_page
    page.custom_output = tmp_path / "out" / "mine.jpg"
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    window.result_page.again_button.click()
    assert page.custom_output == tmp_path / "out" / "mine (1).jpg"
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["mine (1).jpg", "mine.jpg"]


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
    # no celebrating owl on errors
    assert page.icon.isVisibleTo(page) and not page.emote.isVisibleTo(page)
    assert not page.credit.isVisibleTo(page)


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


_CLIENT = """
import sys
from PySide6.QtCore import QCoreApplication
from omniconverter.gui.single_instance import forward
app = QCoreApplication([])
sys.exit(0 if forward(sys.argv[1], sys.argv[2:]) else 3)
"""


def test_single_instance_forwards_files(qtbot, tmp_path):
    # The second launch is a real separate process, as when Explorer starts one per file.
    name = f"omniconverter-test-{uuid.uuid4().hex[:8]}"
    primary = SingleInstance(name)
    assert primary.acquire_or_forward([]) is True
    files = [str(tmp_path / "x.mp4"), str(tmp_path / "ü ber.png")]
    try:
        with qtbot.waitSignal(primary.files_received, timeout=10000) as blocker:
            client = subprocess.Popen([sys.executable, "-c", _CLIENT, name, *files])
        qtbot.waitUntil(lambda: client.poll() is not None, timeout=10000)  # keep serving
        assert client.returncode == 0
        assert blocker.args[0] == [str(Path(f).resolve()) for f in files]
    finally:
        primary.close()


def test_forward_without_primary_returns_false():
    from omniconverter.gui.single_instance import forward

    assert forward(f"omniconverter-none-{uuid.uuid4().hex[:8]}", ["x"]) is False


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


@pytest.fixture
def pictures(tmp_path, monkeypatch):
    """Generated results (QR codes, noise) go to the pictures folder by default."""
    folder = tmp_path / "Pictures"
    folder.mkdir()
    monkeypatch.setattr("omniconverter.gui.main_window.generated_output_dir", lambda: folder)
    return folder


def test_owls_while_cooking_and_when_done(window, qtbot, tmp_path):
    progress = window.progress_page
    assert progress.emote.is_valid()
    assert progress.emote.movie_.fileName().endswith("gif_owly_cook_slow.gif")
    assert window.result_page.emote.movie_.fileName().endswith("gif_owly_nerd.gif")
    for page in (progress, window.result_page):
        assert page.credit.text() == (
            'Emotes by <a href="https://roamingowl.itch.io/owlish-emotes">RoamingOwl</a>')
        assert page.credit.openExternalLinks()

    src = tmp_path / "a.json"
    src.write_text('[{"x": 1}]')
    window.open_files([str(src)])
    target_button(window, "yaml").click()
    window.config_page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    page = window.result_page
    assert page.emote.isVisible() and page.credit.isVisible()
    assert not page.icon.isVisible()
    qtbot.waitUntil(lambda: page.emote.pixmap() is not None and not page.emote.pixmap().isNull())


def test_qr_code_from_typed_link(window, qtbot, pictures):
    drop = window.drop_page
    assert not drop.qr_button.isEnabled()
    qtbot.keyClicks(drop.qr_text, "https://example.com")
    assert drop.qr_button.isEnabled()
    drop.qr_button.click()
    page = window.config_page
    assert window.stack.currentWidget() is page
    assert page.text_edit.isVisible()
    assert page.text_edit.toPlainText() == "https://example.com"
    assert page.subtitle.text() == "19 bytes"
    assert {b.property("format_id") for b in page.group.buttons()} == {"qr-png", "qr-svg"}

    target_button(window, "qr-png").click()
    assert page.output_label.toolTip() == str(pictures / "qr-code.png")
    page.text_edit.setPlainText("   ")
    assert not page.convert_button.isEnabled()  # nothing to encode
    page.text_edit.setPlainText("https://example.org/owl")
    assert page.convert_button.isEnabled() and page.subtitle.text() == "23 bytes"
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    assert window.result_page.outputs == [pictures / "qr-code.png"]
    assert window.result_page.again_button.isVisibleTo(window.result_page)


def test_noise_map_with_dice(window, qtbot, pictures):
    window.drop_page.noise_button.click()
    page = window.config_page
    assert page.title.text() == "Noise-Map" and not page.text_edit.isVisible()
    target_button(window, "png").click()
    for key, value in (("width", 48), ("height", 32), ("scale", 16)):
        page.form.widget(key).setValue(value)
    seed = page.form.widget("seed")
    seed.setValue(1234)
    assert page.output_label.toolTip() == str(pictures / "noise-1234.png")
    dice = page.form.findChild(QToolButton, "random_seed")
    for _ in range(5):  # a new seed (five tries, so a repeated roll cannot fail the test)
        dice.click()
        if seed.value() != 1234:
            break
    assert seed.value() != 1234
    assert page.output_label.toolTip() == str(pictures / f"noise-{seed.value()}.png")
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=10000)
    (out,) = window.result_page.outputs
    assert out == pictures / f"noise-{seed.value()}.png"
    with Image.open(out) as im:
        assert im.size == (48, 32)


def test_dropped_links_and_text():
    from PySide6.QtCore import QMimeData, QUrl

    from omniconverter.gui.widgets import dropped_text, local_paths

    link = QMimeData()
    link.setUrls([QUrl("https://example.com/a")])
    assert dropped_text(link) == "https://example.com/a" and local_paths(link) == []
    text = QMimeData()
    text.setText("  hello owl ")
    assert dropped_text(text) == "hello owl"
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile("/tmp/x.png")])
    assert dropped_text(files) == "" and local_paths(files) == ["/tmp/x.png"]


def run_batch(window, qtbot, files, target):
    window.open_files([str(f) for f in files])
    page = window.config_page
    assert len(page.sources) == len(files)
    target_button(window, target).click()
    page.convert_button.click()
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.result_page, timeout=60000)
    return window.result_page


def test_batch_of_mixed_image_formats(window, qtbot, tmp_path):
    files = []
    for name in ("a.png", "b.jpg", "c.bmp"):
        Image.new("RGB", (8, 8), "teal").save(tmp_path / name)
        files.append(tmp_path / name)
    result = run_batch(window, qtbot, files, "webp")
    assert sorted(p.name for p in result.outputs) == ["a.webp", "b.webp", "c.webp"]


@needs_ffmpeg
def test_batch_of_mixed_audio_formats(window, qtbot, tmp_path):
    files = []
    for name in ("a.wav", "b.flac", "c.ogg"):
        ffmpeg("-f", "lavfi", "-i", "sine=duration=0.5", str(tmp_path / name))
        files.append(tmp_path / name)
    result = run_batch(window, qtbot, files, "mp3")
    assert sorted(p.name for p in result.outputs) == ["a.mp3", "b.mp3", "c.mp3"]
    assert "3 files" in result.message.text()
