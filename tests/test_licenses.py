"""Every bundled component is named in the notices and its license text gets into packages."""

import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_collector():
    spec = importlib.util.spec_from_file_location("omni_licenses",
                                                  ROOT / "packaging" / "licenses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_dependency_is_named_in_the_notices():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8").lower()
    names = [re.split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0] for dep in
             project["project"]["dependencies"]]
    missing = [n for n in names if n.lower().removesuffix("-essentials") not in notices]
    assert missing == []


def test_license_texts_are_collected(tmp_path):
    collector = load_collector()
    out = collector.collect(tmp_path)
    assert (out / "THIRD-PARTY-NOTICES.md").is_file()
    assert (out / "OmniConverter-LICENSE.txt").is_file()
    assert any(out.glob("Python-*-LICENSE.txt"))
    folders = {p.name.rsplit("-", 1)[0].lower().replace("_", "-") for p in out.iterdir()
               if p.is_dir()}
    assert {"pypdfium2", "zxing-cpp", "pillow", "pillow-heif", "pyside6-essentials"} <= folders
    qt = next(out.glob("PySide6_Essentials-*"))
    assert "LESSER GENERAL PUBLIC LICENSE" in (qt / "LGPL-3.0.txt").read_text(encoding="utf-8")
    heif = next(out.glob("pillow_heif-*"))
    assert (heif / "GPL-2.0.txt").is_file()  # x265
    pdfium = next(out.glob("pypdfium2-*"))
    assert any("pdfium" in p.name.lower() for p in pdfium.rglob("*.txt"))
