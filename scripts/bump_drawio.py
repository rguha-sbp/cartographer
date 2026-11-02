"""Bump the pinned draw.io web app to the newest release that is at least 7 days old and has no open advisory.

When jgraph has published a security advisory against the pinned version, the 7-day wait is skipped for a release
that fixes it; if none exists yet the script exits 1 so the scheduled run fails loudly.
Stdlib only. Prints the new version or "up to date".
Usage: python scripts/bump_drawio.py [--dry-run]
"""

import argparse
import hashlib
import json
import operator
import os
import re
import sys
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

PIN_PATH = Path(__file__).resolve().parent.parent / "src" / "cartographer" / "drawio_pin.json"
RELEASES_URL = "https://api.github.com/repos/jgraph/drawio/releases?per_page=30"
ADVISORIES_URL = "https://api.github.com/repos/jgraph/drawio/security-advisories?state=published&per_page=100"
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


CLAUSE = re.compile(r"(<=|>=|<|>|=)?\s*v?(\d+(?:\.\d+)*)")
COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "=": operator.eq}


def affects(spec: str, version: str) -> bool:
    """Whether `version` is in an advisory range such as "<= 32.6.8", "30.2.4" or ">= 31.0.0, < 31.4.4"."""
    key = parse_version(version)
    hits = []
    for clause in spec.split(","):
        match = CLAUSE.fullmatch(clause.strip())
        if match is None:
            raise ValueError(f"unreadable advisory version range: {spec!r}")
        op, bound = match.groups()
        hits.append(COMPARE[op or "="](key, parse_version(bound)))
    return all(hits)


def open_advisories(advisories: list[dict], version: str) -> list[str]:
    """GHSA ids of the advisories not withdrawn whose ranges include `version`."""
    return [
        adv["ghsa_id"]
        for adv in advisories
        if adv["withdrawn_at"] is None
        and any(affects(vuln["vulnerable_version_range"], version) for vuln in adv["vulnerabilities"])
    ]


def select_release(releases: Iterable[dict], now: datetime, advisories: list[dict], pinned: str) -> Release | None:
    """The highest-versioned stable release with a draw.war asset and no open advisory, published at least MIN_AGE
    ago unless the pinned version has an open advisory itself."""
    urgent = bool(open_advisories(advisories, pinned))
    best: tuple[tuple[int, ...], Release] | None = None
    for rel in releases:
        if rel["draft"] or rel["prerelease"]:
            continue
        if not urgent and now - datetime.fromisoformat(rel["published_at"]) < MIN_AGE:
            continue
        asset = next((a for a in rel["assets"] if a["name"] == ASSET_NAME), None)
        if asset is None:
            continue
        try:
            key = parse_version(rel["tag_name"])
        except ValueError:
            continue
        if open_advisories(advisories, rel["tag_name"]):
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


def fetch(url: str) -> list[dict]:
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as resp:
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
    advisories = fetch(ADVISORIES_URL)
    release = select_release(fetch(RELEASES_URL), datetime.now(UTC), advisories, pin["version"])
    if release is None or not is_newer(release.version, pin["version"]):
        if ghsa := open_advisories(advisories, pin["version"]):
            sys.exit(f"draw.io {pin['version']} is affected by {', '.join(ghsa)} and no fixed release exists yet")
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
