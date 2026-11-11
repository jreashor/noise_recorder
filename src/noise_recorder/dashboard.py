"""
Noise Recorder Dashboard - Web UI for reviewing recorded disturbances.
Reads from the SQLite database and serves HTML with embedded assets.

    noise-dashboard                 # then open http://127.0.0.1:8000
    noise-dashboard --port 8001 --data-dir ~/NoiseRecordings
    noise-dashboard --recorder-args "--device 0"   # flags for recorders started here
"""

import argparse
import json
import shlex
import sqlite3
from importlib.resources import files
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import config, control, db

TEMPLATE = files("noise_recorder") / "templates" / "dashboard.html"

EVENTS_SQL = """
    SELECT id, start, duration_s, peak, max_lz, max_la, laeq, lzeq,
           baseline_lz, unit, note, file
    FROM events
    ORDER BY start DESC
    LIMIT ?
"""
# Per-minute levels for one day
MINUTES_SQL = """
    SELECT minute AS time_bucket, laeq, lzeq, max_lz
    FROM minutes
    WHERE substr(minute, 1, 10) = ?
    ORDER BY minute
"""
# Loudest level per hour, for the all-days chart
HOURS_SQL = """
    SELECT substr(minute, 1, 13) || ':00' AS time_bucket, MAX(max_lz) AS max_lz
    FROM minutes
    GROUP BY substr(minute, 1, 13)
    ORDER BY 1
"""
# Every day with level readings or disturbances, newest first
DAYS_SQL = """
    SELECT substr(minute, 1, 10) AS day FROM minutes
    UNION
    SELECT date(start) FROM events
    ORDER BY 1 DESC
"""
DAILY_SQL = """
    SELECT date(start) as day, COUNT(*) as count, ROUND(MAX(max_lz), 1) as loudest,
           ROUND(SUM(duration_s)/60, 1) as total_min
    FROM events
    GROUP BY 1
    ORDER BY 1 DESC
"""


class DeleteRequest(BaseModel):
    ids: list[int]


def to_js(data):
    # Escape "</" so data can't close the surrounding <script> tag.
    return json.dumps(data).replace("</", "<\\/")


def create_app(data_dir: Path | None = None, recorder_args=(), recorder_cmd=None) -> FastAPI:
    """recorder_args are extra noise-recorder flags; recorder_cmd replaces the whole
    command (for tests)."""
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

    def prune_missing_files():
        try:
            c = db.connect(db_file)
        except FileNotFoundError:
            return
        try:
            db.prune_missing_files(c, data)
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
        finally:
            c.close()

    def page_data(day=None):
        """day picks the chart's day: a date, "all" (hourly levels), or None for the latest."""
        prune_missing_files()
        days = [r["day"] for r in query(DAYS_SQL)]
        if day == "all":
            minutes = query(HOURS_SQL)
        else:
            day = day or (days[0] if days else None)
            minutes = query(MINUTES_SQL, (day,)) if day else []
        return {
            "events": query(EVENTS_SQL, (500,)),
            "minutes": minutes,
            "daily": query(DAILY_SQL),
            "days": days,
            "day": day,
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        """Serve the main dashboard page."""
        d = page_data()
        html = TEMPLATE.read_text()
        html = html.replace("{{{events_json}}}", to_js(d["events"]))
        html = html.replace("{{{minutes_json}}}", to_js(d["minutes"]))
        html = html.replace("{{{daily_data}}}", to_js(d["daily"]))
        html = html.replace("{{{days_json}}}", to_js(d["days"]))
        return HTMLResponse(content=html)

    @app.get("/data")
    def get_data(day: str | None = None):
        """The page's data as JSON, so it can update itself without reloading."""
        return page_data(day)

    def delete_events(ids):
        try:
            c = db.connect(db_file)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Database not found") from None
        try:
            return db.delete_events(c, ids, data)
        finally:
            c.close()

    @app.delete("/events/{event_id}")
    def delete_event(event_id: int):
        """Remove a single disturbance: its database row and its WAV clip."""
        if not delete_events([event_id]):
            raise HTTPException(status_code=404, detail="Event not found")
        return {"deleted": event_id}

    @app.post("/events/delete")
    def delete_many(req: DeleteRequest):
        """Remove several disturbances at once (used by the select-all / bulk delete UI)."""
        return {"deleted": delete_events(req.ids)}

    @app.get("/play/{file:path}")
    def serve_audio(file: str):
        """Serve recorded WAV files for playback (file is e.g. 2026-11-07/11-14-10.wav)."""
        path = (data / file).resolve()
        if data.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path, media_type="audio/wav")

    def recorder_status():
        pid = control.running_pid(data)
        return {
            "running": pid is not None,
            "pid": pid,
            "live": control.read_status(data) if pid else None,
            "log": control.log_tail(data),
        }

    def require_page_header(x_noise_dashboard):
        # A custom header can't be sent cross-site without CORS approval, so other
        # websites open in the browser can't switch the microphone on or off.
        if x_noise_dashboard != "1":
            raise HTTPException(status_code=403, detail="Missing X-Noise-Dashboard header")

    @app.get("/recorder")
    def get_recorder():
        """Whether the recorder is running, plus the last lines of its log."""
        return recorder_status()

    @app.post("/recorder/start")
    def start_recorder(x_noise_dashboard: str | None = Header(default=None)):
        require_page_header(x_noise_dashboard)
        if control.running_pid(data):
            raise HTTPException(status_code=409, detail="Recorder is already running")
        try:
            control.start(data, recorder_args, cmd=recorder_cmd)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from None
        return recorder_status()

    @app.post("/recorder/stop")
    def stop_recorder(x_noise_dashboard: str | None = Header(default=None)):
        require_page_header(x_noise_dashboard)
        try:
            if not control.stop(data):
                raise HTTPException(status_code=409, detail="Recorder isn't running")
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from None
        return recorder_status()

    def settings_response():
        return {
            "settings": control.load_settings(data),
            "limits": {k: limits for k, (_, limits) in control.SETTINGS.items()},
            "defaults": control.default_settings(),
        }

    @app.get("/recorder/settings")
    def get_settings():
        """Detection settings the recorder starts with, plus their allowed ranges."""
        return settings_response()

    @app.post("/recorder/settings")
    def set_settings(
        values: dict[str, float], x_noise_dashboard: str | None = Header(default=None)
    ):
        """Save detection settings; they apply the next time the recorder starts."""
        require_page_header(x_noise_dashboard)
        try:
            control.save_settings(data, values)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return settings_response()

    return app


def main(argv=None):
    p = argparse.ArgumentParser(description="Web dashboard for recorded disturbances.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--data-dir", help=f"default: $NOISE_DATA_DIR or {config.DEFAULT_DATA_DIR}")
    p.add_argument(
        "--recorder-args",
        default="",
        help='noise-recorder flags used by the Start button, e.g. "--device 0 --threshold 25"',
    )
    a = p.parse_args(argv)
    app = create_app(a.data_dir, shlex.split(a.recorder_args))
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
