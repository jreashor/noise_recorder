# Noise Recorder

An all-day ambient noise recorder for macOS. It saves WAV clips of loud disturbances, logs levels to SQLite, and comes with a CLI report tool and a web dashboard.

| Command | What it does |
|---|---|
| `noise-recorder` | Listens continuously, detects events above the room baseline, saves clips with pre-roll |
| `noise-report` | Top events, hourly/daily summaries, notes, deletion, CSV export |
| `noise-dashboard` | Web UI: level chart, event list with playback, settings, start/stop recording |

## Setup

Requires macOS, Python 3.11+ and PortAudio.

```bash
brew install portaudio
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```bash
source .venv/bin/activate
noise-recorder --list-devices            # find your microphone's index
noise-dashboard --recorder-args "--device 0"
```

Open <http://127.0.0.1:8000>, press **Start recording**, and stay quiet for ~10 s while it measures the room. Ctrl+C stops the dashboard; a recorder it started keeps running until you press **Stop recording**.

Prefer a terminal? Run `caffeinate -i noise-recorder --device 0` in one window and `noise-dashboard` in another.

Data lives in `~/NoiseRecordings` (`noise.db` plus one folder of WAVs per day). Override with `NOISE_DATA_DIR` or `--data-dir`.

## Recorder

| Flag | Description | Default |
|------|-------------|---------|
| `--device N` | Input device index | system default |
| `--threshold T` | dB above baseline that triggers recording | 30.0* |
| `--min-duration S` | Seconds a disturbance must last to be saved | 0* |
| `--preroll P` | Seconds captured before the event | 1.0* |
| `--tail T` | Quiet seconds that end an event (shorter pauses join into one clip) | 90.0* |
| `--max-clip M` | Max clip length in seconds | 900.0 |
| `--min-level L` | Absolute floor below which noise is ignored | none |
| `--gain G` | dB added to saved WAVs (database levels unaffected) | 18.0 |
| `--rate S` | Sample rate | 44100 |
| `--cal-offset X` | Calibration offset for dB SPL | 0.0 (dBFS) |
| `--data-dir D` | Where WAVs and `noise.db` go | `~/NoiseRecordings` |

\* Defaults come from the dashboard's **⚙ Settings** (`recorder_settings.json` in the data directory); command-line flags override them.

For dB SPL instead of dBFS: play a steady sound, run `noise-recorder --calibrate`, enter the reading from a sound level meter, and pass the printed `--cal-offset`. Keep the macOS input volume fixed afterwards.

## Dashboard

```bash
noise-dashboard [--port 8001] [--recorder-args "--device 0"]
```

- **Start/Stop recording** runs the recorder in the background under `caffeinate -i`; output goes to `recorder.log` in the data directory.
- **⚙ Settings** changes sensitivity, minimum length, tail and pre-roll. Saving while recording restarts the recorder.
- **Day** and **Min level** filter the chart and event list. Click a dot to jump to its row.

## Report

```bash
noise-report top --n 10 --by la --since 2026-11-01
noise-report hourly
noise-report daily
noise-report note 42 "dragging furniture"
noise-report delete 42 43 [--keep-file]   # can't be undone
noise-report export events.csv
```

## Troubleshooting

- **"A recorder is already running … (PID N)"**: stop it from the dashboard, or `kill -INT N` (saves any event in progress). `pgrep -fl noise` lists running programs.
- **"address already in use"**: another dashboard is running (`pkill -f noise-dashboard`), or use `--port`.

## Database schema

**`events`**: one row per disturbance: `id`, `start` (ISO 8601 local), `duration_s`, `peak`, `max_lz`/`max_la` (loudest 0.1 s block, unweighted/A-weighted), `lzeq`/`laeq` (energy average), `baseline_lz` (room level before the event), `unit` (`dB SPL` or `dBFS`), `file` (WAV path relative to the data directory), `note`.

**`minutes`**: per-minute baseline levels: `minute`, `laeq`, `lzeq`, `max_lz`.

## Development

```bash
pytest          # no microphone needed
ruff check .
ruff format .
```

