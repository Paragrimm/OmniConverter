"""Video and audio conversion via FFmpeg."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from omniconverter.backends import ffmpeg_args as fa
from omniconverter.backends.preview import image_frames
from omniconverter.core import process
from omniconverter.core.backend import (
    Backend,
    Conversion,
    ConversionContext,
    ConversionRequest,
    Preview,
)
from omniconverter.core.errors import Cancelled, ConversionError
from omniconverter.core.formats import Format
from omniconverter.core.options import Kind, Option, when
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

_REQUIRES = ("ffmpeg",)
_encoder_cache: dict[str, set[str]] = {}
_encoder_lock = threading.Lock()


def available_encoders(ffmpeg: str) -> set[str]:
    with _encoder_lock:
        if ffmpeg not in _encoder_cache:
            try:
                out = process.run([ffmpeg, "-hide_banner", "-encoders"], timeout=20).stdout
                _encoder_cache[ffmpeg] = fa.parse_encoders(out)
            except ConversionError:
                _encoder_cache[ffmpeg] = set()
        return _encoder_cache[ffmpeg]


# -- shared option builders ----------------------------------------------------------------


def trim_options() -> list[Option]:
    return [
        Option("start", t("opt.start"), Kind.TIME, None, help=t("opt.trim_help")),
        Option("end", t("opt.end"), Kind.TIME, None, help=t("opt.trim_help")),
    ]


def normalize_option(advanced: bool, visible_if: tuple = ()) -> Option:
    return Option(
        "normalize",
        t("opt.normalize"),
        Kind.CHOICE,
        "off",
        choices=tuple((k, t(f"opt.normalize.{k}")) for k in ("off", "streaming", "podcast",
                                                             "broadcast")),
        advanced=advanced,
        visible_if=visible_if,
    )


def audio_options(target: str) -> list[Option]:
    opts = trim_options()
    if target in fa.LOSSY_AUDIO:
        default = 128 if target == "opus" else 192
        opts.append(Option(
            "bitrate", t("opt.bitrate"), Kind.CHOICE, default,
            choices=tuple((b, f"{b} kbit/s") for b in (96, 128, 160, 192, 256, 320)),
        ))
    opts.append(normalize_option(advanced=False))
    if target == "flac":
        opts.append(Option("flac_level", t("opt.flac_level"), Kind.INT, 5, minimum=0,
                           maximum=8, advanced=True))
    if target != "opus":
        opts.append(Option(
            "sample_rate", t("opt.sample_rate"), Kind.CHOICE, "original",
            choices=(("original", t("opt.original")), (44100, "44,1 kHz"), (48000, "48 kHz")),
            advanced=True,
        ))
    opts += [
        Option("channels", t("opt.channels"), Kind.CHOICE, "original", advanced=True,
               choices=(("original", t("opt.original")), ("mono", t("opt.channels.mono")),
                        ("stereo", t("opt.channels.stereo")))),
        Option("fade_in", t("opt.fade_in"), Kind.INT, 0, minimum=0, maximum=60, suffix=" s",
               advanced=True),
        Option("fade_out", t("opt.fade_out"), Kind.INT, 0, minimum=0, maximum=60, suffix=" s",
               advanced=True),
        Option("strip_metadata", t("opt.strip_metadata"), Kind.BOOL, False, advanced=True,
               help=t("opt.strip_metadata_help")),
    ]
    return opts


def video_options() -> list[Option]:
    not_fast = when("fast", False)
    return [
        *trim_options(),
        Option(
            "resolution", t("opt.resolution"), Kind.CHOICE, "original", visible_if=not_fast,
            choices=(("original", t("opt.original")),
                     *((h, f"{h}p") for h in (2160, 1440, 1080, 720, 480, 360)),
                     ("custom", t("opt.custom"))),
        ),
        Option("width", t("opt.width"), Kind.INT, 1280, minimum=16, maximum=7680, suffix=" px",
               visible_if=(("fast", (False,)), ("resolution", ("custom",)))),
        Option(
            "quality", t("opt.quality"), Kind.CHOICE, "medium", visible_if=not_fast,
            choices=tuple((q, t(f"opt.quality.{q}")) for q in ("high", "medium", "small")),
        ),
        Option("fast", t("opt.fast"), Kind.BOOL, False, advanced=True, help=t("opt.fast_help")),
        Option("fps", t("opt.fps"), Kind.CHOICE, "original", advanced=True, visible_if=not_fast,
               choices=(("original", t("opt.original")),
                        *((f, str(f)) for f in (60, 50, 30, 25, 24)))),
        Option("remove_audio", t("opt.remove_audio"), Kind.BOOL, False, advanced=True),
        normalize_option(
            advanced=True, visible_if=(("fast", (False,)), ("remove_audio", (False,)))
        ),
        Option("strip_metadata", t("opt.strip_metadata"), Kind.BOOL, True, advanced=True,
               help=t("opt.strip_metadata_help")),
    ]


def gif_video_options(target: str) -> list[Option]:
    """Animated GIF → video: no audio, no stream copy; WebM can keep the transparency."""
    opts = [
        *trim_options(),
        Option(
            "resolution", t("opt.resolution"), Kind.CHOICE, "original",
            choices=(("original", t("opt.original")),
                     *((h, f"{h}p") for h in (1080, 720, 480, 360)),
                     ("custom", t("opt.custom"))),
        ),
        Option("width", t("opt.width"), Kind.INT, 480, minimum=16, maximum=7680, suffix=" px",
               visible_if=when("resolution", "custom")),
        Option(
            "quality", t("opt.quality"), Kind.CHOICE, "medium",
            choices=tuple((q, t(f"opt.quality.{q}")) for q in ("high", "medium", "small")),
        ),
    ]
    if target in fa.ALPHA_TARGETS:
        opts.append(Option("keep_transparency", t("opt.keep_transparency"), Kind.BOOL, True,
                           help=t("opt.keep_transparency_help")))
    opts.append(Option("fps", t("opt.fps"), Kind.CHOICE, "original", advanced=True,
                       choices=(("original", t("opt.original")),
                                *((f, str(f)) for f in (60, 50, 30, 25, 24, 15)))))
    return opts


def gif_options(source_is_gif: bool) -> list[Option]:
    return [
        *trim_options(),
        Option("fps", t("opt.fps"), Kind.CHOICE, "original" if source_is_gif else 12,
               choices=(("original", t("opt.original")),
                        *((f, str(f)) for f in (5, 8, 10, 12, 15, 20, 25, 30)))),
        Option("width", t("opt.width"), Kind.CHOICE, "original" if source_is_gif else 480,
               choices=(("original", t("opt.original")),
                        *((w, f"{w} px") for w in (160, 240, 320, 480, 640, 800, 1024)))),
        Option("colors", t("opt.colors"), Kind.INT, 256, minimum=2, maximum=256),
        Option("dither", t("opt.dither"), Kind.CHOICE, "sierra2_4a", advanced=True,
               choices=tuple((d, t(f"opt.dither.{d}"))
                             for d in ("sierra2_4a", "floyd_steinberg", "bayer", "none"))),
        Option("loop", t("opt.loop"), Kind.CHOICE, "forever", advanced=True,
               choices=(("forever", t("opt.loop.forever")), ("once", t("opt.loop.once")))),
    ]


# -- running -------------------------------------------------------------------------------


class _FFmpegBase(Backend):
    def _run(self, args: list[str], ctx: ConversionContext, total: float | None,
             span: tuple[float, float] = (0.0, 1.0)) -> process.RunResult:
        parser = fa.ProgressParser(total)
        lo, hi = span
        if total is None:
            ctx.progress(None)

        def on_line(line: str) -> None:
            fraction = parser.feed(line)
            if fraction is not None and total:
                ctx.progress(lo + (hi - lo) * fraction)

        return process.run(args, cancel=ctx.cancel, on_stdout_line=on_line,
                           error_message=t("error.ffmpeg_failed"))

    def _measure_loudness(self, ffmpeg: str, request: ConversionRequest,
                          ctx: ConversionContext, total: float | None) -> dict[str, str] | None:
        args = fa.build_loudnorm_measure(ffmpeg, str(request.source), request.options,
                                         request.media)
        result = self._run(args, ctx, total, (0.0, 0.5))
        return fa.parse_loudnorm(result.stderr_tail)

    def _with_fallback(self, attempts: Iterable[Callable[[], Any]]) -> None:
        """Try each attempt until one succeeds (e.g. stream copy → re-encode)."""
        error: ConversionError | None = None
        for attempt in attempts:
            try:
                attempt()
                return
            except Cancelled:
                raise
            except ConversionError as exc:
                error = exc
        assert error is not None
        raise error


def _duration(request: ConversionRequest) -> float | None:
    media = request.media
    return fa.trim(request.options.get("start"), request.options.get("end"),
                   media.duration if media else None).duration


class FFmpegVideoBackend(_FFmpegBase):
    """Video (and animated GIF) sources → video, GIF, or extracted audio."""

    id = "ffmpeg-video"

    def conversions(self) -> Iterable[Conversion]:
        for src in fa.VIDEO_SOURCES:
            for dst in (*fa.VIDEO_TARGETS, "gif", *fa.AUDIO_TARGETS):
                yield Conversion(src, dst, _REQUIRES)
        for dst in (*fa.VIDEO_TARGETS, "gif"):
            # GIF → GIF via FFmpeg (trim, fps, palette) beats Pillow; Pillow is the fallback.
            yield Conversion("gif", dst, _REQUIRES, priority=60)

    def supports(self, conversion: Conversion, media: MediaInfo | None) -> bool:
        if media is None:
            return True
        if conversion.target in fa.AUDIO_TARGETS:
            return media.has_audio
        return media.has_video

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        if target.id == "gif":
            return gif_options(source.id == "gif")
        if target.id in fa.AUDIO_TARGETS:
            return audio_options(target.id)
        if source.id == "gif":
            return gif_video_options(target.id)
        return video_options()

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ffmpeg = ctx.locator.require("ffmpeg")
        src, out, target = str(request.source), str(output), request.target_format.id
        opts, media = request.options, request.media
        total = _duration(request)

        if target == "gif":
            self._run(fa.build_gif(ffmpeg, src, out, opts, media), ctx, total)
            return
        if target in fa.AUDIO_TARGETS:
            _convert_audio(self, ffmpeg, request, output, ctx, total, allow_cover=False)
            return

        encoders = available_encoders(ffmpeg)
        normalize = (opts.get("normalize", "off") != "off" and not opts.get("remove_audio")
                     and not opts.get("fast") and (media is None or media.has_audio))
        measured = self._measure_loudness(ffmpeg, request, ctx, total) if normalize else None
        span = (0.5, 1.0) if normalize else (0.0, 1.0)

        def encode(options: dict[str, Any]) -> Callable[[], Any]:
            return lambda: self._run(
                fa.build_video(ffmpeg, src, out, target, options, media,
                               measured=measured, encoders=encoders),
                ctx, total, span)

        attempts = [encode(opts)]
        if opts.get("fast"):
            attempts.append(encode({**opts, "fast": False}))
        self._with_fallback(attempts)

    # -- preview ----------------------------------------------------------------------------

    def can_preview(self, source: Format, target: Format) -> bool:
        return target.id not in fa.AUDIO_TARGETS

    def preview(self, request: ConversionRequest, ctx: ConversionContext) -> Preview:
        ffmpeg = ctx.locator.require("ffmpeg")
        if request.target_format.id == "gif":
            return self._gif_preview(ffmpeg, request, ctx)
        return self._video_preview(ffmpeg, request, ctx)

    def _video_preview(self, ffmpeg: str, request: ConversionRequest,
                       ctx: ConversionContext) -> Preview:
        """Silent frames of the chosen part: in real time, or as a time-lapse if it is long."""
        opts, media, src = request.options, request.media, str(request.source)
        plan = fa.preview_plan(opts, media)
        width = fa.preview_width(media)
        alpha = (request.source_format.id == "gif" and bool(opts.get("keep_transparency"))
                 and request.target_format.id in fa.ALPHA_TARGETS)
        ext = "png" if alpha else "jpg"
        pattern = str(ctx.work_dir / f"frame-%04d.{ext}")
        self._run(fa.build_preview_frames(ffmpeg, src, pattern, plan, width, alpha=alpha),
                  ctx, plan.duration)
        frames = sorted(ctx.work_dir.glob(f"frame-*.{ext}"))
        timestamps = [plan.start + i / plan.fps for i in range(len(frames))]
        if plan.timelapse:  # keyframes only in between: the exact first and last frame too
            first, last = ctx.work_dir / f"first.{ext}", ctx.work_dir / f"last.{ext}"
            for path, is_last in ((first, False), (last, True)):
                self._run(fa.build_edge_frame(ffmpeg, src, str(path), plan, width, last=is_last,
                                              alpha=alpha), ctx, None)
            if first.is_file() and last.is_file():
                last_at = plan.end - 1 / (media.fps if media and media.fps else 25)
                frames = [first, *frames[1:], last]  # the exact first replaces a keyframe
                timestamps = [plan.start, *timestamps[1:], max(plan.start, last_at)]
        if not frames:
            raise ConversionError(t("error.no_output"))
        notes = []
        if plan.timelapse:
            notes.append(t("preview.timelapse"))
        if not plan.end_known:
            notes.append(t("preview.first_seconds", s=f"{fa.PREVIEW_REALTIME_S:g}"))
        if opts.get("fast") and plan.start > 0:
            notes.append(t("preview.fast_cut"))
        size = fa.video_output_size(opts, media)
        return Preview(frames, [plan.frame_ms] * len(frames), timestamps,
                       span=(plan.start, plan.end), width=size[0] if size else None,
                       height=size[1] if size else None, note=" · ".join(notes))

    def _gif_preview(self, ffmpeg: str, request: ConversionRequest,
                     ctx: ConversionContext) -> Preview:
        """The real GIF with all options (colors, dithering, …), at most a few seconds long."""
        opts, media = dict(request.options), request.media
        start = opts.get("start") or 0.0
        full = _duration(request)  # also checks the cut
        shortened = full is None or full > fa.GIF_PREVIEW_S
        if shortened:
            opts["end"] = start + fa.GIF_PREVIEW_S
        shown = fa.GIF_PREVIEW_S if shortened else full
        result = ctx.work_dir / "result.gif"
        self._run(fa.build_gif(ffmpeg, str(request.source), str(result), opts, media),
                  ctx, shown)
        frames, durations, (width, height) = image_frames(result, ctx)
        timestamps, at = [], start
        for duration in durations or [0]:
            timestamps.append(at)
            at += duration / 1000
        size: int | None = result.stat().st_size
        note = ""
        if shortened and full is not None and shown:
            size = round(size * full / shown)  # GIF size grows about linearly with the length
        elif shortened:
            size, note = None, t("preview.first_seconds", s=f"{fa.GIF_PREVIEW_S:g}")
        return Preview(frames, durations, timestamps if durations else [],
                       span=(start, start + (shown or 0)), width=width, height=height,
                       size_bytes=size, estimated=shortened and size is not None, note=note)


class FFmpegAudioBackend(_FFmpegBase):
    id = "ffmpeg-audio"

    def conversions(self) -> Iterable[Conversion]:
        for src in fa.AUDIO_SOURCES:
            for dst in fa.AUDIO_TARGETS:
                yield Conversion(src, dst, _REQUIRES)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        return audio_options(target.id)

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ffmpeg = ctx.locator.require("ffmpeg")
        _convert_audio(self, ffmpeg, request, output, ctx, _duration(request), allow_cover=True)


def _convert_audio(backend: _FFmpegBase, ffmpeg: str, request: ConversionRequest, output: Path,
                   ctx: ConversionContext, total: float | None, *, allow_cover: bool) -> None:
    opts, media, target = request.options, request.media, request.target_format.id
    encoders = available_encoders(ffmpeg)
    normalize = opts.get("normalize", "off") != "off"
    measured = backend._measure_loudness(ffmpeg, request, ctx, total) if normalize else None
    span = (0.5, 1.0) if normalize else (0.0, 1.0)
    keep_cover = bool(allow_cover and media and media.has_cover
                      and target in fa.COVER_ART_TARGETS and not opts.get("strip_metadata"))

    def encode(cover: bool) -> Callable[[], Any]:
        return lambda: backend._run(
            fa.build_audio(ffmpeg, str(request.source), str(output), target, opts, media,
                           measured=measured, encoders=encoders, keep_cover=cover),
            ctx, total, span)

    attempts = [encode(True), encode(False)] if keep_cover else [encode(False)]
    backend._with_fallback(attempts)
