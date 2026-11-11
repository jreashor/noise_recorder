import os
import subprocess
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from noise_recorder import control
from noise_recorder.dashboard import create_app

HEADERS = {"X-Noise-Dashboard": "1"}


@pytest.fixture
def fake_cmd(tmp_path):
    """A stand-in recorder: writes the PID file, runs until Ctrl+C, then cleans up.

    Its filename contains "noise_recorder" so control recognises the process.
    """
    script = tmp_path / "fake_noise_recorder.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import time
            from pathlib import Path
            from noise_recorder import control
            out = Path({str(tmp_path)!r})
            control.write_pid(out)
            print("Listening...", flush=True)
            try:
                while True:
                    time.sleep(0.05)
            except KeyboardInterrupt:
                print("Stopped.", flush=True)
            finally:
                control.clear_pid(out)
            """
        )
    )
    return [sys.executable, str(script)]


@pytest.fixture
def client(tmp_path, fake_cmd):
    c = TestClient(create_app(tmp_path, recorder_cmd=fake_cmd))
    yield c
    control.stop(tmp_path)  # never leave a stray process behind


def test_start_and_stop(client, tmp_path):
    assert client.get("/recorder").json()["running"] is False

    r = client.post("/recorder/start", headers=HEADERS)
    assert r.status_code == 200
    status = r.json()
    assert status["running"] is True
    assert (tmp_path / "recorder.pid").read_text() == str(status["pid"])
    assert client.post("/recorder/start", headers=HEADERS).status_code == 409

    r = client.post("/recorder/stop", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["running"] is False
    assert not (tmp_path / "recorder.pid").exists()
    assert "Stopped." in (tmp_path / "recorder.log").read_text()  # stopped gracefully
    assert client.post("/recorder/stop", headers=HEADERS).status_code == 409


@pytest.mark.parametrize("action", ["start", "stop"])
def test_control_requires_page_header(client, tmp_path, action):
    assert client.post(f"/recorder/{action}").status_code == 403
    assert not (tmp_path / "recorder.pid").exists()


def test_stale_pid_file_is_ignored_and_removed(client, tmp_path):
    # A PID that belongs to some other live process must never be signalled.
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "recorder.pid").write_text(str(other.pid))
        assert client.get("/recorder").json()["running"] is False
        assert not (tmp_path / "recorder.pid").exists()
        assert client.post("/recorder/stop", headers=HEADERS).status_code == 409
        assert other.poll() is None  # still alive: it wasn't signalled
    finally:
        other.kill()
        other.wait()


def test_start_reports_early_exit(tmp_path):
    cmd = [sys.executable, "-c", "print('no such device'); raise SystemExit(1)"]
    r = TestClient(create_app(tmp_path, recorder_cmd=cmd)).post("/recorder/start", headers=HEADERS)
    assert r.status_code == 500
    assert "no such device" in r.json()["detail"]


def test_clear_pid_only_removes_own_pid(tmp_path):
    (tmp_path / "recorder.pid").write_text(str(os.getpid() + 1))
    control.clear_pid(tmp_path)
    assert (tmp_path / "recorder.pid").exists()
    control.write_pid(tmp_path)
    control.clear_pid(tmp_path)
    assert not (tmp_path / "recorder.pid").exists()


def test_read_status_ignores_stale(tmp_path):
    import time

    control.write_status(tmp_path, {"updated": time.time(), "level": -40.0})
    assert control.read_status(tmp_path)["level"] == -40.0
    control.write_status(tmp_path, {"updated": time.time() - 60, "level": -40.0})
    assert control.read_status(tmp_path) is None
    control.clear_pid(tmp_path)
    assert not (tmp_path / control.STATUS_NAME).exists()


def test_settings_defaults_save_and_validate(tmp_path):
    assert control.load_settings(tmp_path) == control.default_settings()
    assert control.load_settings(tmp_path)["threshold"] == 30.0
    control.save_settings(tmp_path, {"min_duration": 3})
    assert control.load_settings(tmp_path)["min_duration"] == 3.0
    for bad in ({"threshold": 0}, {"tail": 999}, {"bogus": 1}):
        with pytest.raises(ValueError):
            control.save_settings(tmp_path, bad)
    (tmp_path / control.SETTINGS_NAME).write_text("not json")
    assert control.load_settings(tmp_path) == control.default_settings()


def test_settings_endpoints(client):
    d = client.get("/recorder/settings").json()
    assert d["settings"] == d["defaults"] == control.default_settings()
    assert client.post("/recorder/settings", json={"threshold": 25}).status_code == 403
    r = client.post("/recorder/settings", json={"threshold": 25}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["settings"]["threshold"] == 25.0
    r = client.post("/recorder/settings", json={"threshold": 500}, headers=HEADERS)
    assert r.status_code == 422 and "between" in r.json()["detail"]
    assert client.get("/recorder/settings").json()["settings"]["threshold"] == 25.0
