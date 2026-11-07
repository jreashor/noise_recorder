import pytest

from noise_recorder import db


@pytest.fixture
def data_dir(tmp_path):
    """A data directory with a database holding two events and their WAV files."""
    c = db.create(tmp_path / "noise.db")
    for i, (start, lz, note) in enumerate(
        [
            ("2026-11-07T11:14:10", -20.0, "<b>thud</b>"),
            ("2026-11-07T11:14:24", -19.0, None),
        ],
        start=1,
    ):
        name = f"2026-11-07/{start[11:].replace(':', '-')}.wav"
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"RIFF fake wav " + bytes([i]))
        c.execute(
            "INSERT INTO events (start,duration_s,peak,max_lz,max_la,laeq,lzeq,"
            "baseline_lz,unit,file,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (start, 10.0, -3.0, lz, -25.0, -30.0, -28.0, -50.0, "dBFS", name, note),
        )
    for m in range(10, 15):
        c.execute(
            "INSERT INTO minutes VALUES (?,?,?,?)", (f"2026-11-07 11:{m}", -45.0, -42.0, -30.0)
        )
    c.execute("INSERT INTO minutes VALUES (?,?,?,?)", ("2026-11-06 09:00", -45.0, -42.0, -1.0))
    c.commit()
    c.close()
    return tmp_path
