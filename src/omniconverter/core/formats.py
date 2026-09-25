"""Known file formats and detection by file extension."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Category(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    DATA = "data"


# Order in which categories are presented to the user.
CATEGORY_ORDER = list(Category)


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    category: Category
    extensions: tuple[str, ...]
    mime: tuple[str, ...] = ()

    @property
    def extension(self) -> str:
        """Canonical extension used for output files."""
        return self.extensions[0]


def _f(id_: str, label: str, cat: Category, exts: str, mime: str = "") -> Format:
    return Format(id_, label, cat, tuple(exts.split()), tuple(mime.split()))


V, A, I, D, S, P, J = (  # noqa: E741
    Category.VIDEO,
    Category.AUDIO,
    Category.IMAGE,
    Category.DOCUMENT,
    Category.SPREADSHEET,
    Category.PRESENTATION,
    Category.DATA,
)

_ALL = [
    # Video
    _f("mp4", "MP4", V, "mp4", "video/mp4"),
    _f("m4v", "M4V", V, "m4v", "video/x-m4v"),
    _f("mkv", "MKV", V, "mkv", "video/x-matroska"),
    _f("webm", "WebM", V, "webm", "video/webm"),
    _f("mov", "MOV", V, "mov qt", "video/quicktime"),
    _f("avi", "AVI", V, "avi", "video/x-msvideo video/avi"),
    _f("wmv", "WMV", V, "wmv", "video/x-ms-wmv"),
    _f("flv", "FLV", V, "flv", "video/x-flv"),
    _f("mpeg", "MPEG", V, "mpg mpeg mpe", "video/mpeg"),
    _f("ts", "MPEG-TS", V, "ts m2ts mts", "video/mp2t video/vnd.dlna.mpeg-tts"),
    _f("3gp", "3GP", V, "3gp 3g2", "video/3gpp video/3gpp2"),
    _f("ogv", "OGV", V, "ogv", "video/ogg"),
    # Audio
    _f("mp3", "MP3", A, "mp3", "audio/mpeg"),
    _f("wav", "WAV", A, "wav", "audio/x-wav audio/wav"),
    _f("flac", "FLAC", A, "flac", "audio/flac audio/x-flac"),
    _f("ogg", "OGG", A, "ogg oga", "audio/ogg audio/x-vorbis+ogg"),
    _f("opus", "Opus", A, "opus", "audio/x-opus+ogg audio/opus"),
    _f("m4a", "M4A", A, "m4a", "audio/mp4 audio/x-m4a"),
    _f("aac", "AAC", A, "aac", "audio/aac audio/x-aac"),
    _f("aiff", "AIFF", A, "aiff aif aifc", "audio/x-aiff audio/aiff"),
    _f("wma", "WMA", A, "wma", "audio/x-ms-wma"),
    # Images
    _f("png", "PNG", I, "png", "image/png"),
    _f("jpg", "JPEG", I, "jpg jpeg jpe jfif", "image/jpeg"),
    _f("webp", "WebP", I, "webp", "image/webp"),
    _f("avif", "AVIF", I, "avif", "image/avif"),
    _f("heic", "HEIC", I, "heic heif", "image/heic image/heif"),
    _f("bmp", "BMP", I, "bmp", "image/bmp image/x-bmp"),
    _f("tiff", "TIFF", I, "tiff tif", "image/tiff"),
    _f("gif", "GIF", I, "gif", "image/gif"),
    _f("ico", "ICO", I, "ico", "image/vnd.microsoft.icon image/x-icon"),
    _f("tga", "TGA", I, "tga", "image/x-tga image/x-targa"),
    # Documents
    _f("pdf", "PDF", D, "pdf", "application/pdf"),
    _f("docx", "DOCX", D, "docx",
       "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    _f("doc", "DOC", D, "doc", "application/msword"),
    _f("odt", "ODT", D, "odt", "application/vnd.oasis.opendocument.text"),
    _f("rtf", "RTF", D, "rtf", "application/rtf text/rtf"),
    _f("txt", "TXT", D, "txt text", "text/plain"),
    _f("md", "Markdown", D, "md markdown", "text/markdown text/x-markdown"),
    _f("html", "HTML", D, "html htm xhtml", "text/html"),
    _f("epub", "EPUB", D, "epub", "application/epub+zip"),
    _f("rst", "RST", D, "rst", "text/x-rst"),
    _f("tex", "LaTeX", D, "tex latex", "text/x-tex application/x-tex"),
    # Spreadsheets
    _f("xlsx", "XLSX", S, "xlsx",
       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    _f("xls", "XLS", S, "xls", "application/vnd.ms-excel"),
    _f("ods", "ODS", S, "ods", "application/vnd.oasis.opendocument.spreadsheet"),
    _f("csv", "CSV", S, "csv", "text/csv"),
    _f("tsv", "TSV", S, "tsv tab", "text/tab-separated-values"),
    # Presentations
    _f("pptx", "PPTX", P, "pptx",
       "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    _f("ppt", "PPT", P, "ppt", "application/vnd.ms-powerpoint"),
    _f("odp", "ODP", P, "odp",
       "application/vnd.oasis.opendocument.presentation"),
    # Structured data
    _f("json", "JSON", J, "json", "application/json"),
    _f("yaml", "YAML", J, "yaml yml", "application/yaml application/x-yaml text/yaml"),
    _f("toml", "TOML", J, "toml", "application/toml"),
]

FORMATS: dict[str, Format] = {f.id: f for f in _ALL}
_BY_EXTENSION: dict[str, Format] = {ext: f for f in _ALL for ext in f.extensions}


def get_format(format_id: str) -> Format:
    """Return the format for an id or any known extension (case-insensitive)."""
    key = format_id.lower().lstrip(".")
    fmt = FORMATS.get(key) or _BY_EXTENSION.get(key)
    if fmt is None:
        raise KeyError(format_id)
    return fmt


def detect_format(path: str | Path) -> Format | None:
    """Detect the format of a file from its extension."""
    suffix = Path(path).suffix.lower().lstrip(".")
    return _BY_EXTENSION.get(suffix)


def all_extensions() -> list[str]:
    return sorted(_BY_EXTENSION)
