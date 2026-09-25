"""Check a packaged build with real conversions.

    python packaging/smoke_test.py dist/OmniConverter/omniconvert
    python packaging/smoke_test.py dist/release/OmniConverter-0.1.0-x86_64.AppImage --gui
    python packaging/smoke_test.py omniconvert            # installed .deb (on PATH)

The command must understand the CLI (``--to`` …). With ``--gui`` it (or ``--gui-command``) is
also started without arguments (offscreen) and must still be running after a few seconds.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'✔' if ok else '✘'} {label}{f' – {detail}' if detail else ''}", flush=True)
    if not ok:
        raise SystemExit(1)


def run(cmd: list[str], *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*cmd, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def convert(cmd: list[str], src: Path, target: str, *sets: str) -> Path:
    args = [str(src), "--to", target, "-q"]
    for s in sets:
        args += ["-s", s]
    result = run(cmd, *args)
    out = src.with_suffix(f".{target}")
    detail = (result.stderr or result.stdout).strip()[-800:]
    check(f"{src.name} → {out.name}", result.returncode == 0 and out.is_file()
          and out.stat().st_size > 0, "" if result.returncode == 0 else detail)
    return out


def stop(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        import signal

        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", help="packaged omniconvert / OmniConverter / .AppImage")
    parser.add_argument("--gui", action="store_true", help="also start the GUI offscreen")
    parser.add_argument("--gui-command", help="GUI executable if it differs from COMMAND")
    args = parser.parse_args()

    exe = shutil.which(args.command) or str(Path(args.command).resolve())
    cmd = [exe]
    env_note = os.environ.get("APPIMAGE_EXTRACT_AND_RUN")
    print(f"Testing {exe}" + (" (APPIMAGE_EXTRACT_AND_RUN=1)" if env_note else ""))

    result = run(cmd, "--version")
    check("--version", result.returncode == 0, result.stdout.strip() or result.stderr.strip())
    result = run(cmd, "--tools")
    check("--tools", result.returncode == 0)
    print(result.stdout.rstrip())
    # Decide from the environment, not from the output: if the packaged app fails to find or
    # run a tool that is installed, the conversions below must fail.
    have_ffmpeg = bool(shutil.which("ffmpeg"))
    have_pandoc = bool(shutil.which("pandoc"))

    with tempfile.TemporaryDirectory(prefix="omni-smoke-") as tmp:
        work = Path(tmp)
        os.environ["OMNICONVERTER_CONFIG_DIR"] = str(work / "config")

        # Images (Pillow, pillow-heif and libavif are bundled)
        png = work / "picture.png"
        png.write_bytes(_tiny_png())
        for target in ("jpg", "webp", "avif", "heic", "ico", "pdf"):
            convert(cmd, png, target)

        # Data (pure Python, openpyxl, PyYAML)
        csv = work / "table.csv"
        csv.write_text("name;value\nä;1\nb;2.5\n", encoding="utf-8")
        xlsx = convert(cmd, csv, "xlsx")
        check("xlsx is a zip", zipfile.is_zipfile(xlsx))
        convert(cmd, csv, "yaml")

        # External tools: this is where a packaged build could leak its own libraries.
        if have_ffmpeg:
            wav = work / "tone.wav"
            ffmpeg = shutil.which("ffmpeg")
            subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=duration=2", str(wav)], check=True)
            convert(cmd, wav, "mp3", "normalize=podcast")
            convert(cmd, wav, "opus")
        else:
            print("- FFmpeg not installed, skipping audio")
        if have_pandoc:
            md = work / "notes.md"
            md.write_text("# Hallo\n\nText mit **Umlauten** äöü.\n", encoding="utf-8")
            convert(cmd, md, "html")
            convert(cmd, md, "docx")
        else:
            print("- Pandoc not installed, skipping documents")

    if args.gui:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        with tempfile.TemporaryDirectory(prefix="omni-gui-") as cfg:
            env["OMNICONVERTER_CONFIG_DIR"] = cfg
            log = Path(cfg) / "gui.log"
            with log.open("w") as out:
                # Own process group: launchers like the AppImage runtime start the real app
                # as a child, which has to be stopped as well.
                gui = [shutil.which(args.gui_command) or args.gui_command] if args.gui_command \
                    else cmd
                proc = subprocess.Popen(gui, env=env, stdout=out, stderr=subprocess.STDOUT,
                                        start_new_session=sys.platform != "win32")
                time.sleep(6)
                alive = proc.poll() is None
                stop(proc)
            output = log.read_text(errors="replace").strip()[-1500:]
        check("GUI starts and keeps running", alive, "" if alive else output)

    print("All smoke tests passed.")
    return 0


def _tiny_png() -> bytes:
    import base64

    # 16×16 semi-transparent orange PNG (made with Pillow).
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAHUlEQVR4nGP8H8CwgIECwESJ5lEDRg0Y"
        "NWAwGQAAHFkCD5bfq2MAAAAASUVORK5CYII="
    )


if __name__ == "__main__":
    sys.exit(main())
