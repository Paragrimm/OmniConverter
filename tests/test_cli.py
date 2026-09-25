import json

import pytest

from omniconverter.cli import is_cli_invocation, main


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,x\n", encoding="utf-8")
    return path


def test_cli_detection():
    assert is_cli_invocation(["x.mp4", "--to", "gif"])
    assert is_cli_invocation(["--to=gif", "x.mp4"])
    assert is_cli_invocation(["--tools"])
    assert not is_cli_invocation(["a.mp4", "b.mp4"])
    assert not is_cli_invocation([])


def test_convert_default_output(csv_file, capsys):
    assert main([str(csv_file), "--to", "json"]) == 0
    out = csv_file.with_suffix(".json")
    assert json.loads(out.read_text()) == [{"a": 1, "b": "x"}]
    assert str(out) in capsys.readouterr().err
    # a second run never overwrites the first result
    assert main([str(csv_file), "--to", "json", "-q"]) == 0
    assert (csv_file.parent / "t (1).json").exists()


def test_explicit_output_and_overwrite(csv_file, tmp_path):
    out = tmp_path / "custom.yaml"
    assert main([str(csv_file), "-t", "yaml", "-o", str(out)]) == 0
    assert main([str(csv_file), "-t", "yaml", "-o", str(out)]) == 1
    assert main([str(csv_file), "-t", "yaml", "-o", str(out), "--overwrite"]) == 0


def test_options_via_set(csv_file):
    assert main([str(csv_file), "--to", "tsv", "-s", "excel_bom=yes", "-q"]) == 0
    assert csv_file.with_suffix(".tsv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_many_files_into_folder(tmp_path):
    files = []
    for name in ("a", "b"):
        f = tmp_path / f"{name}.json"
        f.write_text('[{"x": 1}]')
        files.append(str(f))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert main([*files, "--to", "csv", "-o", str(out_dir), "-q"]) == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ["a.csv", "b.csv"]


def test_errors(csv_file, capsys):
    assert main([str(csv_file), "--to", "nope"]) == 2
    assert main([str(csv_file), "--to", "json", "-s", "bogus=1"]) == 1
    assert main([str(csv_file), "--to", "json", "-s", "novalue"]) == 1
    assert main([str(csv_file.with_name("missing.csv")), "--to", "json"]) == 1
    with pytest.raises(SystemExit):
        main([str(csv_file)])  # no --to
    err = capsys.readouterr().err
    assert "Unknown format: nope" in err and "unknown option" in err


def test_list_and_options(csv_file, capsys):
    assert main(["--list", str(csv_file)]) == 0
    out = capsys.readouterr().out
    assert "xlsx" in out and "json" in out
    data = csv_file.with_name("d.json")
    data.write_text('[{"a": 1}]')
    assert main(["--options", str(data), "--to", "csv"]) == 0
    out = capsys.readouterr().out
    assert "delimiter" in out and "comma | semicolon | tab" in out


def test_tools(capsys):
    assert main(["--tools"]) == 0
    out = capsys.readouterr().out
    assert "FFmpeg" in out and "LibreOffice" in out


def test_integrate_status(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert main(["--integrate", "status"]) == 0
    assert "not installed" in capsys.readouterr().out.lower()


def test_qr_code_from_text(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert is_cli_invocation(["--text", "https://example.com"])
    assert main(["--text", "https://example.com", "--to", "qr"]) == 0
    assert (tmp_path / "qr-code.png").is_file()
    assert main(["--text", "hi", "--to", "qr-svg", "-o", str(tmp_path / "hi.svg"), "-q"]) == 0
    assert (tmp_path / "hi.svg").read_text().lstrip().startswith("<?xml")
    assert "qr-code.png" in capsys.readouterr().err


def test_generated_noise_is_named_after_its_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = ["--generate", "noise", "--to", "png", "-s", "width=32", "-s", "height=32", "-q"]
    assert main([*args, "-s", "seed=42"]) == 0
    assert main([*args, "-s", "seed=42"]) == 0
    assert (tmp_path / "noise-42.png").read_bytes() == (tmp_path / "noise-42 (1).png").read_bytes()
    assert main(args) == 0  # a random seed, which then shows up in the name
    random_one = [p.name for p in tmp_path.iterdir() if not p.name.startswith("noise-42")]
    assert len(random_one) == 1 and random_one[0].startswith("noise-")


def test_source_conflicts(csv_file):
    with pytest.raises(SystemExit):
        main([str(csv_file), "--text", "x", "--to", "qr"])
    with pytest.raises(SystemExit):
        main(["--text", "x", "--generate", "noise", "--to", "png"])


def test_list_for_generators(capsys):
    assert main(["--list", "--generate", "noise"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Noise-Map" and "jpg" in out
