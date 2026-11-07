#!/usr/bin/env python3
"""
Noise Recorder Dashboard - Web UI for reviewing recorded disturbances.
Reads from the SQLite database and serves HTML with embedded assets.
"""
import json
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "noise_recordings"
DB_PATH = OUT_DIR / "noise.db"
TEMPLATE_PATH = BASE_DIR / "dashboard_template.html"


app = FastAPI(title="Noise Recorder Dashboard")

# --- Database helpers ---

def query(sql, params=()):
    """Run a read-only query and return rows as dicts.

    Opens the DB read-only so a missing database is reported instead of being
    silently created as an empty file. Returns [] if the tables don't exist yet.
    """
    if not DB_PATH.exists():
        return []
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise
    finally:
        c.close()

def get_events(limit=500, since=None):
    """Fetch events with noise levels and file paths."""
    return query("""
        SELECT id, start, duration_s, peak, max_lz, max_la, laeq, lzeq,
               baseline_lz, unit, note, file
        FROM events
        WHERE (? IS NULL OR start >= ?)
        ORDER BY start DESC
        LIMIT ?
    """, (since, since, limit))

def get_minutes():
    """Get per-minute averages for the chart."""
    try:
        return query("""
            SELECT strftime('%Y-%m-%d %H:%M', minute) as time_bucket, 
                   laeq, lzeq, max_lz
            FROM minutes
            WHERE strftime('%Y-%m-%d', minute) = (
                SELECT MAX(strftime('%Y-%m-%d', minute)) FROM minutes
            )
            ORDER BY time_bucket
        """)
    except sqlite3.OperationalError:
        return []


def get_hourly():
    """Get hourly summary."""
    try:
        return query("""
            SELECT strftime('%H', start) || ':00' as hour, COUNT(*) as count, 
                   ROUND(MAX(max_lz), 1) as loudest, ROUND(AVG(max_lz), 1) as avg_max
            FROM events
            GROUP BY 1
            ORDER BY 1
        """)
    except sqlite3.OperationalError:
        return []


def get_daily():
    """Get daily summary."""
    try:
        return query("""
            SELECT date(start) as day, COUNT(*) as count, ROUND(MAX(max_lz), 1) as loudest,
                   ROUND(SUM(duration_s)/60, 1) as total_min
            FROM events
            GROUP BY 1
            ORDER BY 1 DESC
        """)
    except sqlite3.OperationalError:
        return []


def to_js(data):
    # Escape "</" so data can't close the surrounding <script> tag.
    return json.dumps(data).replace("</", "<\\/")


def prune_missing_files():
    """Delete event rows whose WAV file was removed from disk outside the dashboard."""
    if not DB_PATH.exists():
        return
    c = sqlite3.connect(DB_PATH)
    try:
        rows = c.execute("SELECT id, file FROM events WHERE file IS NOT NULL AND file != ''").fetchall()
        gone = [(i,) for i, f in rows if not (OUT_DIR / f).exists()]
        if gone:
            c.executemany("DELETE FROM events WHERE id = ?", gone)
            c.commit()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
    finally:
        c.close()


def build_html_page():
    """Build the dashboard HTML page by reading a template file and injecting data."""
    prune_missing_files()
    html_content = TEMPLATE_PATH.read_text()
    html_content = html_content.replace("{{{events_json}}}", to_js(get_events(limit=500)))
    html_content = html_content.replace("{{{minutes_json}}}", to_js(get_minutes()))
    html_content = html_content.replace("{{{daily_data}}}", to_js(get_daily()))
    return HTMLResponse(content=html_content)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the main dashboard page."""
    return build_html_page()


class DeleteRequest(BaseModel):
    ids: list[int]


def delete_events(ids):
    """Remove disturbances (database rows and WAV clips). Returns the ids deleted."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found")
    placeholders = ",".join("?" * len(ids))
    c = sqlite3.connect(DB_PATH)
    try:
        rows = c.execute(f"SELECT id, file FROM events WHERE id IN ({placeholders})", ids).fetchall()
        c.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
        c.commit()
    finally:
        c.close()
    for _, file in rows:
        if file:
            path = (OUT_DIR / file).resolve()
            if OUT_DIR.resolve() in path.parents:
                path.unlink(missing_ok=True)
    return [r[0] for r in rows]


@app.delete("/events/{event_id}")
def delete_event(event_id: int):
    """Remove a single disturbance: its database row and its WAV clip."""
    if not delete_events([event_id]):
        raise HTTPException(status_code=404, detail="Event not found")
    return {"deleted": event_id}


@app.post("/events/delete")
def delete_many(req: DeleteRequest):
    """Remove several disturbances at once (used by the select-all / bulk delete UI)."""
    if not req.ids:
        return {"deleted": []}
    return {"deleted": delete_events(req.ids)}


@app.get("/play/{file:path}")
def serve_audio(file: str):
    """Serve recorded WAV files for playback (file is e.g. 2026-11-07/11-14-10.wav)."""
    path = (OUT_DIR / file).resolve()
    if OUT_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run("dashboard:app", host="127.0.0.1", port=8000)
