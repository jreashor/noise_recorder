#!/usr/bin/env python3
"""
All-day noise recorder for macOS with dB readings and a SQLite database.

- Listens continuously; when the level rises above the room baseline it saves
  a WAV clip (with pre-roll) and adds a row to the `events` table.
- Every minute it also logs the average/max level to the `minutes` table, so
  you can show the quiet baseline as well as the disturbances.
- Query/sort the data with noise_report.py, DB Browser for SQLite, or Datasette.

Setup:
    brew install portaudio
    pip3 install sounddevice numpy
    python3 noise_recorder.py --list-devices

Run all day (caffeinate stops the Mac sleeping; keep it plugged in):
    caffeinate -i python3 noise_recorder.py --device 2 --cal-offset 0

CALIBRATION: levels are dBFS + --cal-offset. Offset 0 = relative dBFS.
For dB SPL run `--calibrate` against a reference sound level meter, then pass
the printed offset. Fix the macOS input volume and never change it.
"""
import argparse
import collections
import datetime as dt
import sqlite3
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

BLOCK_SEC = 0.1
HIGHPASS_HZ = 20.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start TEXT NOT NULL,          -- local time, ISO 8601
    duration_s REAL,
    peak REAL,                    -- max instantaneous sample level
    max_lz REAL,                  -- loudest 0.1 s block, unweighted
    max_la REAL,                  -- loudest 0.1 s block, A-weighted
    laeq REAL,                    -- energy average over the event, A-weighted
    lzeq REAL,                    -- energy average over the event, unweighted
    baseline_lz REAL,             -- room level just before the event
    unit TEXT,                    -- 'dB SPL' or 'dBFS'
    file TEXT,                    -- WAV filename
    note TEXT                     -- free text for you (e.g. 'dragging', 'thud')
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
CREATE INDEX IF NOT EXISTS idx_events_maxlz ON events(max_lz);
CREATE TABLE IF NOT EXISTS minutes (
    minute TEXT PRIMARY KEY,
    laeq REAL, lzeq REAL, max_lz REAL
);
"""


def a_weight_db(f):
    f2 = np.maximum(f, 1e-3) ** 2
    ra = (12194.0**2 * f2**2) / (
        (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194.0**2))
    return 20 * np.log10(ra) + 2.0


class Meter:
    def __init__(self, n, rate):
        self.n = n
        self.win = np.hanning(n)
        self.win_pow = np.sum(self.win**2)
        freqs = np.fft.rfftfreq(n, 1.0 / rate)
        keep = freqs >= HIGHPASS_HZ
        edge = np.ones_like(freqs)
        edge[1:-1] = 2.0
        self.w_z = edge * keep
        self.w_a = edge * keep * 10 ** (a_weight_db(freqs) / 10.0)

    def levels(self, x):
        X = np.fft.rfft(x * self.win)
        p = np.abs(X) ** 2 / (self.n * self.win_pow)
        lz = 10 * np.log10(max(np.sum(p * self.w_z), 1e-20))
        la = 10 * np.log10(max(np.sum(p * self.w_a), 1e-20))
        pk = 20 * np.log10(max(np.max(np.abs(x)), 1e-10))
        return float(lz), float(la), float(pk)


def energy_mean(vals):
    return float(10 * np.log10(np.mean(10 ** (np.asarray(vals) / 10))))


def save_wav(path, chunks, rate):
    pcm = (np.clip(np.concatenate(chunks), -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


class Detector:
    def __init__(self, args, meter, db, out_dir):
        self.a, self.meter, self.db, self.out = args, meter, db, out_dir
        self.off = args.cal_offset
        self.unit = "dB SPL" if self.off else "dBFS"
        self.floor = args.min_level if args.min_level is not None else -1e9
        self.pre = collections.deque(maxlen=int(args.preroll / BLOCK_SEC))
        self.tail_blocks = int(args.tail / BLOCK_SEC)
        self.max_blocks = int(args.max_clip / BLOCK_SEC)
        self.n = 0
        self.baseline = None
        self.rec = False
        self.clip, self.lz, self.la, self.pk = [], [], [], []
        self.quiet = 0
        self.start = None
        self.clip_base = None
        self.minute = None
        self.m_lz, self.m_la = [], []

    # ---- per-minute log
    def _minute(self, now, lz, la):
        key = now.strftime("%Y-%m-%d %H:%M")
        if self.minute is not None and key != self.minute:
            self._flush_minute()
        self.minute = key
        self.m_lz.append(lz)
        self.m_la.append(la)

    def _flush_minute(self):
        if self.minute and self.m_lz:
            self.db.execute(
                "INSERT OR REPLACE INTO minutes VALUES (?,?,?,?)",
                (self.minute, round(energy_mean(self.m_la), 1),
                 round(energy_mean(self.m_lz), 1), round(max(self.m_lz), 1)))
            self.db.commit()
        self.m_lz, self.m_la = [], []

    # ---- event saving
    def _save_event(self):
        name = f"{self.start:%Y-%m-%d}/{self.start:%H-%M-%S}.wav"
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        save_wav(path, self.clip, self.a.rate)
        self.db.execute(
            "INSERT INTO events (start,duration_s,peak,max_lz,max_la,laeq,lzeq,"
            "baseline_lz,unit,file) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.start.isoformat(timespec="seconds"),
             round(len(self.clip) * BLOCK_SEC, 1), round(max(self.pk), 1),
             round(max(self.lz), 1), round(max(self.la), 1),
             round(energy_mean(self.la), 1), round(energy_mean(self.lz), 1),
             round(self.clip_base, 1), self.unit, name))
        self.db.commit()
        print(f"  saved {name}: max LZ {max(self.lz):.1f}, max LA {max(self.la):.1f} {self.unit}")
        self.rec = False
        self.clip, self.lz, self.la, self.pk = [], [], [], []
        self.pre.clear()

    def feed(self, data, now):
        lz, la, pk = self.meter.levels(data)
        lz, la, pk = lz + self.off, la + self.off, pk + self.off
        self.n += 1
        self._minute(now, lz, la)

        if self.baseline is None:
            self.baseline = lz
        if self.n < 100:                       # ~10 s calibration window
            self.baseline = 0.9 * self.baseline + 0.1 * lz
            self.pre.append(data)
            return

        loud = lz > max(self.baseline + self.a.threshold, self.floor)
        if not self.rec:
            self.pre.append(data)
            if loud:
                self.rec, self.start, self.clip_base = True, now, self.baseline
                self.clip = list(self.pre)
                self.lz, self.la, self.pk = [lz], [la], [pk]
                self.quiet = 0
                print(f"[{now:%H:%M:%S}] disturbance {lz:.1f} {self.unit} "
                      f"(baseline {self.baseline:.1f})")
            else:
                self.baseline = 0.995 * self.baseline + 0.005 * lz
        else:
            self.clip.append(data)
            self.lz.append(lz); self.la.append(la); self.pk.append(pk)
            self.quiet = 0 if loud else self.quiet + 1
            if self.quiet >= self.tail_blocks or len(self.clip) >= self.max_blocks:
                self._save_event()

    def finish(self):
        if self.rec:
            self._save_event()
        self._flush_minute()


def run_calibration(args, meter):
    print("Play a steady sound; note the reference meter reading. Measuring 10 s...")
    vals = []
    with sd.InputStream(samplerate=args.rate, channels=1, blocksize=meter.n,
                        device=args.device) as s:
        for _ in range(100):
            data, _ = s.read(meter.n)
            vals.append(meter.levels(data[:, 0])[1])
    measured = energy_mean(vals)
    ref = float(input("Reference meter reading in dBA: "))
    print(f"Measured {measured:.1f} dBFS(A). Use: --cal-offset {ref - measured:.1f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--device", type=int)
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--cal-offset", type=float, default=0.0)
    p.add_argument("--rate", type=int, default=44100,
                   help="sample rate; 22050 halves disk use and is fine for thumps")
    p.add_argument("--threshold", type=float, default=10.0,
                   help="dB above baseline that counts as a disturbance")
    p.add_argument("--min-level", type=float, default=None)
    p.add_argument("--preroll", type=float, default=5.0)
    p.add_argument("--tail", type=float, default=5.0)
    p.add_argument("--max-clip", type=float, default=300.0)
    p.add_argument("--out", default="noise_recordings")
    args = p.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return
    block = int(args.rate * BLOCK_SEC)
    meter = Meter(block, args.rate)
    if args.calibrate:
        run_calibration(args, meter)
        return

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    db = sqlite3.connect(out / "noise.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)

    # Keep running through glitches (mic unplugged, sleep/wake): retry after 5 s.
    while True:
        det = Detector(args, meter, db, out)
        print("Listening... Ctrl+C to stop. Calibrating baseline ~10 s, stay quiet.")
        try:
            with sd.InputStream(samplerate=args.rate, channels=1, blocksize=block,
                                device=args.device) as stream:
                while True:
                    data, overflow = stream.read(block)
                    if overflow:
                        print("warning: audio buffer overflow", file=sys.stderr)
                    det.feed(data[:, 0].copy(), dt.datetime.now())
        except KeyboardInterrupt:
            det.finish()
            print("\nStopped.")
            return
        except Exception as e:  # noqa: BLE001
            det.finish()
            print(f"Audio error: {e}. Retrying in 5 s...", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
