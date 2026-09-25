"""Real conversions through FFmpeg (skipped when FFmpeg is not installed)."""

import threading
import time

import pytest

from omniconverter.core.errors import Cancelled
from omniconverter.core.formats import get_format
from tests.conftest import ffmpeg, ffprobe_json, measure_lufs, needs_ffmpeg

pytestmark = needs_ffmpeg


def streams(path, kind):
    return [s for s in ffprobe_json(path)["streams"] if s["codec_type"] == kind]


def test_inspect_video(converter, sample_video):
    source = converter.inspect(sample_video)
    assert source.format.id == "mp4"
    assert source.media.has_video and source.media.has_audio
    assert source.media.width == 320 and source.media.duration == pytest.approx(2, abs=0.1)


def test_video_to_gif_with_options(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)
    out = converter.convert(source, get_format("gif"), tmp_path / "clip.gif",
                            {"start": "0.5", "end": "1.5", "fps": "10", "width": "160",
                             "colors": "32"})
    (video,) = streams(out, "video")
    assert video["codec_name"] == "gif"
    assert int(video["width"]) == 160
    assert float(ffprobe_json(out)["format"]["duration"]) == pytest.approx(1.0, abs=0.15)


def test_video_to_webm_scaled(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)
    progress = []
    out = converter.convert(source, get_format("webm"), tmp_path / "x.webm",
                            {"resolution": "360", "quality": "small"}, on_progress=progress.append)
    (video,) = streams(out, "video")
    assert video["codec_name"] == "vp9" and int(video["height"]) == 360
    assert streams(out, "audio")[0]["codec_name"] == "opus"
    assert progress[-1] == 1.0 and len(progress) > 2


def test_fast_remux_keeps_codecs(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)
    out = converter.convert(source, get_format("mkv"), tmp_path / "x.mkv", {"fast": "yes"})
    assert streams(out, "video")[0]["codec_name"] == "h264"


def test_fast_mode_falls_back_to_reencoding(converter, sample_video, tmp_path):
    # H.264 cannot be copied into WebM, so the stream copy fails and we re-encode.
    source = converter.inspect(sample_video)
    out = converter.convert(source, get_format("webm"), tmp_path / "x.webm", {"fast": "yes"})
    assert streams(out, "video")[0]["codec_name"] == "vp9"


def test_extract_audio_normalized(converter, sample_video, tmp_path):
    source = converter.inspect(sample_video)
    out = converter.convert(source, get_format("mp3"), tmp_path / "x.mp3",
                            {"normalize": "podcast"})
    assert streams(out, "video") == []
    assert measure_lufs(out) == pytest.approx(-16, abs=1.0)


@pytest.mark.parametrize(("target", "codec"), [
    ("flac", "flac"), ("opus", "opus"), ("ogg", "vorbis"), ("m4a", "aac"), ("wav", "pcm_s16le"),
])
def test_audio_formats(converter, sample_audio, tmp_path, target, codec):
    source = converter.inspect(sample_audio)
    out = converter.convert(source, get_format(target), tmp_path / f"x.{target}")
    assert streams(out, "audio")[0]["codec_name"] == codec


def test_audio_normalization_hits_target(converter, sample_audio, tmp_path):
    source = converter.inspect(sample_audio)
    assert measure_lufs(sample_audio) < -30
    out = converter.convert(source, get_format("wav"), tmp_path / "loud.wav",
                            {"normalize": "streaming"})
    assert measure_lufs(out) == pytest.approx(-14, abs=1.0)
    assert int(streams(out, "audio")[0]["sample_rate"]) == 44100  # not loudnorm's 192 kHz


def test_audio_trim_and_fade(converter, sample_audio, tmp_path):
    source = converter.inspect(sample_audio)
    out = converter.convert(source, get_format("mp3"), tmp_path / "cut.mp3",
                            {"start": "0.5", "end": "2", "fade_out": "1"})
    assert float(ffprobe_json(out)["format"]["duration"]) == pytest.approx(1.5, abs=0.1)


def test_odd_sized_gif_to_mp4(converter, tmp_path):
    gif = tmp_path / "odd.gif"
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=1:size=101x77:rate=10", str(gif))
    source = converter.inspect(gif)
    out = converter.convert(source, get_format("mp4"), tmp_path / "odd.mp4")
    (video,) = streams(out, "video")
    assert (int(video["width"]), int(video["height"])) == (100, 76)


def test_transparent_gif_to_webm_keeps_alpha(converter, tmp_path):
    from PIL import Image

    gif = tmp_path / "owl.gif"
    frames = []
    for i in range(4):
        frame = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
        frame.paste((255, 200, 0, 255), (5 + i * 5, 5, 20 + i * 5, 25))
        frames.append(frame)
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0,
                   disposal=2)
    source = converter.inspect(gif)
    out = converter.convert(source, get_format("webm"), tmp_path / "owl.webm")
    (video,) = streams(out, "video")
    assert video["codec_name"] == "vp9" and video["tags"].get("alpha_mode") == "1"
    # Decode with libvpx, which reads the alpha plane, and look at a corner and the square.
    png = tmp_path / "frame.png"
    ffmpeg("-c:v", "libvpx-vp9", "-i", str(out), "-frames:v", "1", str(png))
    with Image.open(png) as im:
        rgba = im.convert("RGBA")
        assert rgba.getpixel((1, 1))[3] < 16
        assert rgba.getpixel((12, 15))[3] > 240


def test_audio_only_mp4_offers_only_audio_targets(converter, tmp_path):
    m4 = tmp_path / "voice.mp4"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(m4))
    ids = {c.format.id for c in converter.targets([converter.inspect(m4)])}
    assert "mp3" in ids and "gif" not in ids and "webm" not in ids


def test_cancel_stops_ffmpeg_and_leaves_nothing(converter, tmp_path):
    long_video = tmp_path / "long.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=duration=40:size=1280x720:rate=30",
           "-c:v", "libx264", "-preset", "ultrafast", str(long_video))
    source = converter.inspect(long_video)
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        converter.convert(source, get_format("webm"), tmp_path / "out.webm",
                          {"quality": "high"}, cancel=cancel)
    assert time.monotonic() - started < 15
    assert not (tmp_path / "out.webm").exists()
    assert not [p for p in tmp_path.iterdir() if ".omni-" in p.name]
