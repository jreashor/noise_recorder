# Noise Recorder

An all-day ambient noise recorder for macOS that captures sound disturbances and logs them to a SQLite database, with a CLI report tool and a web dashboard for review.

| Command | What it does |
|---|---|
| `noise-recorder` | Listens continuously, detects loud events above the room baseline, saves WAV clips with ~5 s pre-roll, and logs levels to SQLite |
| `noise-report` | CLI for top events, hourly/daily summaries, notes, deleting and CSV export |
| `noise-dashboard` | Web UI: chart of levels, event list with playback, delete button, daily summary |

## Setup

Requires macOS, Python 3.11+ and PortAudio.

```bash
brew install portaudio
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"      # installs the three commands above (+ test tools)
```

In a new terminal, only `source .venv/bin/activate` is needed.

## Where data is stored

Recordings and the database live in **`~/NoiseRecordings`**, outside the code folder:

```
~/NoiseRecordings/
├── noise.db                 # SQLite database
└── 2026-11-07/11-14-10.wav  # one folder per day
```

Change it with the `NOISE_DATA_DIR` environment variable or each command's `--data-dir` flag.

## Recording

```bash
noise-recorder --list-devices                 # find your microphone's index
caffeinate -i noise-recorder --device 0       # run all day (keep the Mac plugged in)
```

It calibrates to the room baseline (~10 s, stay quiet), then records disturbances that exceed the threshold. It retries automatically on glitches (e.g. mic unplugged). Leave the terminal open; Ctrl+C stops it.

| Flag | Description | Default |
|------|-------------|---------|
| `--device N` | Input device index (see `--list-devices`) | system default |
| `--cal-offset X` | Calibration offset for dB SPL conversion | 0.0 (dBFS) |
| `--rate S` | Sample rate (22050 saves disk space) | 44100 |
| `--threshold T` | dB above baseline that triggers recording | 10.0 |
| `--min-level L` | Absolute floor below which noise is ignored | none |
| `--preroll P` | Seconds captured before the event | 5.0 |
| `--tail T` | Quiet seconds that end an event | 5.0 |
| `--max-clip M` | Max clip duration in seconds | 300.0 |
| `--data-dir D` | Where WAVs and `noise.db` go | `~/NoiseRecordings` |

**Calibration (optional, for dB SPL instead of relative dBFS):** play a steady sound, run `noise-recorder --calibrate`, enter the reading from a reference sound level meter, and pass the printed `--cal-offset`. Keep the macOS input volume fixed afterwards.

## Dashboard

```bash
noise-dashboard              # then open http://127.0.0.1:8000
noise-dashboard --port 8001  # if 8000 is in use
```

Shows a chart of per-minute levels for the latest recorded day, the event list with ▶ Play and Delete buttons, and a daily summary. Ctrl+C stops it.

If it says *address already in use*, another copy is running. Find and stop it:

```bash
pgrep -fl noise-dashboard
pkill -f noise-dashboard
```

## Reporting

```bash
noise-report top --n 20                   # loudest by max LZ (unweighted)
noise-report top --n 10 --by la           # by A-weighted level
noise-report top --since 2026-11-01
noise-report hourly                       # hour | events | loudest | avg_max
noise-report daily                        # date | events | loudest | total_min
noise-report note 42 "dragging furniture" # annotate event 42
noise-report delete 42 43                 # delete rows and their WAV clips
noise-report delete 42 --keep-file        # delete the row, keep the WAV
noise-report export events.csv            # CSV for Excel / Numbers
```

Deleting can't be undone.

## Database schema

**`events`**: one row per disturbance

| Column | Description |
|--------|-------------|
| `id` | Auto-incrementing row ID |
| `start` | ISO 8601 local timestamp of event start |
| `duration_s` | Clip duration in seconds |
| `peak` | Max instantaneous sample level |
| `max_lz` / `max_la` | Loudest 0.1 s block, unweighted / A-weighted |
| `lzeq` / `laeq` | Energy average over the event, unweighted / A-weighted |
| `baseline_lz` | Room level just before the event |
| `unit` | `dB SPL` or `dBFS` |
| `file` | WAV path relative to the data directory |
| `note` | Free-text annotation |

**`minutes`**: per-minute levels (`minute`, `laeq`, `lzeq`, `max_lz`) for baseline reference.

## Development

```bash
pytest                  # run tests (no microphone needed)
ruff check .            # lint
ruff format .           # format
```

```
├── pyproject.toml              # metadata, dependencies, commands, tool config
├── src/noise_recorder/
│   ├── config.py               # data directory / database location
│   ├── db.py                   # schema and shared database helpers
│   ├── recorder.py             # noise-recorder
│   ├── report.py               # noise-report
│   ├── dashboard.py            # noise-dashboard (FastAPI)
│   └── templates/dashboard.html
└── tests/
```
