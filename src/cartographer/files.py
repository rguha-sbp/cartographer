"""The files of one diagram: the .drawio fingerprint, its sibling image and the hand-edit guard."""

import hashlib
import json
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_path(drawio: Path) -> Path:
    return drawio.with_suffix(".svg")


def hand_edited(drawio: Path, curated: dict) -> bool:
    """True when a .drawio exists that the curated file does not vouch for."""
    return drawio.is_file() and sha256_file(drawio) != curated.get("drawio_sha256")


def record_sha256(curated_path: Path, sha256: str) -> None:
    curated = json.loads(curated_path.read_text())
    curated["drawio_sha256"] = sha256
    curated_path.write_text(json.dumps(curated, indent=2, ensure_ascii=False) + "\n")
