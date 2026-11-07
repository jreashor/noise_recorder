# Noise Recorder

An all-day ambient noise recorder for macOS that captures sound disturbances and logs them to a SQLite database.

## Overview

- **`noise_recorder.py`**: Core recording program that listens continuously, detects loud events above the room baseline, records WAV clips with pre-roll context (~5s), and logs metrics to SQLite.
- **`noise_report.py`**: Query tool for inspecting recorded events, generating summaries (hourly/daily), and exporting data.

## Setup

1. Create and activate virtual environment, then install Python packages:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install sounddevice numpy fastapi uvicorn
   ```
2. Calibrate (optional, for dB SPL instead of relative dBFS):
   ```bash
   # Play a steady sound and note the reading on a reference meter
   python3 noise_recorder.py --calibrate
   ```
3. Run all day:
   ```bash
   caffeinate -i python3 noise_recorder.py --device 2 --cal-offset 0
   ```

## Dashboard (Review Recorded Data)

Start the web dashboard to view disturbances interactively:
```bash
python3 dashboard.py
# Then open http://localhost:8000 in your browser
```

The dashboard provides:
- 📊 Interactive chart of noise levels over time
- 🔍 List of recorded events with timestamps and dB levels
- ▶️ Play back WAV recordings directly in the browser
- 📅 Daily/hourly summaries
- 🔎 Filter events by date
- 🗑️ Delete disturbances (row + WAV clip)

## Usage: Recording

| Flag | Description | Default |
|------|-------------|---------|
| `--device N` | Input device index (see `--list-devices`) | auto |
| `--cal-offset X` | Calibration offset for dB SPL conversion | 0.0 |
| `--rate S` | Sample rate (22050 saves disk space) | 44100 |
| `--threshold T` | dB above baseline that triggers recording | 10.0 |
| `--min-level L` | Absolute floor below which noise is ignored | -∞ |
| `--preroll P` | Pre-roll seconds (captured before event) | 5.0 |
| `--tail T` | Seconds of tail after event start | 5.0 |
| `--max-clip M` | Max clip duration in seconds | 300.0 |
| `--out D` | Output directory for WAV files | `noise_recordings` |

Run with:
```bash
caffeinate -i python3 noise_recorder.py --device 2
```

Leave it running all day (keep Mac plugged in). It will:
- Calibrate to room baseline (~10s)
- Record disturbances that exceed the threshold
- Retries automatically on glitches (e.g., mic unplugged)

## Usage: Reporting

### Top N Loudest Events
```bash
python3 noise_report.py top --n 20                  # by max LZ (unweighted)
python3 noise_report.py top --n 10 --by la          # by A-weighted level
python3 noise_report.py top --n 5 --since 2026-11-01
```

### Hourly Summary
```bash
python3 noise_report.py hourly
# Output: hour | events | loudest | avg_max
```

### Daily Summary
```bash
python3 noise_report.py daily
# Output: date | events | loudest | total_min
```

### Add Notes to Events
```bash
python3 noise_report.py note 42 "dragging furniture"
# Updates the 'note' field for event ID 42
```

### Remove Events
```bash
python3 noise_report.py delete 42 43               # deletes rows and their WAV clips
python3 noise_report.py delete 42 --keep-file      # deletes the row, keeps the WAV
```
You can also click **Delete** next to an event in the dashboard.

### Export Data
```bash
python3 noise_report.py export events.csv
# Writes CSV suitable for Excel / Numbers
```

## Database Schema

**Table: `events`**
| Column | Description |
|--------|-------------|
| `id` | Auto-incrementing row ID |
| `start` | ISO 8601 timestamp of event start |
| `duration_s` | Event duration in seconds |
| `peak` | Max instantaneous sample level (dBFS/SPL) |
| `max_lz` | Loudest 0.1s block, unweighted |
| `max_la` | Loudest 0.1s block, A-weighted |
| `laeq` | Energy average over event, A-weighted |
| `lzeq` | Energy average over event, unweighted |
| `baseline_lz` | Room level before event |
| `unit` | `'dB SPL'` or `'dBFS'` |
| `file` | WAV filename |
| `note` | Free text annotation |

**Table: `minutes`** (per-minute logging for baseline reference)
| Column | Description |
|--------|-------------|
| `minute` | ISO 8601 date-time (YYYY-MM-DD HH:MM) |
| `laeq` | Average A-weighted level |
| `lzeq` | Average unweighted level |
| `max_lz` | Max instantaneous level |

## Files

- `noise_recorder.py` – Main recording script
- `noise_report.py` – CLI query and reporting tool
- `dashboard.py` – Web dashboard for interactive review (runs FastAPI server)
- `setup.sh` – One-liner setup script (creates venv + installs deps)
- `requirements.txt` – Python dependencies
- `noise_recordings/` – Output directory for WAV clips and SQLite database (`noise.db`)
