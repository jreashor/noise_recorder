"""
Noise Recorder Dashboard - Web UI for reviewing recorded disturbances.
Reads from the SQLite database and serves HTML with embedded assets.

    noise-dashboard                 # then open http://127.0.0.1:8000
    noise-dashboard --port 8001 --data-dir ~/NoiseRecordings
"""

import argparse
import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import config, db

TEMPLATE = files("noise_recorder") / "templates" / "dashboard.html"

EVENTS_SQL = """
    SELECT id, start, duration_s, peak, max_lz, max_la, laeq, lzeq,
           baseline_lz, unit, note, file
    FROM events
    ORDER BY start DESC
    LIMIT ?
"""
# Per-minute levels for the most recent recorded day
MINUTES_SQL = """
    SELECT minute AS time_bucket, laeq, lzeq, max_lz
    FROM minutes
    WHERE substr(minute, 1, 10) = (SELECT MAX(substr(minute, 1, 10)) FROM minutes)
    ORDER BY minute
"""
DAILY_SQL = """
    SELECT date(start) as day, COUNT(*) as count, ROUND(MAX(max_lz), 1) as loudest,
           ROUND(SUM(duration_s)/60, 1) as total_min
    FROM events
    GROUP BY 1
    ORDER BY 1 DESC
"""


def to_js(data):
    # Escape "</" so data can't close the surrounding <script> tag.
    return json.dumps(data).replace("</", "<\\/")


def create_app(data_dir: Path | None = None) -> FastAPI:
    data = config.data_dir(data_dir)
    db_file = config.db_path(data)
    app = FastAPI(title="Noise Recorder Dashboard")

    def query(sql, params=()):
        """Rows as dicts; [] if the database or its tables don't exist yet."""
        try:
            c = db.connect(db_file, readonly=True)
        except FileNotFoundError:
            return []
        try:
            return [dict(r) for r in c.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return []
            raise
        finally:
            c.close()

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        """Serve the main dashboard page."""
        html = TEMPLATE.read_text()
        html = html.replace("{{{events_json}}}", to_js(query(EVENTS_SQL, (500,))))
        html = html.replace("{{{minutes_json}}}", to_js(query(MINUTES_SQL)))
        html = html.replace("{{{daily_data}}}", to_js(query(DAILY_SQL)))
        return HTMLResponse(content=html)

    @app.delete("/events/{event_id}")
    def delete_event(event_id: int):
        """Remove a disturbance: its database row and its WAV clip."""
        try:
            c = db.connect(db_file)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Database not found") from None
        try:
            if not db.delete_event(c, event_id, data):
                raise HTTPException(status_code=404, detail="Event not found")
        finally:
            c.close()
        return {"deleted": event_id}

    @app.get("/play/{file:path}")
    def serve_audio(file: str):
        """Serve recorded WAV files for playback (file is e.g. 2026-11-07/11-14-10.wav)."""
        path = (data / file).resolve()
        if data.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path, media_type="audio/wav")

    return app


def main(argv=None):
    p = argparse.ArgumentParser(description="Web dashboard for recorded disturbances.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--data-dir", help=f"default: $NOISE_DATA_DIR or {config.DEFAULT_DATA_DIR}")
    a = p.parse_args(argv)
    uvicorn.run(create_app(a.data_dir), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
