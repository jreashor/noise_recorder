import csv

import pytest

from noise_recorder import report


def run(data_dir, *args):
    report.main(["--data-dir", str(data_dir), *args])


def test_top_lists_loudest_first(data_dir, capsys):
    run(data_dir, "top")
    lines = capsys.readouterr().out.splitlines()
    assert "11:14:24" in lines[2] and "11:14:10" in lines[3]


def test_note_and_export(data_dir, tmp_path):
    run(data_dir, "note", "2", "door slam")
    out = tmp_path / "events.csv"
    run(data_dir, "export", str(out))
    rows = list(csv.DictReader(out.open()))
    assert [r["note"] for r in rows] == ["<b>thud</b>", "door slam"]


def test_delete(data_dir, capsys):
    run(data_dir, "delete", "1", "999")
    assert capsys.readouterr().out.splitlines() == ["1: deleted", "999: no such event"]
    assert not (data_dir / "2026-11-07/11-14-10.wav").exists()


def test_missing_database_exits_cleanly(tmp_path):
    with pytest.raises(SystemExit, match="No database"):
        run(tmp_path, "daily")
    assert not (tmp_path / "noise.db").exists()
