"""Where cartographer keeps what is not committed: the facts, the schema and the verify output of a stack."""

import json
import os
from pathlib import Path


def cache_dir(stack: str) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    path = root / "cartographer" / stack
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
