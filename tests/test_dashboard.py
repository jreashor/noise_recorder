import json
import re

import pytest
from fastapi.testclient import TestClient

from noise_recorder.dashboard import create_app


def embedded(html, name):
    """Parse the JSON the server injected into `var <name> = ...;`."""
    return json.loads(re.search(rf"var {name} = (.*?);\n", html).group(1))


@pytest.fixture
def client(data_dir):
    return TestClient(create_app(data_dir))


def test_page_embeds_data(client):
    html = client.get("/").text
    events = embedded(html, "events")
    assert [e["id"] for e in events] == [2, 1]
    assert events[1]["max_lz"] == -20.0
    assert len(embedded(html, "minutes")) == 5  # latest day only
    assert embedded(html, "days") == ["2026-11-07", "2026-11-06"]
    assert embedded(html, "dailyData") == [
        {"day": "2026-11-07", "count": 2, "loudest": -19.0, "total_min": 0.3}
    ]
    assert "{{{" not in html


def test_page_works_without_database(tmp_path):
    html = TestClient(create_app(tmp_path)).get("/").text
    assert embedded(html, "events") == []
    assert not (tmp_path / "noise.db").exists()


def test_play_serves_wav(client):
    r = client.get("/play/2026-11-07/11-14-10.wav")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


@pytest.mark.parametrize("path", ["2026-11-07/missing.wav", "..%2F..%2Fetc%2Fpasswd"])
def test_play_rejects_bad_paths(client, path):
    assert client.get(f"/play/{path}").status_code == 404


def test_delete_event(client, data_dir):
    assert client.delete("/events/1").json() == {"deleted": 1}
    assert not (data_dir / "2026-11-07/11-14-10.wav").exists()
    assert [e["id"] for e in embedded(client.get("/").text, "events")] == [2]
    assert client.delete("/events/1").status_code == 404


def test_bulk_delete(client, data_dir):
    r = client.post("/events/delete", json={"ids": [1, 2, 999]})
    assert r.status_code == 200
    assert sorted(r.json()["deleted"]) == [1, 2]
    assert not list((data_dir / "2026-11-07").iterdir())
    assert embedded(client.get("/").text, "events") == []
    assert client.post("/events/delete", json={"ids": []}).json() == {"deleted": []}
    assert client.post("/events/delete", json={"ids": ["x"]}).status_code == 422


def test_page_load_prunes_events_with_missing_wav(client, data_dir):
    (data_dir / "2026-11-07/11-14-10.wav").unlink()
    assert [e["id"] for e in embedded(client.get("/").text, "events")] == [2]


def test_data_endpoint_matches_page(client):
    html = client.get("/").text
    d = client.get("/data").json()
    assert d["events"] == embedded(html, "events")
    assert d["minutes"] == embedded(html, "minutes")
    assert d["daily"] == embedded(html, "dailyData")


def test_data_endpoint_picks_chart_day(client):
    d = client.get("/data", params={"day": "2026-11-06"}).json()
    assert d["day"] == "2026-11-06"
    assert [m["max_lz"] for m in d["minutes"]] == [-1.0]
    assert len(d["events"]) == 2  # the page filters the list itself
    assert client.get("/data").json()["day"] == "2026-11-07"
    assert client.get("/data", params={"day": "2026-01-01"}).json()["minutes"] == []


def test_data_endpoint_all_days_is_hourly(client):
    d = client.get("/data", params={"day": "all"}).json()
    assert d["minutes"] == [
        {"time_bucket": "2026-11-06 09:00", "max_lz": -1.0},
        {"time_bucket": "2026-11-07 11:00", "max_lz": -30.0},
    ]


def test_data_endpoint_prunes_missing_wav(client, data_dir):
    (data_dir / "2026-11-07/11-14-10.wav").unlink()
    assert [e["id"] for e in client.get("/data").json()["events"]] == [2]
