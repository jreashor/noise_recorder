import sqlite3

import pytest

from noise_recorder import config, db


def test_connect_never_creates_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect(tmp_path / "noise.db")
    assert not (tmp_path / "noise.db").exists()


def test_readonly_connection_rejects_writes(data_dir):
    c = db.connect(data_dir / "noise.db", readonly=True)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM events")


def test_delete_event_removes_row_and_file(data_dir):
    c = db.connect(data_dir / "noise.db")
    wav = data_dir / "2026-11-07/11-14-10.wav"
    assert db.delete_event(c, 1, data_dir)
    assert not wav.exists()
    assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_delete_event_keep_file(data_dir):
    c = db.connect(data_dir / "noise.db")
    assert db.delete_event(c, 1, data_dir, keep_file=True)
    assert (data_dir / "2026-11-07/11-14-10.wav").exists()


def test_delete_missing_event(data_dir):
    assert not db.delete_event(db.connect(data_dir / "noise.db"), 999, data_dir)


def test_delete_refuses_paths_outside_data_dir(data_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "keep.wav"
    outside.write_bytes(b"x")
    c = db.connect(data_dir / "noise.db")
    c.execute("UPDATE events SET file=? WHERE id=1", (str(outside),))
    c.commit()
    assert db.delete_event(c, 1, data_dir)
    assert outside.exists()


def test_data_dir_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("NOISE_DATA_DIR", raising=False)
    assert config.data_dir() == config.DEFAULT_DATA_DIR
    monkeypatch.setenv("NOISE_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.data_dir(tmp_path / "x") == tmp_path / "x"


def test_delete_events_bulk(data_dir):
    c = db.connect(data_dir / "noise.db")
    assert sorted(db.delete_events(c, [1, 2, 999], data_dir)) == [1, 2]
    assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert not list((data_dir / "2026-11-07").iterdir())
    assert db.delete_events(c, [], data_dir) == []


def test_prune_missing_files(data_dir):
    (data_dir / "2026-11-07/11-14-10.wav").unlink()
    c = db.connect(data_dir / "noise.db")
    assert db.prune_missing_files(c, data_dir) == [1]
    assert [r[0] for r in c.execute("SELECT id FROM events")] == [2]
