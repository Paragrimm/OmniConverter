"""FFmpeg command construction – no FFmpeg needed."""

import pytest

from omniconverter.backends import ffmpeg_args as fa
from omniconverter.core.errors import ConversionError
from omniconverter.core.probe import MediaInfo, parse_probe

MEDIA = MediaInfo(duration=10.0, has_video=True, has_audio=True, width=1920, height=1080,
                  sample_rate=44100)
MEDIA_LONG = MediaInfo(duration=60.0, has_video=True, width=1920, height=1080, fps=25.0)
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


def test_gif_to_webm_keeps_transparency():
    gif = MediaInfo(duration=1.0, has_video=True, width=385, height=385)
    opts = {"keep_transparency": True, "quality": "medium", "resolution": "original"}
    args = fa.build_video("ffmpeg", "in.gif", "out.webm", "webm", opts, gif, encoders=ENCODERS)
    assert after(args, "-c:v") == "libvpx-vp9"
    assert after(args, "-pix_fmt") == "yuva420p" and after(args, "-auto-alt-ref") == "0"
    assert "-an" in args
    opaque = fa.build_video("ffmpeg", "in.gif", "out.webm", "webm",
                            {**opts, "keep_transparency": False}, gif, encoders=ENCODERS)
    assert after(opaque, "-pix_fmt") == "yuv420p" and "-auto-alt-ref" not in opaque
    mp4 = fa.build_video("ffmpeg", "in.gif", "out.mp4", "mp4", opts, gif, encoders=ENCODERS)
    assert after(mp4, "-pix_fmt") == "yuv420p"  # H.264 has no alpha channel


def test_gif_sources_get_gif_options():
    from omniconverter.backends.ffmpeg import FFmpegVideoBackend
    from omniconverter.core.formats import get_format

    backend = FFmpegVideoBackend()
    webm = {o.key for o in backend.options(get_format("gif"), get_format("webm"))}
    assert "keep_transparency" in webm
    assert not webm & {"normalize", "remove_audio", "fast"}  # GIFs have no sound to process
    mp4 = {o.key for o in backend.options(get_format("gif"), get_format("mp4"))}
    assert "keep_transparency" not in mp4
    video = {o.key for o in backend.options(get_format("mp4"), get_format("webm"))}
    assert "keep_transparency" not in video and "normalize" in video


# -- preview -------------------------------------------------------------------------------


def test_preview_plan_real_time_for_short_parts():
    plan = fa.preview_plan({"start": 1.0, "end": 3.0}, MediaInfo(duration=5.0, fps=30.0))
    assert (plan.start, plan.duration, plan.end) == (1.0, 2.0, 3.0)
    assert plan.fps == 15 and plan.frame_ms == 67 and not plan.timelapse
    slow = fa.preview_plan({"fps": 10}, MediaInfo(duration=5.0, fps=30.0))
    assert slow.fps == 10 and slow.frame_ms == 100  # what the result will look like


def test_preview_plan_time_lapse_for_long_parts():
    plan = fa.preview_plan({"start": 60.0}, MediaInfo(duration=660.0, fps=25.0))
    assert plan.timelapse and plan.duration == 600.0
    assert plan.fps * plan.duration == pytest.approx(fa.PREVIEW_FRAMES)
    assert plan.end_known


def test_preview_plan_without_known_length_shows_the_beginning():
    plan = fa.preview_plan({}, None)
    assert plan.duration == fa.PREVIEW_REALTIME_S and not plan.end_known
    with pytest.raises(ConversionError):
        fa.preview_plan({"start": 4.0, "end": 2.0}, MEDIA)


def test_preview_frames_args():
    plan = fa.preview_plan({"start": 2.0, "end": 4.0}, MEDIA)
    args = fa.build_preview_frames("ffmpeg", "in.mp4", "f-%04d.jpg", plan, 640)
    assert after(args, "-ss") == "2" and after(args, "-t") == "2"
    assert args.index("-ss") < args.index("-i")  # fast input seek
    assert after(args, "-vf") == "fps=15,scale=640:-2:flags=bicubic"
    assert after(args, "-protocol_whitelist") == "file,pipe"
    assert "-skip_frame" not in args and after(args, "-q:v") == "3"
    assert args[-1] == "f-%04d.jpg"


def test_time_lapse_decodes_only_keyframes_and_keeps_alpha():
    plan = fa.preview_plan({}, MediaInfo(duration=3600.0, fps=30.0))
    args = fa.build_preview_frames("ffmpeg", "in.gif", "f-%04d.png", plan, 320, alpha=True)
    assert after(args, "-skip_frame") == "nokey"
    assert args.index("-skip_frame") < args.index("-i")
    assert after(args, "-pix_fmt") == "rgba" and "-q:v" not in args
    assert after(args, "-frames:v") == str(fa.PREVIEW_FRAMES)


def test_edge_frames_of_a_part():
    plan = fa.preview_plan({"start": 10.0, "end": 50.0}, MEDIA_LONG)
    first = fa.build_edge_frame("ffmpeg", "in", "first.jpg", plan, 640, last=False)
    assert after(first, "-ss") == "10" and after(first, "-frames:v") == "1"
    last = fa.build_edge_frame("ffmpeg", "in", "last.jpg", plan, 640, last=True)
    # Seeking to the very end would miss the last frame: decode the last second instead.
    assert after(last, "-ss") == "49" and after(last, "-t") == "1"
    assert after(last, "-update") == "1" and "-frames:v" not in last


@pytest.mark.parametrize(("opts", "size"), [
    ({}, (1920, 1080)),
    ({"resolution": 720}, (1280, 720)),
    ({"resolution": "custom", "width": 500}, (500, 282)),
    ({"fast": True, "resolution": 480}, (1920, 1080)),  # stream copy keeps the size
])
def test_video_output_size(opts, size):
    assert fa.video_output_size(opts, MEDIA) == size


def test_video_output_size_odd_and_unknown():
    odd = MediaInfo(duration=1.0, has_video=True, width=121, height=81)
    assert fa.video_output_size({}, odd) == (120, 80)
    assert fa.video_output_size({}, None) is None
    assert fa.preview_width(odd) == 120 and fa.preview_width(None) == fa.PREVIEW_WIDTH
