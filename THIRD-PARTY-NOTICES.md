# Drittanbieter-Lizenzen / Third-party notices

OmniConverter selbst steht unter der [MIT-Lizenz](LICENSE). Die fertigen Pakete (Windows-
Installer, portable ZIP/tar.gz, AppImage, `.deb`) enthalten außerdem die unten aufgeführten
Komponenten. Ihre vollständigen Lizenztexte liegen in jedem Paket im Ordner **`licenses/`**
(unter Linux bei der `.deb` in `/opt/omniconverter/licenses/`), erzeugt von
`packaging/licenses.py` aus den Lizenzdateien der installierten Wheels.

*OmniConverter itself is MIT licensed. The release packages also contain the components below;
their full license texts are in the `licenses/` folder of every package.*

## Gesamtlizenz der Pakete / License of the packages as a whole

Die HEIC-Unterstützung (pillow-heif) bringt den Encoder **x265** mit, der unter der
**GPL-2.0** steht. Deshalb gelten für die fertigen Pakete als Ganzes zusätzlich die Bedingungen
der GPL-2.0 (Text in `licenses/pillow-heif-*/GPL-2.0.txt`). Der Quellcode von OmniConverter ist
[hier](https://github.com/Paragrimm/OmniConverter) verfügbar, der aller Bibliotheken unter den
unten genannten Links. Wer OmniConverter aus dem Quellcode installiert (`pip install`), bekommt
die Bibliotheken über PyPI und damit deren jeweilige Lizenz.

*Because the bundled HEIC encoder x265 is GPL-2.0, the release packages as a whole are also
subject to the GPL-2.0. All sources are available at the links below.*

## Komponenten / Components

| Komponente | Wofür | Lizenz | Quelle |
|---|---|---|---|
| Python | Laufzeit | PSF-2.0 | https://www.python.org |
| Qt 6 (über PySide6-Essentials, shiboken6) | Oberfläche | LGPL-3.0 | https://www.qt.io, https://code.qt.io/cgit/pyside/pyside-setup.git |
| Pillow (mit libjpeg-turbo, libpng, zlib, libtiff, libwebp, libavif, FreeType, HarfBuzz, Little CMS, OpenJPEG, brotli, zstd, xz, libxcb) | Bilder | MIT-CMU (+ Lizenzen der Bibliotheken, im Pillow-Lizenztext enthalten) | https://github.com/python-pillow/Pillow |
| pillow-heif (mit libheif, libde265, x265) | HEIC | BSD-3-Clause; libheif/libde265 LGPL-3.0; x265 GPL-2.0 | https://github.com/bigcat88/pillow_heif |
| pypdfium2 (mit PDFium und dessen Bibliotheken: FreeType, ICU, Little CMS, libjpeg-turbo, OpenJPEG, libpng, libtiff, zlib, abseil, …) | PDF | Apache-2.0 / BSD-3-Clause (+ Lizenzen der Bibliotheken) | https://github.com/pypdfium2-team/pypdfium2, https://pdfium.googlesource.com/pdfium/ |
| zxing-cpp | QR-Codes/Barcodes lesen | Apache-2.0 | https://github.com/zxing-cpp/zxing-cpp |
| segno | QR-Codes erzeugen | BSD-3-Clause | https://github.com/heuer/segno |
| NumPy | Textur-/Noise-Maps | BSD-3-Clause (+ Lizenzen enthaltener Teile) | https://numpy.org |
| trimesh | 3D-Modelle | MIT | https://github.com/mikedh/trimesh |
| openpyxl, et-xmlfile | Excel | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| PyYAML | YAML | MIT | https://pyyaml.org |
| tomli-w | TOML | MIT | https://github.com/hukkin/tomli-w |
| platformdirs | Einstellungsordner | MIT | https://github.com/tox-dev/platformdirs |
| Owlish Emotes (RoamingOwl) | Eulen-Animationen | CC BY 4.0 | https://roamingowl.itch.io/owlish-emotes |

Qt wird dynamisch gelinkt (eigene `.dll`/`.so`-Dateien im Paket) und lässt sich gegen eine
andere, kompatible Qt-Version austauschen, wie es die LGPL-3.0 verlangt. Das Paket wird mit
[PyInstaller](https://pyinstaller.org) gebaut; dessen Bootloader steht unter der GPL-2.0 mit
einer Ausnahme, die die Weitergabe ohne weitere Bedingungen erlaubt.

## Nicht enthalten / Not included

FFmpeg, Pandoc, LibreOffice und Blender liefert OmniConverter **nicht** mit. Es ruft sie als
eigenständige, bereits installierte Programme auf; es gelten ihre eigenen Lizenzen.
