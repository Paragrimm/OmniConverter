"""Build a portable OmniConverter folder with PyInstaller and zip it into ``dist/``."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from omniconverter import __version__  # noqa: E402


def main() -> int:
    dist = ROOT / "dist"
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(dist), "--workpath", str(ROOT / "build"),
         str(ROOT / "packaging" / "omniconverter.spec")],
        check=True,
    )
    folder = dist / "OmniConverter"
    system = {"Windows": "windows", "Linux": "linux"}.get(platform.system(), "other")
    archive = dist / f"OmniConverter-{__version__}-{system}-{platform.machine().lower()}"
    shutil.make_archive(str(archive), "zip", root_dir=dist, base_dir=folder.name)
    print(f"Built {archive}.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
