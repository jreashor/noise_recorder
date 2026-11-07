"""Where recordings and the database live.

Defaults to ~/NoiseRecordings so data is kept outside the source tree.
Override with the NOISE_DATA_DIR environment variable or each tool's --data-dir flag.
"""

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / "NoiseRecordings"
DB_NAME = "noise.db"


def data_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("NOISE_DATA_DIR")
    return Path(env).expanduser() if env else DEFAULT_DATA_DIR


def db_path(directory: Path) -> Path:
    return directory / DB_NAME
