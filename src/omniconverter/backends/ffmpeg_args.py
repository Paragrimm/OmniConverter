"""Pure functions turning options into FFmpeg command lines (unit-testable without FFmpeg)."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from omniconverter.core.errors import ConversionError
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

VIDEO_SOURCES = (
    "mp4", "m4v", "mkv", "webm", "mov", "avi", "wmv", "flv", "mpeg", "ts", "3gp", "ogv",
)
VIDEO_TARGETS = ("mp4", "mkv", "webm", "mov", "avi")
AUDIO_SOURCES = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff", "wma")
AUDIO_TARGETS = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aiff")
LOSSY_AUDIO = ("mp3", "ogg", "opus", "m4a")
ALPHA_TARGETS = ("webm",)  # VP9/VP8 in WebM can carry an alpha channel
COVER_ART_TARGETS = ("mp3", "flac", "m4a")

# Loudness targets in LUFS (EBU R128 integrated loudness).
LOUDNESS = {"streaming": -14.0, "podcast": -16.0, "broadcast": -23.0}
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0

# Encoder preferences; the first one the installed FFmpeg offers is used.
_H264 = ("libx264", "libopenh264", "h264_mf", "mpeg4")
_VP9 = ("libvpx-vp9", "libvpx")
_VIDEO_ENCODERS = {
    "mp4": _H264, "mov": _H264, "mkv": _H264, "m4v": _H264,
    "webm": _VP9,
    "avi": ("mpeg4",),
}
_AUDIO_ENCODERS = {
    "mp3": ("libmp3lame", "mp3_mf"),
    "ogg": ("libvorbis", "vorbis"),
    "opus": ("libopus", "opus"),
    "m4a": ("aac",),
    "aac": ("aac",),
    "wav": ("pcm_s16le",),
    "aiff": ("pcm_s16be",),
    "flac": ("flac",),
}
_AUDIO_IN_VIDEO = {"mp4": "aac", "mov": "aac", "mkv": "aac", "m4v": "aac",
                   "webm": "opus", "avi": "mp3"}
_EXPERIMENTAL = {"vorbis", "opus"}

_CRF = {
    "libx264": {"high": 18, "medium": 23, "small": 28},
    "libvpx-vp9": {"high": 24, "medium": 32, "small": 38},
    "libvpx": {"high": 6, "medium": 10, "small": 20},
}
_QSCALE = {"high": 2, "medium": 5, "small": 9}  # mpeg4 -q:v
_BITRATE = {"high": "8M", "medium": "4M", "small": "1500k"}  # encoders without CRF

BASE_INPUT = ["-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe"]
PROGRESS = ["-progress", "pipe:1", "-nostats"]


def pick_encoder(preferences: Sequence[str], available: Collection[str] | None) -> str:
    if not available:
        return preferences[0]
    for name in preferences:
        if name in available:
            return name
    return preferences[0]


def parse_encoders(output: str) -> set[str]:
    """Parse ``ffmpeg -encoders`` output into encoder names."""
    names = set()
    for line in output.splitlines():
        m = re.match(r"\s*[VAS][A-Z.]{5}\s+([\w-]+)\s", line)
        if m:
            names.add(m.group(1))
    return names


def fmt_seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


@dataclass(frozen=True)
class Trim:
    input_args: list[str]
    output_args: list[str]
    duration: float | None  # duration of the output, if known


def trim(start: float | None, end: float | None, media_duration: float | None) -> Trim:
    start = start or 0.0
    if end is not None and end <= start:
        raise ConversionError(t("error.trim_range"))
    if media_duration is not None and start >= media_duration:
        raise ConversionError(t("error.trim_range"))
    input_args = ["-ss", fmt_seconds(start)] if start > 0 else []
    output_args = []
    if end is not None and (media_duration is None or end < media_duration):
        output_args = ["-t", fmt_seconds(end - start)]
        duration: float | None = end - start
    else:
        duration = media_duration - start if media_duration is not None else None
    return Trim(input_args, output_args, duration)


# -- audio ---------------------------------------------------------------------------------


def loudnorm_filter(target: float, measured: dict[str, str] | None = None) -> str:
    base = f"loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA={LOUDNESS_RANGE:g}"
    if measured is None:
        return base + ":print_format=json"
    return (
        f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary"
    )


def parse_loudnorm(stderr: str) -> dict[str, str] | None:
    """Extract the JSON block printed by ``loudnorm=print_format=json``.

    Returns ``None`` for silent input (``-inf``) where normalization is meaningless.
    """
    matches = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, flags=re.DOTALL)
    if not matches:
        raise ConversionError(t("error.ffmpeg_failed"), stderr[-2000:])
    data = json.loads(matches[-1])
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if any("inf" in str(data.get(k, "")) for k in keys):
        return None
    return {k: str(data[k]) for k in keys}


def audio_filters(
    opts: dict[str, Any], duration: float | None, measured: dict[str, str] | None
) -> list[str]:
    filters = []
    target = LOUDNESS.get(opts.get("normalize", "off"))
    if target is not None and measured is not None:
        filters.append(loudnorm_filter(target, measured))
    fade_in = opts.get("fade_in") or 0
    fade_out = opts.get("fade_out") or 0
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0 and duration is not None and duration > fade_out:
        filters.append(f"afade=t=out:st={fmt_seconds(duration - fade_out)}:d={fade_out}")
    return filters


def output_sample_rate(target: str, opts: dict[str, Any], media: MediaInfo | None,
                       normalizing: bool) -> int | None:
    if target == "opus":
        return 48000
    chosen = opts.get("sample_rate", "original")
    if chosen != "original":
        return int(chosen)
    if normalizing:  # loudnorm resamples to 192 kHz internally – go back to the source rate
        return (media.sample_rate if media and media.sample_rate else None) or 48000
    return None


def audio_codec_args(
    target: str, opts: dict[str, Any], encoders: Collection[str] | None
) -> list[str]:
    codec = pick_encoder(_AUDIO_ENCODERS[target], encoders)
    args = ["-c:a", codec]
    if codec in _EXPERIMENTAL:
        args += ["-strict", "-2"]
    if target in LOSSY_AUDIO:
        args += ["-b:a", f"{opts.get('bitrate', 192)}k"]
    if target == "flac":
        args += ["-compression_level", str(opts.get("flac_level", 5))]
    channels = opts.get("channels", "original")
    if channels == "mono":
        args += ["-ac", "1"]
    elif channels == "stereo":
        args += ["-ac", "2"]
    return args


def build_loudnorm_measure(
    ffmpeg: str, source: str, opts: dict[str, Any], media: MediaInfo | None
) -> list[str]:
    tr = trim(opts.get("start"), opts.get("end"), media.duration if media else None)
    target = LOUDNESS[opts["normalize"]]
    return [
        ffmpeg, *BASE_INPUT, *tr.input_args, "-i", source, *tr.output_args,
        *PROGRESS, "-vn", "-sn", "-dn",
        "-af", loudnorm_filter(target), "-f", "null", "-",
    ]


def build_audio(
    ffmpeg: str,
    source: str,
    output: str,
    target: str,
    opts: dict[str, Any],
    media: MediaInfo | None,
    *,
    measured: dict[str, str] | None = None,
    encoders: Collection[str] | None = None,
    keep_cover: bool = False,
) -> list[str]:
    """Audio file (or the audio track of a video) → audio file."""
    tr = trim(opts.get("start"), opts.get("end"), media.duration if media else None)
    args = [ffmpeg, *BASE_INPUT, *tr.input_args, "-i", source, *tr.output_args, *PROGRESS]
    if keep_cover:
        args += ["-map", "0:a:0", "-map", "0:v:0", "-c:v", "copy",
                 "-disposition:v:0", "attached_pic"]
    else:
        args += ["-map", "0:a:0", "-vn"]
    args += ["-sn", "-dn"]
    args += audio_codec_args(target, opts, encoders)
    filters = audio_filters(opts, tr.duration, measured)
    if filters:
        args += ["-af", ",".join(filters)]
    rate = output_sample_rate(target, opts, media, measured is not None)
    if rate:
        args += ["-ar", str(rate)]
    if opts.get("strip_metadata"):
        args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    if target == "m4a":
        args += ["-movflags", "+faststart"]
    return [*args, output]


# -- video ---------------------------------------------------------------------------------


def video_filters(opts: dict[str, Any], media: MediaInfo | None, encoder: str) -> list[str]:
    filters = []
    fps = opts.get("fps", "original")
    if fps != "original":
        filters.append(f"fps={fps}")
    resolution = opts.get("resolution", "original")
    if resolution == "custom":
        filters.append(f"scale={int(opts.get('width') or 1280)}:-2:flags=lanczos")
    elif resolution != "original":
        filters.append(f"scale=-2:{int(resolution)}:flags=lanczos")
    elif encoder != "mpeg4" and (
        media is None or media.width is None or media.width % 2 or (media.height or 0) % 2
    ):
        # H.264/VP9 with 4:2:0 chroma need even dimensions (odd ones occur e.g. in GIFs).
        filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    return filters


def video_codec_args(encoder: str, quality: str, alpha: bool = False) -> list[str]:
    args = ["-c:v", encoder]
    if encoder == "libx264":
        args += ["-preset", "medium", "-crf", str(_CRF[encoder][quality]), "-pix_fmt", "yuv420p"]
    elif encoder in ("libvpx-vp9", "libvpx"):
        args += ["-crf", str(_CRF[encoder][quality]), "-b:v", "0", "-deadline", "good",
                 "-cpu-used", "4"]
        if alpha:  # libvpx cannot combine an alpha plane with alternate reference frames
            args += ["-pix_fmt", "yuva420p", "-auto-alt-ref", "0"]
        else:
            args += ["-pix_fmt", "yuv420p"]
        if encoder == "libvpx-vp9":
            args += ["-row-mt", "1"]
    elif encoder == "mpeg4":
        args += ["-q:v", str(_QSCALE[quality]), "-pix_fmt", "yuv420p"]
    else:
        args += ["-b:v", _BITRATE[quality], "-pix_fmt", "yuv420p"]
    return args


def build_video(
    ffmpeg: str,
    source: str,
    output: str,
    target: str,
    opts: dict[str, Any],
    media: MediaInfo | None,
    *,
    measured: dict[str, str] | None = None,
    encoders: Collection[str] | None = None,
) -> list[str]:
    """Video → video. With ``opts['fast']`` the streams are copied instead of re-encoded."""
    tr = trim(opts.get("start"), opts.get("end"), media.duration if media else None)
    args = [ffmpeg, *BASE_INPUT, *tr.input_args, "-i", source, *tr.output_args, *PROGRESS]
    has_audio = media.has_audio if media else True
    remove_audio = opts.get("remove_audio") or not has_audio

    if opts.get("fast"):
        args += ["-map", "0:v:0"]
        if not remove_audio:
            args += ["-map", "0:a?"]
        args += ["-c", "copy"]
    else:
        encoder = pick_encoder(_VIDEO_ENCODERS[target], encoders)
        args += ["-map", "0:v:0"]
        filters = video_filters(opts, media, encoder)
        if filters:
            args += ["-vf", ",".join(filters)]
        alpha = bool(opts.get("keep_transparency")) and target in ALPHA_TARGETS
        args += video_codec_args(encoder, opts.get("quality", "medium"), alpha)
        if not remove_audio:
            args += ["-map", "0:a:0?"]
            audio_target = _AUDIO_IN_VIDEO[target]
            codec = pick_encoder(_AUDIO_ENCODERS[audio_target], encoders)
            args += ["-c:a", codec]
            if codec in _EXPERIMENTAL:
                args += ["-strict", "-2"]
            args += ["-b:a", "128k" if audio_target == "opus" else "192k"]
            filters = audio_filters(opts, tr.duration, measured)
            if filters:
                args += ["-af", ",".join(filters)]
            if measured is not None:
                rate = 48000 if audio_target == "opus" else (media and media.sample_rate) or 48000
                args += ["-ar", str(rate)]
    if remove_audio:
        args += ["-an"]
    args += ["-sn", "-dn"]
    if opts.get("strip_metadata"):
        args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    if target in ("mp4", "mov", "m4v"):
        args += ["-movflags", "+faststart"]
    return [*args, output]


def gif_filtergraph(opts: dict[str, Any], media: MediaInfo | None) -> str:
    steps = []
    fps = opts.get("fps", 12)
    if fps != "original":
        steps.append(f"fps={fps}")
    width = opts.get("width", 480)
    if width != "original" and (media is None or media.width is None or media.width > width):
        steps.append(f"scale={int(width)}:-1:flags=lanczos")
    chain = ",".join([*steps, "split[a][b]"])
    colors = int(opts.get("colors", 256))
    dither = opts.get("dither", "sierra2_4a")
    use = f"paletteuse=dither={dither}:diff_mode=rectangle"
    if dither == "bayer":
        use += ":bayer_scale=3"
    return f"[0:v]{chain};[a]palettegen=max_colors={colors}[p];[b][p]{use}"


def build_gif(
    ffmpeg: str, source: str, output: str, opts: dict[str, Any], media: MediaInfo | None
) -> list[str]:
    tr = trim(opts.get("start"), opts.get("end"), media.duration if media else None)
    loop = "0" if opts.get("loop", "forever") == "forever" else "-1"
    return [
        ffmpeg, *BASE_INPUT, *tr.input_args, "-i", source, *tr.output_args, *PROGRESS,
        "-filter_complex", gif_filtergraph(opts, media),
        "-an", "-sn", "-dn", "-map_metadata", "-1", "-loop", loop, output,
    ]


# -- preview -------------------------------------------------------------------------------

PREVIEW_REALTIME_S = 10.0  # shorter parts are previewed in real time …
PREVIEW_MAX_FPS = 15
PREVIEW_FRAMES = 120  # … longer ones as a time-lapse of this many frames
PREVIEW_TIMELAPSE_FPS = 12  # playback speed of the time-lapse
PREVIEW_WIDTH = 640
GIF_PREVIEW_S = 10.0  # GIF previews are real GIFs of at most this length


@dataclass(frozen=True)
class PreviewPlan:
    start: float
    duration: float  # of the part shown
    fps: float  # frames taken per second of the source
    frame_ms: int  # display time of each frame
    timelapse: bool
    end_known: bool  # False: the source's length is unknown, only the first seconds are shown

    @property
    def end(self) -> float:
        return self.start + self.duration


def preview_plan(opts: dict[str, Any], media: MediaInfo | None) -> PreviewPlan:
    """Which frames a video preview shows (raises like :func:`trim` for invalid cuts)."""
    start = opts.get("start") or 0.0
    duration = trim(start, opts.get("end"), media.duration if media else None).duration
    fps = opts.get("fps", "original")
    source_fps = float(fps) if fps != "original" else (media.fps if media and media.fps else 25.0)
    rate = min(source_fps, PREVIEW_MAX_FPS)
    if duration is None:
        return PreviewPlan(start, PREVIEW_REALTIME_S, rate, round(1000 / rate), False, False)
    if duration <= PREVIEW_REALTIME_S:
        return PreviewPlan(start, duration, rate, round(1000 / rate), False, True)
    return PreviewPlan(start, duration, PREVIEW_FRAMES / duration,
                       round(1000 / PREVIEW_TIMELAPSE_FPS), True, True)


def preview_width(media: MediaInfo | None) -> int:
    width = min(PREVIEW_WIDTH, media.width) if media and media.width else PREVIEW_WIDTH
    return max(2, width - width % 2)


def build_preview_frames(
    ffmpeg: str, source: str, pattern: str, plan: PreviewPlan, width: int, *, alpha: bool = False
) -> list[str]:
    """Frames of the chosen part as images (*pattern* like ``frame-%04d.jpg``).

    A time-lapse only decodes keyframes, so previewing an hour stays quick.
    """
    args = [ffmpeg, *BASE_INPUT]
    if plan.timelapse:
        args += ["-skip_frame", "nokey"]
    if plan.start > 0:
        args += ["-ss", fmt_seconds(plan.start)]
    args += ["-i", source, "-t", fmt_seconds(plan.duration), *PROGRESS, "-map", "0:v:0",
             "-vf", f"fps={plan.fps:.6g},scale={width}:-2:flags=bicubic",
             "-an", "-sn", "-dn", "-frames:v", str(PREVIEW_FRAMES)]
    args += ["-pix_fmt", "rgba"] if alpha else ["-q:v", "3"]
    return [*args, pattern]


def build_edge_frame(ffmpeg: str, source: str, output: str, plan: PreviewPlan, width: int, *,
                     last: bool, alpha: bool = False) -> list[str]:
    """The exact first or last frame of the part, e.g. around a time-lapse of keyframes.

    For the last one, the final second is decoded and each frame overwrites the previous one:
    seeking right to the end would land behind the last frame.
    """
    start = max(plan.start, plan.end - 1.0) if last else plan.start
    args = [ffmpeg, *BASE_INPUT]
    if start > 0:
        args += ["-ss", fmt_seconds(start)]
    args += ["-i", source, "-t", fmt_seconds(plan.end - start), "-map", "0:v:0",
             "-vf", f"scale={width}:-2:flags=bicubic", "-an", "-sn", "-dn"]
    args += ["-update", "1"] if last else ["-frames:v", "1"]
    args += ["-pix_fmt", "rgba"] if alpha else ["-q:v", "3"]
    return [*args, output]


def video_output_size(opts: dict[str, Any], media: MediaInfo | None) -> tuple[int, int] | None:
    """Pixel size of a video result (the scale filters in :func:`video_filters` do this)."""
    if media is None or not media.width or not media.height:
        return None
    width, height = media.width, media.height
    if opts.get("fast"):
        return width, height
    resolution = opts.get("resolution", "original")
    if resolution == "custom":
        new_width = int(opts.get("width") or 1280)
        return new_width, _even(height * new_width / width)
    if resolution != "original":
        return _even(width * int(resolution) / height), int(resolution)
    return width - width % 2, height - height % 2


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


class ProgressParser:
    """Turns ``-progress pipe:1`` lines into fractions of *total* seconds."""

    def __init__(self, total: float | None) -> None:
        self.total = total

    def feed(self, line: str) -> float | None:
        """Returns a fraction in ``[0, 1]`` if *line* carries progress, else ``None``."""
        key, _, value = line.partition("=")
        if key == "progress" and value == "end":
            return 1.0
        if not self.total or key not in ("out_time_us", "out_time_ms"):
            return None
        try:
            seconds = int(value) / 1_000_000  # both keys are in microseconds
        except ValueError:
            return None
        return max(0.0, min(1.0, seconds / self.total))
