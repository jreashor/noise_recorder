import argparse
import datetime as dt
import wave

import numpy as np

from noise_recorder import db
from noise_recorder.recorder import BLOCK_SEC, Detector, Meter

RATE = 8000
BLOCK = int(RATE * BLOCK_SEC)


def make_args(**kw):
    args = dict(
        rate=RATE,
        cal_offset=0.0,
        threshold=10.0,
        min_level=None,
        preroll=1.0,
        tail=1.0,
        max_clip=300.0,
    )
    args.update(kw)
    return argparse.Namespace(**args)


def test_meter_tracks_amplitude():
    m = Meter(BLOCK, RATE)
    t = np.arange(BLOCK) / RATE
    quiet = m.levels(0.001 * np.sin(2 * np.pi * 1000 * t))[0]
    loud = m.levels(0.1 * np.sin(2 * np.pi * 1000 * t))[0]
    assert abs((loud - quiet) - 40.0) < 0.5  # 100x amplitude = +40 dB


def test_detector_records_disturbance(tmp_path):
    conn = db.create(tmp_path / "noise.db")
    det = Detector(make_args(), Meter(BLOCK, RATE), conn, tmp_path)
    rng = np.random.default_rng(0)
    now = dt.datetime(2026, 11, 7, 11, 0, 0)

    def feed(n, amp):
        nonlocal now
        for _ in range(n):
            det.feed(amp * rng.standard_normal(BLOCK), now)
            now += dt.timedelta(seconds=BLOCK_SEC)

    feed(150, 0.001)  # calibration + quiet room
    feed(20, 0.1)  # 2 s disturbance, +40 dB
    feed(30, 0.001)  # quiet tail ends the event
    det.finish()

    rows = conn.execute(
        "SELECT start, duration_s, max_lz, baseline_lz, file FROM events"
    ).fetchall()
    assert len(rows) == 1
    start, duration, max_lz, baseline, name = rows[0]
    assert start == "2026-11-07T11:00:15"
    assert max_lz - baseline > 30
    assert 3.0 <= duration <= 4.5  # pre-roll + event + tail
    with wave.open(str(tmp_path / name)) as w:
        assert w.getframerate() == RATE
        assert abs(w.getnframes() / RATE - duration) < 0.01
    assert conn.execute("SELECT COUNT(*) FROM minutes").fetchone()[0] == 1
