"""FFmpeg command construction – no FFmpeg needed."""

import pytest

from omniconverter.backends import ffmpeg_args as fa
from omniconverter.core.errors import ConversionError
from omniconverter.core.probe import MediaInfo, parse_probe

MEDIA = MediaInfo(duration=10.0, has_video=True, has_audio=True, width=1920, height=1080,
                  sample_rate=44100)
ENCODERS = {"libx264", "libvpx-vp9", "aac", "libopus", "libmp3lame", "libvorbis", "flac",
            "pcm_s16le", "pcm_s16be", "mpeg4"}


def after(args, flag):
    return args[args.index(flag) + 1]


def test_trim_uses_input_seek_and_duration():
    tr = fa.trim(2.5, 7.0, 10.0)
    assert tr.input_args == ["-ss", "2.5"]
    assert tr.output_args == ["-t", "4.5"]
    assert tr.duration == pytest.approx(4.5)


def test_trim_open_ended_and_untouched():
    assert fa.trim(None, None, 10.0).input_args == []
    assert fa.trim(None, None, 10.0).duration == 10.0
    tr = fa.trim(3, None, 10.0)
    assert tr.output_args == [] and tr.duration == 7.0
    assert fa.trim(None, 12, 10.0).output_args == []  # end beyond the file: no -t


@pytest.mark.parametrize(("start", "end"), [(5, 5), (6, 2), (11, None)])
def test_trim_rejects_bad_ranges(start, end):
    with pytest.raises(ConversionError):
        fa.trim(start, end, 10.0)


def test_video_reencode_defaults():
    args = fa.build_video("ffmpeg", "in.mov", "out.mp4", "mp4",
                          {"quality": "medium", "resolution": "original", "fps": "original"},
                          MEDIA, encoders=ENCODERS)
    assert args[0] == "ffmpeg" and args[-1] == "out.mp4"
    assert after(args, "-protocol_whitelist") == "file,pipe"
    assert "-nostdin" in args
    assert after(args, "-c:v") == "libx264" and after(args, "-crf") == "23"
    assert after(args, "-pix_fmt") == "yuv420p"
    assert after(args, "-c:a") == "aac"
    assert after(args, "-movflags") == "+faststart"
    assert "-vf" not in args  # even dimensions, nothing to filter


def test_video_scaling_fps_and_odd_dimensions():
    args = fa.build_video("ffmpeg", "i", "o.webm", "webm",
                          {"resolution": 720, "fps": 30, "quality": "small"}, MEDIA,
                          encoders=ENCODERS)
    assert after(args, "-vf") == "fps=30,scale=-2:720:flags=lanczos"
    assert after(args, "-c:v") == "libvpx-vp9" and after(args, "-b:v") == "0"
    assert after(args, "-c:a") == "libopus"

    odd = MediaInfo(duration=3, has_video=True, width=321, height=241)
    args = fa.build_video("ffmpeg", "i", "o.mp4", "mp4", {}, odd, encoders=ENCODERS)
    assert after(args, "-vf") == "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    assert "-an" in args  # the source has no audio

    args = fa.build_video("ffmpeg", "i", "o.mp4", "mp4",
                          {"resolution": "custom", "width": 1000}, MEDIA, encoders=ENCODERS)
    assert after(args, "-vf") == "scale=1000:-2:flags=lanczos"


def test_video_fast_mode_copies_streams():
    args = fa.build_video("ffmpeg", "i", "o.mkv", "mkv",
                          {"fast": True, "resolution": 720, "start": 1, "end": 3}, MEDIA)
    assert after(args, "-c") == "copy"
    assert "-vf" not in args and "-c:v" not in args
    assert args[args.index("-i") - 2:args.index("-i")] == ["-ss", "1"]


def test_video_remove_audio_and_strip_metadata():
    args = fa.build_video("ffmpeg", "i", "o.mp4", "mp4",
                          {"remove_audio": True, "strip_metadata": True}, MEDIA)
    assert "-an" in args and "-c:a" not in args
    assert after(args, "-map_metadata") == "-1" and after(args, "-map_chapters") == "-1"


def test_encoder_fallback_without_libx264():
    args = fa.build_video("ffmpeg", "i", "o.mp4", "mp4", {"quality": "high"}, MEDIA,
                          encoders={"libopenh264", "aac"})
    assert after(args, "-c:v") == "libopenh264" and after(args, "-b:v") == "8M"
    assert fa.pick_encoder(("a", "b"), {"b"}) == "b"
    assert fa.pick_encoder(("a", "b"), set()) == "a"


def test_audio_args():
    args = fa.build_audio("ffmpeg", "in.flac", "out.mp3", "mp3",
                          {"bitrate": 320, "channels": "mono", "sample_rate": 48000},
                          MEDIA, encoders=ENCODERS)
    assert after(args, "-c:a") == "libmp3lame" and after(args, "-b:a") == "320k"
    assert after(args, "-ac") == "1" and after(args, "-ar") == "48000"
    assert "-vn" in args
    args = fa.build_audio("ffmpeg", "i", "o.opus", "opus", {"bitrate": 96}, MEDIA,
                          encoders=ENCODERS)
    assert after(args, "-ar") == "48000"  # Opus only knows 48 kHz
    args = fa.build_audio("ffmpeg", "i", "o.flac", "flac", {"flac_level": 8}, MEDIA)
    assert after(args, "-compression_level") == "8" and "-b:a" not in args


def test_audio_keeps_cover_art_when_asked():
    args = fa.build_audio("ffmpeg", "i.flac", "o.mp3", "mp3", {}, MEDIA, keep_cover=True)
    assert "attached_pic" in args and "-vn" not in args


def test_fades_and_normalization_filters():
    measured = {"input_i": "-30.1", "input_tp": "-10.0", "input_lra": "2.0",
                "input_thresh": "-40.0", "target_offset": "0.3"}
    args = fa.build_audio("ffmpeg", "i", "o.mp3", "mp3",
                          {"normalize": "podcast", "fade_in": 2, "fade_out": 3, "end": 8},
                          MEDIA, measured=measured)
    chain = after(args, "-af").split(",")
    assert chain[0].startswith("loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-30.1")
    assert "linear=true" in chain[0]
    assert chain[1] == "afade=t=in:st=0:d=2"
    assert chain[2] == "afade=t=out:st=5:d=3"  # 8 s output – 3 s fade
    assert after(args, "-ar") == "44100"  # back from loudnorm's internal 192 kHz


def test_loudnorm_measure_command():
    args = fa.build_loudnorm_measure("ffmpeg", "in.wav", {"normalize": "streaming"}, MEDIA)
    assert after(args, "-af") == "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json"
    assert args[-3:] == ["-f", "null", "-"]


def test_parse_loudnorm():
    stderr = """[Parsed_loudnorm_0 @ 0x55]
{
\t"input_i" : "-27.61",
\t"input_tp" : "-4.47",
\t"input_lra" : "0.00",
\t"input_thresh" : "-37.61",
\t"output_i" : "-16.00",
\t"target_offset" : "0.01"
}"""
    assert fa.parse_loudnorm(stderr) == {"input_i": "-27.61", "input_tp": "-4.47",
                                         "input_lra": "0.00", "input_thresh": "-37.61",
                                         "target_offset": "0.01"}
    assert fa.parse_loudnorm(stderr.replace("-27.61", "-inf")) is None
    with pytest.raises(ConversionError):
        fa.parse_loudnorm("garbage")


def test_gif_filtergraph():
    graph = fa.gif_filtergraph({"fps": 10, "width": 480, "colors": 64, "dither": "bayer"}, MEDIA)
    assert graph == ("[0:v]fps=10,scale=480:-1:flags=lanczos,split[a][b];"
                     "[a]palettegen=max_colors=64[p];"
                     "[b][p]paletteuse=dither=bayer:diff_mode=rectangle:bayer_scale=3")
    small = MediaInfo(width=320, height=240, has_video=True)
    assert "scale" not in fa.gif_filtergraph({"width": 480}, small)  # never upscale
    assert "fps" not in fa.gif_filtergraph({"fps": "original", "width": "original"}, MEDIA)


def test_gif_command_loop():
    args = fa.build_gif("ffmpeg", "i.mp4", "o.gif", {"loop": "once"}, MEDIA)
    assert after(args, "-loop") == "-1"
    assert "-filter_complex" in args and "-an" in args


def test_progress_parser():
    p = fa.ProgressParser(4.0)
    assert p.feed("frame=12") is None
    assert p.feed("out_time_us=1000000") == pytest.approx(0.25)
    assert p.feed("out_time_ms=6000000") == 1.0  # clamped
    assert p.feed("out_time_us=N/A") is None
    assert p.feed("progress=end") == 1.0
    assert fa.ProgressParser(None).feed("out_time_us=1000") is None


def test_parse_encoders():
    out = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC
 A....D aac                  AAC (Advanced Audio Coding)
 A....D libopus              libopus Opus
"""
    assert fa.parse_encoders(out) == {"libx264", "aac", "libopus"}


def test_parse_probe_ignores_cover_art():
    info = parse_probe({
        "format": {"duration": "12.5"},
        "streams": [
            {"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100",
             "channels": 2},
            {"codec_type": "video", "codec_name": "mjpeg", "width": 500, "height": 500,
             "disposition": {"attached_pic": 1}},
        ],
    })
    assert info.duration == 12.5
    assert info.has_audio and info.has_cover and not info.has_video
    assert info.sample_rate == 44100 and info.width is None

    video = parse_probe({"format": {}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360,
         "avg_frame_rate": "30000/1001", "duration": "3.0"}]})
    assert video.has_video and not video.has_audio
    assert video.fps == pytest.approx(29.97, abs=0.01)
    assert video.duration == 3.0
