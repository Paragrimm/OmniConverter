import sys
import threading
import time

import pytest

from omniconverter.core import process
from omniconverter.core.errors import Cancelled, ConversionError


def test_collects_stdout_and_stderr_tail():
    result = process.run([sys.executable, "-c",
                          "import sys; print('out'); print('err', file=sys.stderr)"])
    assert result.stdout == "out" and result.stderr_tail == "err"


def test_failure_carries_details():
    with pytest.raises(ConversionError) as err:
        process.run([sys.executable, "-c", "import sys; sys.exit('broken')"],
                    error_message="Tool failed.")
    assert err.value.message == "Tool failed."
    assert "broken" in err.value.details


def test_missing_program():
    with pytest.raises(ConversionError):
        process.run(["definitely-not-a-program-xyz"])


def test_streams_lines_to_callback():
    lines = []
    process.run([sys.executable, "-c", "print('a'); print('b')"], on_stdout_line=lines.append)
    assert lines == ["a", "b"]


@pytest.mark.skipif(sys.platform == "win32", reason="uses os.kill(pid, 0)")
def test_cancel_also_stops_grandchildren():
    """Like a Chocolatey shim or LibreOffice's launcher: the real work runs in a child."""
    import os

    script = ("import subprocess, sys, time; "
              "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              "print(p.pid, flush=True); time.sleep(60)")
    pids = []
    cancel = threading.Event()

    def on_line(line):
        pids.append(int(line))
        cancel.set()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        process.run([sys.executable, "-c", script], on_stdout_line=on_line, cancel=cancel)
    assert time.monotonic() - started < 10
    (child,) = pids
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        pytest.fail("grandchild survived the cancel")


def test_timeout():
    with pytest.raises(ConversionError):
        process.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)


def test_remove_quietly(tmp_path):
    f = tmp_path / "x"
    f.write_text("1")
    process.remove_quietly(f)
    assert not f.exists()
    process.remove_quietly(f)  # missing is fine
