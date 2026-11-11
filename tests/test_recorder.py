import argparse
import datetime as dt
import wave

import numpy as np

from noise_recorder import db
from noise_recorder.recorder import BLOCK_SEC, Detector, Meter, save_wav

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
        min_duration=0.0,
        max_clip=300.0,
        gain=0.0,
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
    assert 3.0 <= duration <= 4.1  # pre-roll + event + 1 s kept of the tail
    with wave.open(str(tmp_path / name)) as w:
        assert w.getframerate() == RATE
        assert abs(w.getnframes() / RATE - duration) < 0.01
    assert conn.execute("SELECT COUNT(*) FROM minutes").fetchone()[0] == 1


def _wav_peak_dbfs(path):
    with wave.open(str(path)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return 20 * np.log10(np.max(np.abs(pcm)) / 32767)


def test_save_wav_keeps_audio_unchanged_by_default(tmp_path):
    save_wav(tmp_path / "q.wav", [0.01 * np.ones(BLOCK)], RATE)  # -40 dBFS stays -40 dBFS
    assert abs(_wav_peak_dbfs(tmp_path / "q.wav") - (-40)) < 0.05


def test_save_wav_gain_is_the_same_for_quiet_and_loud_clips(tmp_path):
    save_wav(tmp_path / "q.wav", [0.01 * np.ones(BLOCK)], RATE, gain_db=6.0)  # -40 dBFS
    save_wav(tmp_path / "l.wav", [0.1 * np.ones(BLOCK)], RATE, gain_db=6.0)  # -20 dBFS
    assert abs(_wav_peak_dbfs(tmp_path / "q.wav") - (-34)) < 0.05
    assert abs(_wav_peak_dbfs(tmp_path / "l.wav") - (-14)) < 0.05


def test_detector_status_reports_calibration_then_trigger(tmp_path):
    conn = db.create(tmp_path / "noise.db")
    det = Detector(make_args(), Meter(BLOCK, RATE), conn, tmp_path)
    rng = np.random.default_rng(1)
    now = dt.datetime(2026, 11, 7, 11, 0, 0)
    for _ in range(50):
        det.feed(0.001 * rng.standard_normal(BLOCK), now)
    st = det.status()
    assert st["calibrating"] and st["trigger"] is None
    assert st["calibration_left_s"] == 5

    for _ in range(100):
        det.feed(0.001 * rng.standard_normal(BLOCK), now)
    st = det.status()
    assert not st["calibrating"] and not st["in_event"]
    assert st["trigger"] == round(st["baseline"] + 10.0, 1)
    assert abs(st["level"] - st["baseline"]) < 3
    assert st["saved"] == 0

    for _ in range(5):
        det.feed(0.1 * rng.standard_normal(BLOCK), now)
    st = det.status()
    assert st["in_event"] and st["level"] > st["trigger"]
    for _ in range(20):
        det.feed(0.001 * rng.standard_normal(BLOCK), now)
    assert det.status()["saved"] == 1


def _run(det, pattern, seed=2):
    """Feed (blocks, amplitude) pairs after a quiet calibration period."""
    rng = np.random.default_rng(seed)
    now = dt.datetime(2026, 11, 7, 11, 0, 0)
    for n, amp in [(150, 0.001), *pattern]:
        for _ in range(n):
            det.feed(amp * rng.standard_normal(BLOCK), now)
            now += dt.timedelta(seconds=BLOCK_SEC)
    det.finish()


def test_short_disturbance_is_ignored(tmp_path):
    conn = db.create(tmp_path / "noise.db")
    det = Detector(make_args(min_duration=2.0), Meter(BLOCK, RATE), conn, tmp_path)
    _run(det, [(5, 0.1), (30, 0.001)])  # 0.5 s thump
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert det.ignored == 1 and det.saved == 0
    assert not list(tmp_path.glob("*/*.wav"))


def test_gaps_shorter_than_tail_join_one_long_event(tmp_path):
    conn = db.create(tmp_path / "noise.db")
    det = Detector(make_args(min_duration=2.0, tail=3.0), Meter(BLOCK, RATE), conn, tmp_path)
    # Four 1 s bursts with 2 s pauses: each alone is too short, together 10 s.
    bursts = [(10, 0.1), (20, 0.001)] * 3 + [(10, 0.1), (40, 0.001)]
    _run(det, bursts)
    rows = conn.execute("SELECT duration_s FROM events").fetchall()
    assert len(rows) == 1 and det.ignored == 0
    assert 1.0 + 10.0 + 1.0 - 0.2 <= rows[0][0] <= 1.0 + 10.0 + 1.0 + 0.2  # pre-roll + span + 1 s


def test_quiet_tail_is_not_saved(tmp_path):
    conn = db.create(tmp_path / "noise.db")
    det = Detector(make_args(preroll=2.0, tail=10.0), Meter(BLOCK, RATE), conn, tmp_path)
    _run(det, [(1, 0.1), (120, 0.001)])  # 0.1 s thud, then quiet
    (duration,) = conn.execute("SELECT duration_s FROM events").fetchone()
    assert 2.8 <= duration <= 3.2  # 2 s pre-roll + thud + 1 s, not the 10 s tail


def test_recorder_flags_default_to_saved_settings(tmp_path, monkeypatch):
    from noise_recorder import control, recorder

    control.save_settings(tmp_path, {"threshold": 30, "min_duration": 4})
    seen = {}

    def fake_parse(self, argv=None, namespace=None):
        args = orig(self, argv, namespace)
        seen.update(vars(args))
        raise SystemExit(0)  # stop before opening the microphone

    import argparse

    orig = argparse.ArgumentParser.parse_args
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", fake_parse)
    for argv, threshold in [
        (["--data-dir", str(tmp_path)], 30.0),
        (["--data-dir", str(tmp_path), "--threshold", "12"], 12.0),
    ]:
        try:
            recorder.main(argv)
        except SystemExit:
            pass
        assert seen["threshold"] == threshold
        assert seen["min_duration"] == 4.0
        assert seen["tail"] == control.default_settings()["tail"]
