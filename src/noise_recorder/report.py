#!/usr/bin/env python3
"""
Query the noise database.

    noise-report top --n 20            # loudest events
    noise-report top --by la --since 2026-11-01
    noise-report hourly                # which hours are worst
    noise-report daily                 # per-day counts and loudest
    noise-report note 42 "dragging furniture"   # tag an event
    noise-report delete 42 43          # remove events and their WAVs
    noise-report export events.csv     # for Excel / Numbers
"""

import argparse
import csv
import sys

from . import config, db

COLS = {"lz": "max_lz", "la": "max_la", "peak": "peak", "len": "duration_s"}


def show(rows, headers):
    widths = [max(len(str(x)) for x in [h] + [r[i] for r in rows]) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("-" * len(line))
    for r in rows:
        cells = (str(v if v is not None else "").ljust(w) for v, w in zip(r, widths, strict=True))
        print("  ".join(cells))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", help=f"default: $NOISE_DATA_DIR or {config.DEFAULT_DATA_DIR}")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("top")
    t.add_argument("--n", type=int, default=20)
    t.add_argument("--by", choices=COLS, default="lz")
    t.add_argument("--since", default="0000")
    sub.add_parser("hourly")
    sub.add_parser("daily")
    n = sub.add_parser("note")
    n.add_argument("id", type=int)
    n.add_argument("text")
    d = sub.add_parser("delete")
    d.add_argument("ids", type=int, nargs="+")
    d.add_argument("--keep-file", action="store_true", help="keep the WAV clips")
    e = sub.add_parser("export")
    e.add_argument("path")
    a = p.parse_args(argv)

    data = config.data_dir(a.data_dir)
    try:
        conn = db.connect(config.db_path(data))
    except FileNotFoundError as e:
        sys.exit(str(e))
    if a.cmd == "top":
        col = COLS[a.by]
        rows = conn.execute(
            f"SELECT id,start,duration_s,max_lz,max_la,peak,unit,note,file FROM events "
            f"WHERE start >= ? ORDER BY {col} DESC LIMIT ?",
            (a.since, a.n),
        ).fetchall()
        show(rows, ["id", "start", "secs", "maxLZ", "maxLA", "peak", "unit", "note", "file"])
    elif a.cmd == "hourly":
        rows = conn.execute(
            "SELECT strftime('%H',start)||':00', COUNT(*), ROUND(MAX(max_lz),1), "
            "ROUND(AVG(max_lz),1) FROM events GROUP BY 1 ORDER BY 1"
        ).fetchall()
        show(rows, ["hour", "events", "loudest", "avg_max"])
    elif a.cmd == "daily":
        rows = conn.execute(
            "SELECT date(start), COUNT(*), ROUND(MAX(max_lz),1), ROUND(SUM(duration_s)/60,1) "
            "FROM events GROUP BY 1 ORDER BY 1"
        ).fetchall()
        show(rows, ["date", "events", "loudest", "total_min"])
    elif a.cmd == "note":
        conn.execute("UPDATE events SET note=? WHERE id=?", (a.text, a.id))
        conn.commit()
        print("ok")
    elif a.cmd == "delete":
        for i in a.ids:
            ok = db.delete_event(conn, i, data, keep_file=a.keep_file)
            print(f"{i}: {'deleted' if ok else 'no such event'}")
    elif a.cmd == "export":
        cur = conn.execute("SELECT * FROM events ORDER BY start")
        with open(a.path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur)
        print(f"wrote {a.path}")


if __name__ == "__main__":
    main()
