"""Bump the pinned draw.io web app to the newest release that is at least 7 days old.

Stdlib only. Prints the new version or "up to date" and exits 0 either way.
Usage: python scripts/bump_drawio.py [--dry-run]
"""

import argparse
import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

PIN_PATH = Path(__file__).resolve().parent.parent / "src" / "cartographer" / "drawio_pin.json"
RELEASES_URL = "https://api.github.com/repos/jgraph/drawio/releases?per_page=30"
ASSET_NAME = "draw.war"
MIN_AGE = timedelta(days=7)
TIMEOUT_S = 60
CHUNK = 1 << 20


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    page: str


def parse_version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.removeprefix("v").split("."))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def select_release(releases: list[dict], now: datetime) -> Release | None:
    """The highest-versioned stable release published at least MIN_AGE ago that carries a draw.war asset."""
    best: tuple[tuple[int, ...], Release] | None = None
    for rel in releases:
        if rel["draft"] or rel["prerelease"]:
            continue
        if now - datetime.fromisoformat(rel["published_at"]) < MIN_AGE:
            continue
        asset = next((a for a in rel["assets"] if a["name"] == ASSET_NAME), None)
        if asset is None:
            continue
        try:
            key = parse_version(rel["tag_name"])
        except ValueError:
            continue
        if best is None or key > best[0]:
            best = (key, Release(rel["tag_name"].removeprefix("v"), asset["browser_download_url"], rel["html_url"]))
    return best[1] if best else None


def render_pin(pin: dict, release: Release, sha256: str) -> str:
    updated = {**pin, "version": release.version, "url": release.url, "sha256": sha256}
    return json.dumps(updated, indent=2) + "\n"


def _request(url: str) -> urllib.request.Request:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def fetch_releases() -> list[dict]:
    with urllib.request.urlopen(_request(RELEASES_URL), timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def stream_sha256(url: str) -> str:
    digest = hashlib.sha256()
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as resp:
        while chunk := resp.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print what would change without writing")
    dry_run = parser.parse_args().dry_run

    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    release = select_release(fetch_releases(), datetime.now(UTC))
    if release is None or not is_newer(release.version, pin["version"]):
        print("up to date")
        return
    sha256 = stream_sha256(release.url)
    if dry_run:
        print(f"would bump {pin['version']} -> {release.version} ({release.url}, sha256 {sha256})")
        return
    PIN_PATH.write_text(render_pin(pin, release, sha256), encoding="utf-8")
    print(release.version)


if __name__ == "__main__":
    main()
