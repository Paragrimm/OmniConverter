"""Previews: the real result where it is cheap, frames of the chosen part for videos."""

import threading

import numpy as np
import pytest
from PIL import Image

from omniconverter.core.converter import SourceFile
from omniconverter.core.errors import Cancelled, ConversionError
from omniconverter.core.formats import get_format
from tests.conftest import ffmpeg, needs_ffmpeg


def preview(converter, source, target, tmp_path, **options):
    work = tmp_path / "preview"
    work.mkdir(exist_ok=True)
    return converter.preview(source, get_format(target), options, work)


def colors(path):
    with Image.open(path) as im:
        return len(im.convert("RGB").getcolors(1 << 24))


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.png"
    Image.merge("RGB", [Image.effect_noise((120, 80), 60) for _ in range(3)]).save(path)
    return path


def test_image_preview_is_the_real_result(converter, photo, tmp_path):
    source = converter.inspect(photo)
    p = preview(converter, source, "jpg", tmp_path, quality=40)
    real = converter.convert(source, get_format("jpg"), tmp_path / "real.jpg", {"quality": 40})
    assert p.size_bytes == real.stat().st_size
    assert (p.width, p.height) == (120, 80) and len(p.frames) == 1 and not p.durations_ms
    with Image.open(p.frames[0]) as shown, Image.open(real) as im:
        assert shown.size == (120, 80)
        assert np.array_equal(np.asarray(shown.convert("RGB")), np.asarray(im))  # artifacts too
    with Image.open(p.original) as original, Image.open(photo) as im:
        assert np.array_equal(np.asarray(original.convert("RGB")), np.asarray(im))


def test_png_preview_shows_the_palette(converter, photo, tmp_path):
    source = converter.inspect(photo)
    few = preview(converter, source, "png", tmp_path, colors=8)
    assert colors(few.frames[0]) <= 8
    assert colors(few.original) > 1000  # the comparison keeps all colors
    all_colors = preview(converter, source, "png", tmp_path)
    assert few.size_bytes < all_colors.size_bytes


def test_resized_preview_and_original_match(converter, photo, tmp_path):
    p = preview(converter, converter.inspect(photo), "webp", tmp_path, resize="percent",
                percent=50)
    assert (p.width, p.height) == (60, 40)
    with Image.open(p.original) as original:
        assert original.size == (60, 40)  # compared at the same size


def test_animated_preview_has_frames_and_durations(converter, tmp_path):
    src = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (40, 30), c) for c in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=120, loop=0)
    p = preview(converter, converter.inspect(src), "webp", tmp_path)
    assert len(p.frames) == 3 and p.durations_ms == [120, 120, 120]


def test_pdf_preview_shows_the_page(converter, photo, tmp_path):
    p = preview(converter, converter.inspect(photo), "pdf", tmp_path)
    assert len(p.frames) == 1 and p.size_bytes > 0


def test_normal_map_preview(converter, photo, tmp_path):
    p = preview(converter, converter.inspect(photo), "normal-map", tmp_path, strength=50)
    with Image.open(p.frames[0]) as im:
        assert im.size == (120, 80)
    assert p.original is not None and p.size_bytes > 0


def test_large_noise_is_previewed_scaled_down_with_the_same_pattern(converter, tmp_path):
    noise = SourceFile.generator("noise")
    options = {"seed": 5, "width": 2048, "height": 1024, "scale": 512, "kind": "perlin"}
    p = preview(converter, noise, "png", tmp_path, **options)
    assert (p.width, p.height) == (2048, 1024) and p.size_bytes is None and p.note
    full = converter.convert(noise, get_format("png"), tmp_path / "full.png", options)
    with Image.open(p.frames[0]) as small, Image.open(full) as big:
        assert small.size == (1024, 512)
        shrunk = np.asarray(big.resize(small.size, Image.Resampling.BOX), dtype=float)
        assert np.corrcoef(shrunk.ravel(), np.asarray(small, dtype=float).ravel())[0, 1] > 0.98


def test_small_noise_preview_is_exact(converter, tmp_path):
    p = preview(converter, SourceFile.generator("noise"), "png", tmp_path, seed=5, width=64,
                height=32)
    assert (p.width, p.height) == (64, 32) and p.size_bytes > 0 and not p.note


def test_qr_svg_preview(converter, tmp_path):
    p = preview(converter, SourceFile.from_text("https://example.com"), "qr-svg", tmp_path)
    assert p.size_bytes > 0 and p.width is None  # a vector graphic has no pixel size
    with Image.open(p.frames[0]) as im:
        assert im.size[0] == im.size[1] > 100


def test_qr_preview_reports_empty_text(converter, tmp_path):
    with pytest.raises(ConversionError):
        preview(converter, SourceFile.from_text("   "), "qr-png", tmp_path)


def test_no_preview_for_audio_documents_and_data(converter, tmp_path):
    data = tmp_path / "a.json"
    data.write_text("[]")
    assert not converter.can_preview(converter.inspect(data), get_format("yaml"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")  # never read: the answer only depends on the formats
    source = SourceFile(wav, get_format("wav"))
    assert not converter.can_preview(source, get_format("mp3"))


def test_preview_can_be_cancelled(converter, photo, tmp_path):
    cancel = threading.Event()
    cancel.set()
    work = tmp_path / "w"
    work.mkdir()
    with pytest.raises(Cancelled):
        converter.preview(converter.inspect(photo), get_format("png"), {}, work, cancel=cancel)


# -- video ---------------------------------------------------------------------------------


@needs_ffmpeg
def test_video_preview_shows_only_the_chosen_part(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)  # 2 s at 25 fps, 320×240
    p = preview(converter, source, "webm", tmp_path, start=0.5, end=1.5, resolution=720)
    assert p.span == (0.5, 1.5)
    assert 13 <= len(p.frames) <= 16  # one second, real time at up to 15 fps
    assert p.timestamps[0] == 0.5 and all(0.5 <= t < 1.5 for t in p.timestamps)
    assert p.durations_ms == [67] * len(p.frames)
    assert (p.width, p.height) == (960, 720)  # the size of the real result
    with Image.open(p.frames[0]) as im:
        assert im.size == (320, 240)


@needs_ffmpeg
def test_long_parts_become_a_time_lapse_with_exact_ends(converter, tmp_path):
    video = tmp_path / "long.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=24:size=160x120:rate=10", "-g", "20",
           "-pix_fmt", "yuv420p", str(video))
    p = preview(converter, converter.inspect(video), "mp4", tmp_path, start=1, end=23)
    assert p.note and p.span == (1, 23)
    assert len(p.frames) <= 122 and p.frames[0].name.startswith("first")
    assert p.frames[-1].name.startswith("last")
    assert p.timestamps[0] == 1 and p.timestamps[-1] == pytest.approx(22.9)


@needs_ffmpeg
def test_gif_preview_is_the_real_gif(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)
    p = preview(converter, source, "gif", tmp_path, colors=16, width=160, fps=10)
    assert (p.width, p.height) == (160, 120) and p.size_bytes > 0 and not p.estimated
    assert len(p.frames) == 20 and p.durations_ms[0] == 100
    assert all(colors(f) <= 17 for f in p.frames[:3])  # 16 + the transparent color


@needs_ffmpeg
def test_invalid_cut_is_reported(converter, sample_video, tmp_path):
    with pytest.raises(ConversionError):
        preview(converter, converter.inspect(sample_video), "mp4", tmp_path, start=1.5, end=1)


@needs_ffmpeg
def test_no_preview_for_extracted_audio(converter, sample_video):
    assert not converter.can_preview(converter.inspect(sample_video), get_format("mp3"))
