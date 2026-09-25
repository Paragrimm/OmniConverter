"""Minimal German/English translations (Qt-free, usable from core, CLI and GUI)."""

from __future__ import annotations

import contextlib
import locale
import os

LANGUAGES = ("de", "en")
_language: str | None = None

# key: (Deutsch, English)
MESSAGES: dict[str, tuple[str, str]] = {
    # --- categories ---
    "category.video": ("Video", "Video"),
    "category.audio": ("Audio", "Audio"),
    "category.image": ("Bild", "Image"),
    "category.document": ("Dokument", "Document"),
    "category.spreadsheet": ("Tabelle", "Spreadsheet"),
    "category.presentation": ("Präsentation", "Presentation"),
    "category.data": ("Daten", "Data"),
    # --- errors ---
    "error.tool_missing": ("{tool} ist nicht installiert.", "{tool} is not installed."),
    "error.not_a_file": ("Datei nicht gefunden: {path}", "File not found: {path}"),
    "error.unknown_format": (
        "Das Format von „{name}“ wird nicht unterstützt.",
        "The format of “{name}” is not supported.",
    ),
    "error.same_file": (
        "Quelle und Ziel dürfen nicht dieselbe Datei sein.",
        "Source and target must not be the same file.",
    ),
    "error.no_output": (
        "Die Umwandlung hat keine Datei erzeugt.",
        "The conversion did not produce a file.",
    ),
    "error.permission": (
        "Keine Schreibrechte für „{path}“.",
        "No permission to write to “{path}”.",
    ),
    "error.no_common_target": (
        "Für diese Dateien gibt es kein gemeinsames Zielformat.",
        "These files have no target format in common.",
    ),
    "error.ffmpeg_failed": ("FFmpeg konnte die Datei nicht umwandeln.", "FFmpeg failed."),
    "error.pandoc_failed": ("Pandoc konnte die Datei nicht umwandeln.", "Pandoc failed."),
    "error.libreoffice_failed": (
        "LibreOffice konnte die Datei nicht umwandeln.",
        "LibreOffice failed.",
    ),
    "error.image_failed": ("Das Bild konnte nicht gelesen werden.", "Could not read the image."),
    "error.trim_range": (
        "Das Ende muss nach dem Anfang liegen.",
        "The end must be after the start.",
    ),
    "error.data_read": (
        "Die Datei konnte nicht gelesen werden: {problem}",
        "Could not read the file: {problem}",
    ),
    "error.data_not_tabular": (
        "Die Daten sind keine Tabelle (erwartet wird eine Liste von Objekten).",
        "The data is not tabular (expected a list of objects).",
    ),
    "error.toml_structure": (
        "TOML braucht auf oberster Ebene Schlüssel/Wert-Paare.",
        "TOML needs key/value pairs at the top level.",
    ),
    "error.sheet_missing": (
        "Tabellenblatt „{sheet}“ nicht gefunden.",
        "Sheet “{sheet}” not found.",
    ),
    # --- common options ---
    "opt.start": ("Start", "Start"),
    "opt.end": ("Ende", "End"),
    "opt.trim_help": (
        "Leer lassen für Anfang bzw. Ende. Formate: 90, 1:30, 0:01:30.5",
        "Leave empty for the beginning/end. Formats: 90, 1:30, 0:01:30.5",
    ),
    "opt.strip_metadata": ("Metadaten entfernen", "Remove metadata"),
    "opt.strip_metadata_help": (
        "Entfernt z. B. GPS-Position, Kamera- und Autorinfos.",
        "Removes e.g. GPS location, camera and author info.",
    ),
    "opt.original": ("Original", "Original"),
    # --- video ---
    "opt.resolution": ("Auflösung", "Resolution"),
    "opt.custom": ("Eigene Breite", "Custom width"),
    "opt.width": ("Breite", "Width"),
    "opt.quality": ("Qualität", "Quality"),
    "opt.quality.high": ("Hoch", "High"),
    "opt.quality.medium": ("Mittel", "Medium"),
    "opt.quality.small": ("Kleine Datei", "Small file"),
    "opt.fps": ("Bilder pro Sekunde", "Frames per second"),
    "opt.remove_audio": ("Ton entfernen", "Remove audio"),
    "opt.fast": ("Schnell, ohne Neukodierung", "Fast, without re-encoding"),
    "opt.fast_help": (
        "Kopiert die Spuren nur um – verlustfrei und sehr schnell. Schnitte landen dann auf "
        "dem nächsten Schlüsselbild. Klappt es nicht, wird automatisch neu kodiert.",
        "Only copies the streams – lossless and very fast. Cuts snap to the nearest keyframe. "
        "Falls back to re-encoding automatically if needed.",
    ),
    # --- gif ---
    "opt.colors": ("Farben", "Colors"),
    "opt.dither": ("Dithering", "Dithering"),
    "opt.dither.none": ("Keins (flächig)", "None (flat)"),
    "opt.dither.bayer": ("Bayer (klein)", "Bayer (small)"),
    "opt.dither.floyd_steinberg": ("Floyd-Steinberg (weich)", "Floyd–Steinberg (smooth)"),
    "opt.dither.sierra2_4a": ("Sierra (ausgewogen)", "Sierra (balanced)"),
    "opt.loop": ("Wiederholen", "Loop"),
    "opt.loop.forever": ("Endlos", "Forever"),
    "opt.loop.once": ("Einmal abspielen", "Play once"),
    # --- audio ---
    "opt.bitrate": ("Bitrate", "Bitrate"),
    "opt.flac_level": ("Kompression", "Compression"),
    "opt.sample_rate": ("Abtastrate", "Sample rate"),
    "opt.channels": ("Kanäle", "Channels"),
    "opt.channels.mono": ("Mono", "Mono"),
    "opt.channels.stereo": ("Stereo", "Stereo"),
    "opt.normalize": ("Lautstärke normalisieren", "Normalize loudness"),
    "opt.normalize.off": ("Aus", "Off"),
    "opt.normalize.streaming": ("−14 LUFS (Streaming, Musik)", "−14 LUFS (streaming, music)"),
    "opt.normalize.podcast": ("−16 LUFS (Podcast, Sprache)", "−16 LUFS (podcast, speech)"),
    "opt.normalize.broadcast": ("−23 LUFS (Rundfunk, EBU R128)", "−23 LUFS (broadcast, EBU R128)"),
    "opt.fade_in": ("Einblenden", "Fade in"),
    "opt.fade_out": ("Ausblenden", "Fade out"),
    # --- image ---
    "opt.resize": ("Größe", "Size"),
    "opt.resize.percent": ("Prozent", "Percent"),
    "opt.resize.fit": ("Maximal Breite × Höhe", "Fit within width × height"),
    "opt.percent": ("Prozent", "Percent"),
    "opt.max_width": ("Max. Breite", "Max. width"),
    "opt.max_height": ("Max. Höhe", "Max. height"),
    "opt.background": ("Hintergrund für Transparenz", "Background for transparency"),
    "opt.lossless": ("Verlustfrei", "Lossless"),
    # --- documents ---
    "opt.allow_resources": ("Lokale Bilder einbinden", "Embed local images"),
    "opt.allow_resources_help": (
        "Bindet lokale Bilder ein, auf die das Dokument verweist (Pandoc darf dafür Dateien "
        "im Ordner lesen). Internetzugriffe bleiben blockiert.",
        "Embeds local images the document refers to (Pandoc may read files next to it). "
        "Internet access stays blocked.",
    ),
    # --- data ---
    "opt.delimiter": ("Trennzeichen", "Delimiter"),
    "opt.delimiter.comma": ("Komma ,", "Comma ,"),
    "opt.delimiter.semicolon": ("Semikolon ;", "Semicolon ;"),
    "opt.delimiter.tab": ("Tabulator", "Tab"),
    "opt.excel_bom": ("Excel-kompatibel (UTF-8 mit BOM)", "Excel compatible (UTF-8 with BOM)"),
    "opt.sheet": ("Tabellenblatt", "Sheet"),
    "opt.sheet_help": ("Leer = erstes Blatt", "Empty = first sheet"),
    "opt.indent": ("Einrückung", "Indentation"),
    "opt.indent.compact": ("Kompakt", "Compact"),
    "opt.detect_numbers": ("Zahlen erkennen", "Detect numbers"),
    # --- integration ---
    "integration.menu_label": ("Mit OmniConverter umwandeln", "Convert with OmniConverter"),
    "integration.comment": (
        "Videos, Musik, Bilder, Dokumente und Daten umwandeln – lokal und privat",
        "Convert videos, music, images, documents and data – locally and privately",
    ),
    # --- GUI ---
    "gui.drop.title": ("Datei hierher ziehen", "Drop a file here"),
    "gui.drop.hint": ("oder klicken, um Dateien auszuwählen", "or click to choose files"),
    "gui.drop.dialog": ("Dateien zum Umwandeln auswählen", "Choose files to convert"),
    "gui.drop.supported": ("Unterstützte Dateien", "Supported files"),
    "gui.drop.all_files": ("Alle Dateien", "All files"),
    "gui.privacy_footer": (
        "🔒 100 % lokal – nichts verlässt deinen Rechner",
        "🔒 100 % local – nothing leaves your computer",
    ),
    "gui.back": ("Zurück", "Back"),
    "gui.n_files": ("{n} Dateien", "{n} files"),
    "gui.convert_to": ("Umwandeln in", "Convert to"),
    "gui.needs_tool": ("Benötigt {tools}. Installieren mit:", "Needs {tools}. Install with:"),
    "gui.missing_hint": (
        "Ausgegraute Formate benötigen {tools}. <a href='settings'>Einstellungen</a>",
        "Greyed-out formats need {tools}. <a href='settings'>Settings</a>",
    ),
    "gui.options": ("Optionen", "Options"),
    "gui.advanced": ("Erweitert", "Advanced"),
    "gui.save_to": ("Speichern unter:", "Save to:"),
    "gui.change": ("Ändern …", "Change …"),
    "gui.save_as": ("Speichern unter", "Save as"),
    "gui.choose_folder": ("Zielordner wählen", "Choose target folder"),
    "gui.next_to_originals": ("Neben den Originaldateien", "Next to the original files"),
    "gui.convert": ("Umwandeln", "Convert"),
    "gui.converting": ("Wird umgewandelt …", "Converting …"),
    "gui.cancel": ("Abbrechen", "Cancel"),
    "gui.cancelling": ("Wird abgebrochen …", "Cancelling …"),
    "gui.cancelled": ("Umwandlung abgebrochen.", "Conversion cancelled."),
    "gui.busy": (
        "Bitte warten, bis die laufende Umwandlung fertig ist.",
        "Please wait for the running conversion to finish.",
    ),
    "gui.skipped": ("{n} Datei(en) übersprungen (nicht unterstützt).", "{n} file(s) skipped."),
    "gui.done": ("Fertig!", "Done!"),
    "gui.done_many": ("{n} Dateien gespeichert in {folder}", "{n} files saved to {folder}"),
    "gui.failed": ("Umwandlung fehlgeschlagen", "Conversion failed"),
    "gui.partial": ("{ok} von {n} Dateien umgewandelt", "{ok} of {n} files converted"),
    "gui.show_details": ("Details anzeigen", "Show details"),
    "gui.open": ("Öffnen", "Open"),
    "gui.show_in_folder": ("Im Ordner anzeigen", "Show in folder"),
    "gui.back_to_options": ("Zurück zu den Optionen", "Back to options"),
    "gui.new_file": ("Weitere Datei", "Another file"),
    "gui.settings.title": ("Einstellungen", "Settings"),
    "gui.settings.language": ("Sprache", "Language"),
    "gui.settings.language_auto": ("Systemsprache", "System language"),
    "gui.settings.restart": ("Wirkt nach einem Neustart.", "Takes effect after a restart."),
    "gui.settings.tools": ("Externe Programme", "External programs"),
    "gui.settings.tools_hint": (
        "OmniConverter nutzt installierte Programme und lädt selbst nichts herunter.",
        "OmniConverter uses installed programs and never downloads anything itself.",
    ),
    "gui.settings.not_found": ("nicht gefunden", "not found"),
    "gui.settings.browse": ("Auswählen …", "Browse …"),
    "gui.settings.reset": ("Zurücksetzen", "Reset"),
    "gui.settings.rescan": ("Erneut suchen", "Search again"),
    "gui.settings.context_menu": ("Kontextmenü im Dateimanager", "File manager context menu"),
    "gui.settings.menu_on": (
        "„Mit OmniConverter umwandeln“ ist eingerichtet.",
        "“Convert with OmniConverter” is installed.",
    ),
    "gui.settings.menu_off": ("Nicht eingerichtet.", "Not installed."),
    "gui.settings.menu_install": ("Einrichten", "Install"),
    "gui.settings.menu_remove": ("Entfernen", "Remove"),
    "gui.settings.privacy": (
        "Datenschutz: Alle Umwandlungen laufen auf deinem Rechner. Es gibt keine Uploads, "
        "keine Telemetrie und keine Update-Abfragen; es wird kein Verlauf gespeichert.",
        "Privacy: all conversions run on your computer. No uploads, no telemetry, no update "
        "checks, and no history is stored.",
    ),
    # --- CLI ---
    "cli.description": (
        "Wandelt Dateien lokal um – Video, Audio, Bilder, Dokumente und Daten.",
        "Converts files locally – video, audio, images, documents and data.",
    ),
    "cli.epilog": (
        "Beispiele:\n"
        "  omniconvert video.mov --to mp4\n"
        "  omniconvert clip.mp4 --to gif -s start=0:05 -s end=0:12 -s width=640\n"
        "  omniconvert podcast.wav --to mp3 -s normalize=podcast\n"
        "  omniconvert --list bericht.docx\n"
        "  omniconvert --options clip.mp4 --to gif",
        "Examples:\n"
        "  omniconvert video.mov --to mp4\n"
        "  omniconvert clip.mp4 --to gif -s start=0:05 -s end=0:12 -s width=640\n"
        "  omniconvert podcast.wav --to mp3 -s normalize=podcast\n"
        "  omniconvert --list report.docx\n"
        "  omniconvert --options clip.mp4 --to gif",
    ),
    "cli.help.to": ("Zielformat, z. B. mp4, mp3, png, pdf, xlsx", "target format, e.g. mp4"),
    "cli.help.output": (
        "Ausgabedatei oder -ordner (Standard: neben der Quelle)",
        "output file or folder (default: next to the source)",
    ),
    "cli.help.set": ("Option setzen, mehrfach möglich", "set an option, repeatable"),
    "cli.help.overwrite": (
        "vorhandene Ausgabedatei überschreiben",
        "overwrite an existing output file",
    ),
    "cli.help.list": ("mögliche Zielformate anzeigen", "list possible target formats"),
    "cli.help.options": ("Optionen für --to anzeigen", "show the options for --to"),
    "cli.help.tools": ("gefundene externe Werkzeuge anzeigen", "show detected external tools"),
    "cli.help.integrate": (
        "Kontextmenü im Dateimanager einrichten/entfernen",
        "add/remove the file manager context menu",
    ),
    "cli.help.quiet": ("keine Fortschrittsausgabe", "no progress output"),
    "cli.error": ("Fehler", "Error"),
    "cli.cancelled": ("Abgebrochen.", "Cancelled."),
    "cli.error.no_files": ("Keine Datei angegeben.", "No file given."),
    "cli.error.no_target": ("Bitte ein Zielformat mit --to angeben.", "Please give --to."),
    "cli.error.unknown_format": ("Unbekanntes Format: {fmt}", "Unknown format: {fmt}"),
    "cli.error.bad_set": (
        "Ungültige Option „{value}“ (erwartet KEY=VALUE).",
        "Invalid option “{value}” (expected KEY=VALUE).",
    ),
    "cli.error.output_dir": (
        "Bei mehreren Dateien muss --output ein Ordner sein.",
        "With several files --output must be a folder.",
    ),
    "cli.error.exists": (
        "„{path}“ existiert bereits (--overwrite zum Überschreiben).",
        "“{path}” already exists (use --overwrite).",
    ),
    "cli.needs": ("benötigt {tools}", "needs {tools}"),
    "cli.no_options": ("Keine Optionen.", "No options."),
    "cli.tool_missing": ("nicht gefunden – installieren mit", "not found – install with"),
    "cli.integration_on": ("Kontextmenü ist eingerichtet.", "Context menu is installed."),
    "cli.integration_off": ("Kontextmenü ist nicht eingerichtet.", "Context menu not installed."),
    "cli.integration_installed": ("Kontextmenü eingerichtet.", "Context menu installed."),
    "cli.integration_removed": ("Kontextmenü entfernt.", "Context menu removed."),
}


def system_language() -> str:
    """``de`` or ``en`` derived from the OS locale."""
    candidates = [os.environ.get(v, "") for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    with contextlib.suppress(ValueError):
        candidates.append(locale.getlocale()[0] or "")
    for value in candidates:
        low = value.lower()
        if low.startswith(("de", "german")):
            return "de"
        if low and low not in ("c", "posix", "c.utf-8"):
            return "en"
    return "en"


def set_language(lang: str | None) -> None:
    """Set ``de``/``en``; ``None``/``auto`` follows the system."""
    global _language
    _language = lang if lang in LANGUAGES else None


def current_language() -> str:
    return _language or system_language()


def t(key: str, **kwargs: object) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry[LANGUAGES.index(current_language())]
    return text.format(**kwargs) if kwargs else text
