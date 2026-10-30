"""The pinned draw.io web app: download once, check, unpack, and serve it on 127.0.0.1 while a command needs it."""

import hashlib
import json
import os
import shutil
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

_PIN = json.loads(Path(__file__).with_name("drawio_pin.json").read_text(encoding="utf-8"))
NAME = "draw.io"
VERSION: str = _PIN["version"]
LICENCE: str = _PIN["licence"]
URL: str = _PIN["url"]
SHA256: str = _PIN["sha256"]
LOOPBACK = "127.0.0.1"
EMBED_QUERY = "embed=1&proto=json&spin=1&offline=1&stealth=1"
DOWNLOAD_TIMEOUT_S = 60
CHUNK = 1 << 20
MARKER = ".complete"
# Keeps the page on its own origin: no request, frame, form or worker may reach another host.
CSP = (
    "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'self'; img-src 'self' data: blob:; "
    "frame-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'"
)


class DrawioError(Exception):
    pass


def app_dir() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "cartographer" / "drawio" / VERSION


def _download(target: Path) -> None:
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(URL, timeout=DOWNLOAD_TIMEOUT_S) as resp, target.open("wb") as out:
            while chunk := resp.read(CHUNK):
                digest.update(chunk)
                out.write(chunk)
    except (urllib.error.URLError, OSError) as err:
        raise DrawioError(f"could not download {NAME} {VERSION} from {URL}: {err}") from err
    if digest.hexdigest() != SHA256:
        target.unlink(missing_ok=True)
        raise DrawioError(f"{NAME} {VERSION} download does not match the pinned sha256 {SHA256}; it was deleted")


def _unpack(war: Path, dest: Path) -> None:
    with zipfile.ZipFile(war) as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise DrawioError(f"{NAME} archive has an unsafe path: {name}")
        archive.extractall(dest)


def ensure() -> Path:
    """The unpacked web app, downloading and unpacking it on first use."""
    root = app_dir()
    web = root / "web"
    if (root / MARKER).is_file():
        return web
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    war = root / "draw.war"
    _download(war)
    try:
        _unpack(war, web)
    except (DrawioError, zipfile.BadZipFile):
        shutil.rmtree(root, ignore_errors=True)
        raise
    war.unlink()
    (root / MARKER).touch()
    return web


class StaticHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve(handler: type[StaticHandler] = StaticHandler) -> Iterator[str]:
    """Serve the app on a free 127.0.0.1 port; `handler` may add routes ahead of the static files."""
    web = ensure()
    server = ThreadingHTTPServer((LOOPBACK, 0), partial(handler, directory=str(web)))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{LOOPBACK}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def drawio_at(url: str | None) -> Iterator[str]:
    """`url` when the caller points at their own draw.io, else the bundled app for the length of the block."""
    if url is not None:
        yield url.rstrip("/")
        return
    with serve() as base:
        yield base
