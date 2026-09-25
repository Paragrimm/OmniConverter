## Download

| System | Datei | Hinweis |
|---|---|---|
| **Windows** | `OmniConverter-…-windows-x64-setup.exe` | Installer, ohne Admin-Rechte. Richtet auf Wunsch das Kontextmenü „Mit OmniConverter umwandeln“ ein, die Deinstallation entfernt es wieder. |
| Windows portabel | `OmniConverter-…-windows-x64-portable.zip` | Entpacken, `OmniConverter.exe` starten. Die Einstellungen liegen im eigenen Ordner, geht also auch vom USB-Stick. |
| **Linux** (alle Distributionen) | `OmniConverter-…-x86_64.AppImage` | `chmod +x OmniConverter-*.AppImage` und starten. Kontextmenü: `./OmniConverter-*.AppImage --integrate install` |
| Debian / Ubuntu | `omniconverter_…_amd64.deb` | `sudo apt install ./omniconverter_*_amd64.deb` – bringt FFmpeg, Pandoc und LibreOffice als empfohlene Pakete gleich mit |
| Linux portabel | `OmniConverter-…-linux-x86_64-portable.tar.gz` | Entpacken und `OmniConverter/OmniConverter` starten |

Für Video/Audio, Dokumente und Office-Formate nutzt OmniConverter installierte Programme:
FFmpeg (`winget install Gyan.FFmpeg`), Pandoc (`winget install JohnMacFarlane.Pandoc`) und
LibreOffice (`winget install TheDocumentFoundation.LibreOffice`). Bilder und Daten
funktionieren ohne Zusatzprogramme.

Die Windows-Dateien sind (noch) nicht signiert. Die SmartScreen-Warnung lässt sich mit
„Weitere Informationen“ → „Trotzdem ausführen“ überspringen. Prüfsummen stehen in
`SHA256SUMS.txt`.

Die Linux-Pakete laufen ab glibc 2.35 (Ubuntu 22.04, Debian 12, Fedora 36 und neuer).
