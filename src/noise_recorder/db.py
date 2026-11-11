"""SQLite schema and helpers shared by the recorder, report tool and dashboard."""

import sqlite3
from pathlib import Path

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
    file TEXT,                    -- WAV filename, relative to the data directory
    note TEXT                     -- free text for you (e.g. 'dragging', 'thud')
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
CREATE INDEX IF NOT EXISTS idx_events_maxlz ON events(max_lz);
CREATE TABLE IF NOT EXISTS minutes (
    minute TEXT PRIMARY KEY,
    laeq REAL, lzeq REAL, max_lz REAL
);
"""


def create(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database for writing, with the schema in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    """Open an existing database. Never creates an empty file."""
    if not path.exists():
        raise FileNotFoundError(f"No database at {path}. Run noise-recorder first.")
    mode = "ro" if readonly else "rw"
    c = sqlite3.connect(f"file:{path}?mode={mode}", uri=True)
    c.row_factory = sqlite3.Row
    return c


def delete_events(
    c: sqlite3.Connection, ids: list[int], data_dir: Path, keep_file: bool = False
) -> list[int]:
    """Delete event rows and (unless keep_file) their WAV clips. Returns the ids deleted."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT id, file FROM events WHERE id IN ({placeholders})", ids).fetchall()
    c.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
    c.commit()
    if not keep_file:
        for _, file in rows:
            if file:
                path = (data_dir / file).resolve()
                if data_dir.resolve() in path.parents:
                    path.unlink(missing_ok=True)
    return [r[0] for r in rows]


def prune_missing_files(c: sqlite3.Connection, data_dir: Path) -> list[int]:
    """Delete event rows whose WAV file was removed from disk outside the tools."""
    rows = c.execute("SELECT id, file FROM events WHERE file IS NOT NULL AND file != ''")
    gone = [i for i, f in rows.fetchall() if not (data_dir / f).exists()]
    if gone:
        c.executemany("DELETE FROM events WHERE id = ?", [(i,) for i in gone])
        c.commit()
    return gone


def delete_event(
    c: sqlite3.Connection, event_id: int, data_dir: Path, keep_file: bool = False
) -> bool:
    """Delete one event and its WAV clip. False if no such event."""
    return bool(delete_events(c, [event_id], data_dir, keep_file))
