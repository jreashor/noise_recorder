"""Start, stop and check on the recorder process (used by the dashboard).

The recorder writes its PID to <data dir>/recorder.pid while it runs, so a recorder
started from a terminal is seen (and can be stopped) here too. Output from recorders
started here goes to <data dir>/recorder.log.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PID_NAME = "recorder.pid"
LOG_NAME = "recorder.log"
STATUS_NAME = "recorder_status.json"
STATUS_MAX_AGE_S = 5  # older status means the recorder is stuck or gone
SETTINGS_NAME = "recorder_settings.json"

# Detection settings editable from the dashboard: default and allowed (min, max).
# The recorder uses the saved values as its defaults; command-line flags still override.
SETTINGS = {
    "threshold": (30.0, (1.0, 60.0)),  # dB above the room that counts as a disturbance
    "min_duration": (0.5, (0.0, 60.0)),  # shorter disturbances aren't saved (s)
    "preroll": (1.0, (0.0, 30.0)),  # audio kept from before the disturbance (s)
    "tail": (5.0, (0.5, 120.0)),  # quiet that ends it; shorter gaps join one clip (s)
}

_children = []  # Popen objects for recorders we started, so they get reaped


def pid_file(directory: Path) -> Path:
    return directory / PID_NAME


def log_file(directory: Path) -> Path:
    return directory / LOG_NAME


def _reap():
    for p in list(_children):
        if p.poll() is not None:
            _children.remove(p)


def _is_recorder(pid: int) -> bool:
    """True if pid is alive and is a noise recorder (guards against reused PIDs)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    cmd = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    ).stdout
    return "noise_recorder" in cmd or "noise-recorder" in cmd


def running_pid(directory: Path) -> int | None:
    """PID of the running recorder for this data directory, or None."""
    _reap()
    path = pid_file(directory)
    try:
        pid = int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    if _is_recorder(pid):
        return pid
    path.unlink(missing_ok=True)  # stale: the recorder died without cleaning up
    return None


def write_pid(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    pid_file(directory).write_text(str(os.getpid()))


def clear_pid(directory: Path):
    (directory / STATUS_NAME).unlink(missing_ok=True)
    path = pid_file(directory)
    try:
        if int(path.read_text().strip()) == os.getpid():
            path.unlink()
    except (FileNotFoundError, ValueError):
        pass


def write_status(directory: Path, status: dict):
    """Atomically replace the live status file (written by the recorder ~once a second)."""
    path = directory / STATUS_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status))
    os.replace(tmp, path)


def read_status(directory: Path) -> dict | None:
    """The recorder's latest live status, or None if missing or stale."""
    try:
        status = json.loads((directory / STATUS_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return None
    if time.time() - status.get("updated", 0) > STATUS_MAX_AGE_S:
        return None
    return status


def default_settings() -> dict:
    return {k: default for k, (default, _) in SETTINGS.items()}


def validate_settings(values: dict) -> dict:
    """Known keys as floats within their limits; raises ValueError otherwise."""
    out = {}
    for key, value in values.items():
        if key not in SETTINGS:
            raise ValueError(f"Unknown setting {key!r}")
        lo, hi = SETTINGS[key][1]
        v = float(value)
        if not lo <= v <= hi:
            raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
        out[key] = v
    return out


def load_settings(directory: Path) -> dict:
    """Saved settings over the defaults; a missing or invalid file gives the defaults."""
    settings = default_settings()
    try:
        saved = json.loads((directory / SETTINGS_NAME).read_text())
        settings.update(validate_settings({k: v for k, v in saved.items() if k in SETTINGS}))
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        pass
    return settings


def save_settings(directory: Path, values: dict) -> dict:
    settings = load_settings(directory)
    settings.update(validate_settings(values))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SETTINGS_NAME).write_text(json.dumps(settings, indent=2))
    return settings


def log_tail(directory: Path, n: int = 5) -> list[str]:
    try:
        lines = log_file(directory).read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return []
    return [line for line in lines if line.strip()][-n:]


def start(directory: Path, extra_args=(), cmd=None, timeout: float = 5.0) -> int:
    """Launch the recorder in the background and return its PID.

    Raises RuntimeError if one is already running or it fails to start.
    """
    if running_pid(directory):
        raise RuntimeError("Recorder is already running")
    if cmd is None:
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "noise_recorder.recorder",
            "--data-dir",
            str(directory),
            *extra_args,
        ]
        if shutil.which("caffeinate"):  # keep the Mac awake while recording
            cmd = ["caffeinate", "-i", *cmd]
    directory.mkdir(parents=True, exist_ok=True)
    with open(log_file(directory), "a") as log:
        # New session: Ctrl+C on the dashboard doesn't stop the recorder.
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _children.append(proc)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = running_pid(directory)
        if pid:
            return pid
        if proc.poll() is not None:
            tail = "\n".join(log_tail(directory, 3))
            raise RuntimeError(f"Recorder exited during startup:\n{tail}")
        time.sleep(0.1)
    raise RuntimeError(f"Recorder didn't start within {timeout:.0f} s; see {log_file(directory)}")


def stop(directory: Path, timeout: float = 10.0) -> bool:
    """Stop the recorder like Ctrl+C (it saves any event in progress).

    Returns False if no recorder was running.
    """
    pid = running_pid(directory)
    if not pid:
        return False
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _reap()
        if not _is_recorder(pid):
            pid_file(directory).unlink(missing_ok=True)
            return True
        time.sleep(0.1)
    raise RuntimeError(f"Recorder (PID {pid}) didn't stop within {timeout:.0f} s")
