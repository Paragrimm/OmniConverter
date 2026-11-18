"""Collect the license texts of everything a packaged build contains.

    python packaging/licenses.py DEST     # writes DEST/licenses/

``build.py`` runs this for every package. The result holds OmniConverter's own license, the
overview ``THIRD-PARTY-NOTICES.md``, and one folder per bundled Python distribution with the
license files from its wheel (including the libraries bundled inside the wheels, e.g. PDFium
or libjpeg). Qt/PySide6 wheels carry no license files, so the LGPL/GPL texts are added from
``packaging/licenses/``, and Python's own license comes from the interpreter that builds.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import shutil
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXTS = ROOT / "packaging" / "licenses"
LICENSE_FILE = re.compile(r"(^|/)(licen[cs]e|copying|notice|authors)[^/]*$|/licenses/",
                          re.IGNORECASE)
# Wheels without license files: the license texts their metadata names.
EXTRA_TEXTS = {
    "pyside6-essentials": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "shiboken6": ("LGPL-3.0.txt", "GPL-3.0.txt"),
}
# Wheels whose bundled libraries need a license text the wheel only refers to.
ALSO = {
    "pillow-heif": ("GPL-2.0.txt", "LGPL-3.0.txt"),  # x265 (GPLv2), libheif/libde265 (LGPLv3)
}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def bundled_distributions(root: str = "omniconverter") -> list[md.Distribution]:
    """*root* and everything it needs at runtime (no extras), each once."""
    from packaging.requirements import Requirement

    found: dict[str, md.Distribution] = {}

    def walk(name: str) -> None:
        key = normalize(name)
        if key in found:
            return
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            raise SystemExit(f"{name} is not installed – install the project first") from None
        found[key] = dist
        for line in dist.requires or []:
            req = Requirement(line)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                walk(req.name)

    walk(root)
    return [d for key, d in sorted(found.items()) if key != normalize(root)]


def license_files(dist: md.Distribution) -> list[Path]:
    return [Path(str(dist.locate_file(f))) for f in dist.files or []
            if LICENSE_FILE.search(str(f).replace("\\", "/")) and not str(f).endswith(".py")]


def python_license() -> Path | None:
    for folder in (Path(sysconfig.get_path("stdlib")), Path(sys.base_prefix)):
        candidate = folder / "LICENSE.txt"
        if candidate.is_file():
            return candidate
    return None


def collect(dest: Path) -> Path:
    """Write ``dest/licenses`` (replacing an older one) and return it."""
    out = dest / "licenses"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", out / "OmniConverter-LICENSE.txt")
    shutil.copyfile(ROOT / "THIRD-PARTY-NOTICES.md", out / "THIRD-PARTY-NOTICES.md")
    emotes = ROOT / "src" / "omniconverter" / "resources" / "emotes" / "LICENSE.txt"
    shutil.copyfile(emotes, out / "Owlish-Emotes-CC-BY-4.0.txt")
    python = python_license()
    if python is None:
        raise SystemExit("Python's LICENSE.txt not found")
    shutil.copyfile(python, out / f"Python-{sys.version_info.major}.{sys.version_info.minor}"
                                  "-LICENSE.txt")

    missing = []
    for dist in bundled_distributions():
        key = normalize(dist.metadata["Name"])
        folder = out / f"{dist.metadata['Name']}-{dist.version}"
        folder.mkdir()
        files = license_files(dist)
        for path in files:
            # Keep the wheel's sub-folders (pypdfium2 has one file per bundled library).
            parts = path.parts
            relative = Path(*parts[parts.index("licenses") + 1:]) if "licenses" in parts \
                else Path(path.name)
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        for name in (*EXTRA_TEXTS.get(key, ()), *ALSO.get(key, ())):
            shutil.copyfile(TEXTS / name, folder / name)
        if not files and key not in EXTRA_TEXTS:
            missing.append(key)
    if missing:
        raise SystemExit("no license files found for: " + ", ".join(missing)
                         + " – add their texts to packaging/licenses.py")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(collect(Path(sys.argv[1])))
