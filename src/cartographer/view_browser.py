"""Open the editor in its own Chrome app window with a throwaway profile."""

import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path
from typing import NamedTuple

from cartographer import snapshot

CHROME_EXIT_TIMEOUT_SECONDS = 5
NO_CHROME = "No Chrome found: opened your default browser."


class Launch(NamedTuple):
    process: subprocess.Popen | None
    profile: Path | None
    note: str


def chrome_argv(chrome: str, profile: Path, url: str) -> list[str]:
    return [
        chrome, f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check", f"--app={url}",
    ]


def launch(url: str) -> Launch:
    try:
        chrome = snapshot.find_chrome()
    except snapshot.SnapshotError:
        webbrowser.open(url)
        return Launch(None, None, NO_CHROME)
    profile = Path(tempfile.mkdtemp(prefix="cartographer-chrome-"))
    process = subprocess.Popen(chrome_argv(chrome, profile, url), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return Launch(process, profile, "")


def cleanup(opened: Launch) -> None:
    if opened.process is not None and opened.process.poll() is None:
        opened.process.terminate()
        _wait_for_exit(opened.process)
    if opened.profile is not None:
        shutil.rmtree(opened.profile, ignore_errors=True)


def _wait_for_exit(process: subprocess.Popen) -> None:
    """Chrome rewrites Local State while quitting, so the profile can only go once it has exited."""
    try:
        process.wait(timeout=CHROME_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=CHROME_EXIT_TIMEOUT_SECONDS)
