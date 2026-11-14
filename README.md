# Noise Recorder

An all-day ambient noise recorder for macOS that captures sound disturbances and logs them to a SQLite database, with a CLI report tool and a web dashboard for review.

| Command | What it does |
|---|---|
| `noise-recorder` | Listens continuously, detects loud events above the room baseline, saves WAV clips with ~2 s pre-roll, and logs levels to SQLite |
| `noise-report` | CLI for top events, hourly/daily summaries, notes, deleting and CSV export |
| `noise-dashboard` | Web UI: chart of levels, event list with playback, delete button, daily summary |

## Quick start

After [setup](#setup), use two terminal windows, one for each program. Run these from the project folder:

**Terminal 1: recorder** (leave it running all day)
```bash
cd ~/Projects/noise_recorder
source .venv/bin/activate
caffeinate -i noise-recorder --device 0
```
Stay quiet for the first ~10 s while it measures the room. Each disturbance prints a `saved …` line.

**Terminal 2: dashboard**
```bash
cd ~/Projects/noise_recorder
source .venv/bin/activate
noise-dashboard
```
Open <http://127.0.0.1:8000>, and refresh the page to see new events.

**One terminal instead:** run `noise-dashboard --recorder-args "--device 0"` alone and press **Start recording** in the dashboard (see [Dashboard](#dashboard)).

**Stopping:** press Ctrl+C in each window. Closing a window also stops whatever is running in it.

**Is it running?** `pgrep -fl noise` lists both programs (a recorder started from the dashboard shows as `python -m noise_recorder.recorder`).

**"A recorder is already running for … (PID N)"** means a recorder is already running, usually one started from the dashboard. Press **Stop recording** in the dashboard, or run `kill -INT N` (same as Ctrl+C, so any event in progress is saved).

## Setup

One-time, requires macOS, Python 3.11+ and PortAudio.

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

It calibrates to the room baseline (~10 s, stay quiet), then records disturbances that exceed the threshold and last at least the minimum length. It retries automatically on glitches (e.g. mic unplugged). Leave the terminal open; Ctrl+C stops it.

| Flag | Description | Default |
|------|-------------|---------|
| `--device N` | Input device index (see `--list-devices`) | system default |
| `--cal-offset X` | Calibration offset for dB SPL conversion | 0.0 (dBFS) |
| `--rate S` | Sample rate (22050 saves disk space) | 44100 |
| `--threshold T` | dB above baseline that triggers recording | 30.0* |
| `--min-duration S` | Seconds a disturbance must last to be saved; shorter ones are ignored | 0.5* |
| `--min-level L` | Absolute floor below which noise is ignored | none |
| `--preroll P` | Seconds captured before the event | 1.0* |
| `--tail T` | Quiet seconds that end an event; shorter pauses join into one clip. Only 1 s of that quiet is saved | 5.0* |
| `--max-clip M` | Max clip duration in seconds | 300.0 |
| `--gain G` | dB added to every saved WAV, the same for all clips (levels in the database are unaffected); `0` saves audio as captured | 18.0 |
| `--data-dir D` | Where WAVs and `noise.db` go | `~/NoiseRecordings` |

\* Defaults for these four come from the dashboard's **⚙ Settings** (saved in `~/NoiseRecordings/recorder_settings.json`); a flag on the command line overrides them.

**Calibration (optional, for dB SPL instead of relative dBFS):** play a steady sound, run `noise-recorder --calibrate`, enter the reading from a reference sound level meter, and pass the printed `--cal-offset`. Keep the macOS input volume fixed afterwards.

## Dashboard

```bash
noise-dashboard              # then open http://127.0.0.1:8000
noise-dashboard --port 8001  # if 8000 is in use
noise-dashboard --recorder-args "--device 0"   # flags for the Start button
```

**Start / stop recording from the dashboard:** the **Start recording** button runs `noise-recorder` in the background (under `caffeinate -i`, so the Mac stays awake) and **Stop recording** stops it like Ctrl+C, saving any event in progress. The status shows a recorder started from a terminal too, and only one can run at a time. Its output goes to `~/NoiseRecordings/recorder.log`, and the latest line appears under the toolbar. A recorder started from the dashboard keeps running if you close the dashboard; open it again to stop it. Pass recorder flags with `--recorder-args`; without `--device` the Start button uses the system default microphone.

**⚙ Settings** adjusts sensitivity (dB above the room), the minimum length a disturbance must last to be saved, how long a pause can be and still join one clip, and how much audio before the sound is kept. Saving while recording restarts the recorder so the changes apply (it measures the room again for ~10 s). While recording, the line under the toolbar shows the live level, the room level, the trigger point and how long the current disturbance has lasted.

Shows a chart of levels with each disturbance marked as a dot, the event list with ▶ Play and Delete buttons, and a daily summary. **Day** picks one recorded day (per-minute levels) or all days (loudest per hour), and **Min level** hides disturbances that rose less than that many dB above the room; the chart and list follow both. Click a dot to jump to its row. Each event shows how far it rose above the room's baseline (e.g. `+19.5 dB`). Absolute levels are in dBFS, which are always negative, unless you calibrate with `--cal-offset`. Ctrl+C stops it.

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
