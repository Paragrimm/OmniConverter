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
    "category.texture": ("Textur-Maps", "Texture maps"),
    "category.qr": ("QR-Code", "QR code"),
    "category.model": ("3D-Modell", "3D model"),
    "category.generator": ("Erzeugt", "Generated"),
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
        "Kein Zugriff auf „{path}“ (fehlende Rechte oder von einem anderen Programm geöffnet).",
        "Access to “{path}” denied (missing permissions or opened by another program).",
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
    "error.companion_exists": (
        "„{name}“ existiert bereits und wird nicht überschrieben.",
        "“{name}” already exists and is not overwritten.",
    ),
    "error.qr_too_large": (
        "Zu viel Inhalt für einen QR-Code ({size} Bytes). Mit dieser Fehlerkorrektur passen "
        "höchstens {limit} Bytes, mit Stufe L bis zu {max}.",
        "Too much content for a QR code ({size} bytes). With this error correction at most "
        "{limit} bytes fit, with level L up to {max}.",
    ),
    "error.qr_empty": ("Der QR-Code hätte keinen Inhalt.", "The QR code would be empty."),
    "error.qr_no_url": (
        "In der Verknüpfung steht keine Adresse.",
        "The shortcut contains no address.",
    ),
    "error.qr_failed": (
        "Der QR-Code konnte nicht gespeichert werden.",
        "Could not save the QR code.",
    ),
    "error.model_failed": (
        "Das 3D-Modell konnte nicht umgewandelt werden.",
        "Could not convert the 3D model.",
    ),
    "error.model_empty": (
        "Das 3D-Modell enthält keine Geometrie.",
        "The 3D model contains no geometry.",
    ),
    "error.blender_failed": (
        "Blender konnte das Modell nicht umwandeln.",
        "Blender could not convert the model.",
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
    "opt.colors.all": ("Alle (verlustfrei)", "All (lossless)"),
    "opt.colors_help": (
        "Weniger Farben machen PNGs deutlich kleiner (Palettenbild). Für Fotos reichen oft "
        "256, für Logos und Screenshots 64 oder weniger. Animierte PNGs behalten alle Farben.",
        "Fewer colors make PNGs much smaller (palette image). Photos often look fine with 256, "
        "logos and screenshots with 64 or fewer. Animated PNGs keep all colors.",
    ),
    "opt.png_dither_help": (
        "Mischt Farbpunkte gegen sichtbare Farbstufen, die Datei wird etwas größer. Wirkt nur "
        "bei Bildern ohne Transparenz.",
        "Mixes dots of color against visible banding; the file gets a little larger. Only for "
        "images without transparency.",
    ),
    "opt.dither.none": ("Keins (flächig)", "None (flat)"),
    "opt.dither.bayer": ("Bayer (klein)", "Bayer (small)"),
    "opt.dither.floyd_steinberg": ("Floyd-Steinberg (weich)", "Floyd–Steinberg (smooth)"),
    "opt.dither.sierra2_4a": ("Sierra (ausgewogen)", "Sierra (balanced)"),
    "opt.loop": ("Wiederholen", "Loop"),
    "opt.loop.forever": ("Endlos", "Forever"),
    "opt.loop.once": ("Einmal abspielen", "Play once"),
    "opt.keep_transparency": ("Transparenz erhalten", "Keep transparency"),
    "opt.keep_transparency_help": (
        "Durchsichtige Stellen bleiben durchsichtig (VP9 mit Alphakanal, z. B. für Webseiten "
        "und OBS).",
        "Transparent areas stay transparent (VP9 with alpha channel, e.g. for websites and "
        "OBS).",
    ),
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
    # --- texture maps ---
    "opt.tex_strength": ("Stärke", "Strength"),
    "opt.tex_strength_help": (
        "Wie stark die Oberfläche geneigt wirkt.",
        "How steep the surface appears.",
    ),
    "opt.tex_blur": ("Glättung", "Smoothing"),
    "opt.tex_blur_help": (
        "Zeichnet vorher weich, damit Bildrauschen keine Krümel erzeugt.",
        "Blurs first, so image noise does not turn into bumps.",
    ),
    "opt.tex_invert_height": ("Höhe umkehren", "Invert height"),
    "opt.tex_invert_height_help": (
        "Normal: Helles ist erhaben. Umgekehrt: Dunkles ist erhaben.",
        "Normally bright means raised; inverted, dark means raised.",
    ),
    "opt.tex_convention": ("Grün-Kanal", "Green channel"),
    "opt.tex_convention.opengl": (
        "OpenGL (Y+): Blender, Unity, Godot",
        "OpenGL (Y+): Blender, Unity, Godot",
    ),
    "opt.tex_convention.directx": (
        "DirectX (Y−): Unreal, 3ds Max",
        "DirectX (Y−): Unreal, 3ds Max",
    ),
    "opt.tex_brightness": ("Helligkeit", "Brightness"),
    "opt.tex_contrast": ("Kontrast", "Contrast"),
    "opt.tex_invert": ("Umkehren (Roughness-Map)", "Invert (roughness map)"),
    "opt.tex_invert_help": (
        "Helle Stellen werden matt statt glänzend – das ergibt eine Roughness-Map für PBR.",
        "Bright areas become matte instead of shiny – a roughness map for PBR.",
    ),
    "opt.seamless": ("Nahtlos kachelbar", "Seamless (tileable)"),
    "opt.seamless_help": (
        "Die Ränder passen aneinander, wenn die Textur wiederholt wird.",
        "The edges match when the texture is repeated.",
    ),
    # --- noise ---
    "opt.noise_kind": ("Art", "Type"),
    "opt.noise_kind.fbm": ("Wolken (fraktal)", "Clouds (fractal)"),
    "opt.noise_kind.perlin": ("Perlin (weich)", "Perlin (smooth)"),
    "opt.noise_kind.ridged": ("Gebirge (Grate)", "Ridges"),
    "opt.noise_kind.worley": ("Zellen (Worley)", "Cells (Worley)"),
    "opt.noise_kind.white": ("Weißes Rauschen", "White noise"),
    "opt.seed": ("Seed", "Seed"),
    "opt.seed_help": (
        "Gleicher Seed und gleiche Einstellungen ergeben immer dasselbe Bild.",
        "The same seed and settings always give the same image.",
    ),
    "opt.height": ("Höhe", "Height"),
    "opt.noise_scale": ("Strukturgröße", "Feature size"),
    "opt.noise_scale_help": (
        "Ungefähre Größe der gröbsten Strukturen.",
        "Approximate size of the coarsest features.",
    ),
    "opt.noise_octaves": ("Detailstufen", "Octaves"),
    "opt.noise_octaves_help": (
        "Wie viele immer feinere Ebenen übereinanderliegen.",
        "How many ever finer layers are added.",
    ),
    "opt.noise_roughness": ("Rauheit", "Roughness"),
    "opt.noise_color_low": ("Farbe dunkel", "Dark color"),
    "opt.noise_color_high": ("Farbe hell", "Light color"),
    # --- QR codes ---
    "opt.qr_error_correction": ("Fehlerkorrektur", "Error correction"),
    "opt.qr_error_correction.l": ("L – 7 % (passt am meisten)", "L – 7 % (fits the most)"),
    "opt.qr_error_correction.m": ("M – 15 %", "M – 15 %"),
    "opt.qr_error_correction.q": ("Q – 25 %", "Q – 25 %"),
    "opt.qr_error_correction.h": ("H – 30 % (am robustesten)", "H – 30 % (most robust)"),
    "opt.qr_error_correction_help": (
        "Höhere Stufen bleiben lesbar, wenn der Code verschmutzt oder verdeckt ist, fassen "
        "aber weniger.",
        "Higher levels stay readable when the code is dirty or covered, but hold less.",
    ),
    "opt.qr_size": ("Größe", "Size"),
    "opt.qr_size_help": (
        "Ungefähre Kantenlänge. Jedes Modul bekommt ganze Pixel, damit der Code scharf bleibt.",
        "Approximate edge length. Every module gets whole pixels so the code stays sharp.",
    ),
    "opt.qr_dark": ("Farbe", "Color"),
    "opt.qr_light": ("Hintergrund", "Background"),
    "opt.qr_transparent": ("Transparenter Hintergrund", "Transparent background"),
    "opt.qr_border": ("Rand", "Quiet zone"),
    "opt.qr_border_help": (
        "Leerer Rand in Modulen. Scanner brauchen meist 4.",
        "Empty margin in modules. Scanners usually need 4.",
    ),
    # --- 3D models ---
    "opt.model_scale": ("Skalierung", "Scale"),
    "opt.model_scale.none": ("Unverändert", "Unchanged"),
    "opt.model_scale.cm_to_m": ("cm → m (× 0,01)", "cm → m (× 0.01)"),
    "opt.model_scale.m_to_cm": ("m → cm (× 100)", "m → cm (× 100)"),
    "opt.model_scale.mm_to_m": ("mm → m (× 0,001)", "mm → m (× 0.001)"),
    "opt.model_scale.m_to_mm": ("m → mm (× 1000)", "m → mm (× 1000)"),
    "opt.model_scale.inch_to_mm": ("Zoll → mm (× 25,4)", "inch → mm (× 25.4)"),
    "opt.model_scale_help": (
        "Rechnet die Einheit um, wenn das Modell im Zielprogramm zu groß oder zu klein ist.",
        "Converts the unit if the model is too large or too small in the target program.",
    ),
    "opt.model_up_axis": ("Oben-Achse", "Up axis"),
    "opt.model_up_axis.keep": ("Unverändert", "Unchanged"),
    "opt.model_up_axis.y_to_z": (
        "Y oben → Z oben (z. B. 3D-Druck)",
        "Y up → Z up (e.g. 3D printing)",
    ),
    "opt.model_up_axis.z_to_y": (
        "Z oben → Y oben (z. B. glTF, Spiele)",
        "Z up → Y up (e.g. glTF, games)",
    ),
    "opt.model_up_axis_help": (
        "Dreht das Modell um 90°, falls es im Zielprogramm auf der Seite liegt.",
        "Rotates the model by 90° if it lies on its side in the target program.",
    ),
    "opt.model_ascii": ("Als Text speichern (ASCII)", "Save as text (ASCII)"),
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
    "gui.qr_placeholder": (
        "Link oder Text für einen QR-Code …",
        "Link or text for a QR code …",
    ),
    "gui.qr_button": ("QR-Code", "QR code"),
    "gui.noise_button": ("Noise-Map erzeugen", "Create noise map"),
    "gui.qr_content": ("Inhalt des QR-Codes", "QR code content"),
    "gui.qr_bytes": ("{n} Bytes", "{n} bytes"),
    "gui.generated": ("Wird neu erzeugt, ohne Quelldatei", "Generated, no source file"),
    "gui.randomize": ("Zufälligen Wert würfeln", "Roll a random value"),
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
    "gui.back_to_options": ("← Zurück zu den Optionen", "← Back to options"),
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
        "Wandelt Dateien lokal um – Video, Audio, Bilder, 3D-Modelle, Dokumente und Daten – "
        "und erzeugt QR-Codes, Textur- und Noise-Maps.",
        "Converts files locally – video, audio, images, 3D models, documents and data – and "
        "creates QR codes, texture and noise maps.",
    ),
    "cli.epilog": (
        "Beispiele:\n"
        "  omniconvert video.mov --to mp4\n"
        "  omniconvert clip.mp4 --to gif -s start=0:05 -s end=0:12 -s width=640\n"
        "  omniconvert podcast.wav --to mp3 -s normalize=podcast\n"
        "  omniconvert --list bericht.docx\n"
        "  omniconvert --options clip.mp4 --to gif\n"
        "  omniconvert --text https://example.com --to qr\n"
        "  omniconvert --generate noise --to png -s seed=42 -s width=2048\n"
        "  omniconvert stein.jpg --to normal-map\n"
        "  omniconvert modell.fbx --to glb",
        "Examples:\n"
        "  omniconvert video.mov --to mp4\n"
        "  omniconvert clip.mp4 --to gif -s start=0:05 -s end=0:12 -s width=640\n"
        "  omniconvert podcast.wav --to mp3 -s normalize=podcast\n"
        "  omniconvert --list report.docx\n"
        "  omniconvert --options clip.mp4 --to gif\n"
        "  omniconvert --text https://example.com --to qr\n"
        "  omniconvert --generate noise --to png -s seed=42 -s width=2048\n"
        "  omniconvert stone.jpg --to normal-map\n"
        "  omniconvert model.fbx --to glb",
    ),
    "cli.help.to": (
        "Zielformat, z. B. mp4, mp3, png, pdf, xlsx, glb, qr, normal-map",
        "target format, e.g. mp4, mp3, png, glb, qr, normal-map",
    ),
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
    "cli.help.text": (
        "Link oder Text als Quelle, z. B. für --to qr",
        "link or text as source, e.g. for --to qr",
    ),
    "cli.help.generate": (
        "ohne Quelldatei erzeugen, z. B. noise (mit --to png)",
        "generate without a source file, e.g. noise (with --to png)",
    ),
    "cli.error.source_conflict": (
        "Entweder Dateien, --text oder --generate angeben.",
        "Give either files, --text or --generate.",
    ),
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
