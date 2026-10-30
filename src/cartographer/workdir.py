"""Where cartographer keeps what is not committed: the facts, the schema and the verify output of a diagram."""

import json
import os
from pathlib import Path


def cache_root() -> Path:
    """Everything cartographer downloads or caches. The plugin launcher points CARTOGRAPHER_HOME at its data folder."""
    if home := os.environ.get("CARTOGRAPHER_HOME"):
        return Path(home)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "cartographer"


def cache_dir(name: str) -> Path:
    path = cache_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
