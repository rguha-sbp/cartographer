"""`cartographer view`: edit a .drawio in the bundled draw.io, served on 127.0.0.1 until the tab is closed."""

import argparse
import base64
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import zlib
from pathlib import Path
from xml.etree import ElementTree

from cartographer import drawio_app, snapshot, svg_export
from cartographer.drawio_app import LOOPBACK, StaticHandler

PREFIX = "/_cartographer"
MAX_SAVE_BYTES = 64 << 20
OPEN_NOTE = "Editing {name}. Save in the editor writes the file. Close the tab to stop."
VIEW_NOTE = ("Read-only view. To edit, open the .drawio in your local draw.io (never a public host) "
             "and run `cartographer image` after.")
HOST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>cartographer</title>
<style>html,body,iframe{margin:0;width:100%;height:100%;border:0}</style></head>
<body><iframe id="editor" src="/index.html?__EMBED__&noExitBtn=1"></iframe>
<script>
const PREFIX = "__PREFIX__";
const frame = document.getElementById("editor");
const send = msg => frame.contentWindow.postMessage(JSON.stringify(msg), location.origin);
let closed = false;
const close = () => {
  if (!closed) { closed = true; navigator.sendBeacon(PREFIX + "/close", "close"); }
};
addEventListener("message", async e => {
  if (e.source !== frame.contentWindow) return;
  const msg = JSON.parse(e.data);
  if (msg.event === "init") {
    send({action: "load", xml: await (await fetch(PREFIX + "/file")).text()});
  } else if (msg.event === "save") {
    const res = await fetch(PREFIX + "/save", {method: "POST", body: msg.xml});
    send(res.ok ? {action: "status", modified: false} : {action: "status", message: "Save failed", modified: true});
  } else if (msg.event === "exit") {
    close();
    window.close();
  }
});
addEventListener("pagehide", close);
</script></body></html>
""".replace("__EMBED__", drawio_app.EMBED_QUERY).replace("__PREFIX__", PREFIX)


def plain_mxfile(xml: str) -> str:
    """The saved file with any compressed diagram expanded, so the image render can read its cells."""
    root = ElementTree.fromstring(xml)
    if root.tag != "mxfile":
        raise ValueError("not an mxfile")
    changed = False
    for diagram in root.iter("diagram"):
        if len(diagram) == 0 and (diagram.text or "").strip():
            model = urllib.parse.unquote(zlib.decompress(base64.b64decode(diagram.text), -15).decode())
            diagram.append(ElementTree.fromstring(model))
            diagram.text = None
            changed = True
    return ElementTree.tostring(root, encoding="unicode") if changed else xml


class Session:
    """The one file being edited and the signal that the tab is gone."""

    def __init__(self, drawio: Path) -> None:
        self.drawio = drawio
        self.closed = threading.Event()
        self.busy = threading.Lock()

    def write(self, xml: str) -> None:
        tmp = self.drawio.with_name(f".{self.drawio.name}.tmp")
        tmp.write_text(xml)
        os.replace(tmp, self.drawio)

    def handler(self) -> type[StaticHandler]:
        session = self

        class Handler(StaticHandler):
            def _own_origin(self) -> str:
                return f"http://{LOOPBACK}:{self.server.server_address[1]}"

            def _reply(self, code: int, body: bytes = b"", content_type: str = "text/plain") -> None:
                self.send_response(code)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _allowed(self, post: bool) -> bool:
                own = self._own_origin()
                host_ok = self.headers.get("Host") == own.removeprefix("http://")
                return host_ok and (not post or self.headers.get("Origin") == own)

            def do_GET(self) -> None:
                if not self.path.startswith(PREFIX):
                    return super().do_GET()
                if not self._allowed(post=False):
                    return self._reply(403)
                if self.path == f"{PREFIX}/":
                    return self._reply(200, HOST_PAGE.encode(), "text/html")
                if self.path == f"{PREFIX}/file":
                    return self._reply(200, session.drawio.read_bytes(), "application/xml")
                self._reply(404)

            def do_POST(self) -> None:
                if self.path not in (f"{PREFIX}/save", f"{PREFIX}/close"):
                    return self._reply(404)
                if not self._allowed(post=True):
                    return self._reply(403)
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_SAVE_BYTES:
                    return self._reply(413)
                body = self.rfile.read(length).decode(errors="replace")
                if self.path == f"{PREFIX}/close":
                    self._reply(204)
                    session.closed.set()
                    return
                try:
                    xml = plain_mxfile(body)
                except (ValueError, zlib.error, ElementTree.ParseError):
                    return self._reply(400, b"not a draw.io file")
                with session.busy:
                    session.write(xml)
                    self._reply(204)
                    try:
                        svg_export.write_image(session.drawio, self._own_origin(), xml)
                    except (svg_export.SvgError, snapshot.SnapshotError) as err:
                        print(f"saved, but the image was not regenerated: {err}", file=sys.stderr)

        return Handler


def open_browser(url: str) -> None:
    if sys.platform == "darwin" and Path(snapshot.CHROME_MAC).exists():
        subprocess.run(["open", "-a", "Google Chrome", url], check=False)
    else:
        webbrowser.open(url)


def _lightbox(drawio: Path, url: str) -> int:
    webbrowser.open(snapshot.viewer_url(url, drawio.read_text()))
    print(VIEW_NOTE)
    return 0


def _edit(drawio: Path) -> None:
    session = Session(drawio)
    with drawio_app.serve(session.handler()) as base:
        url = f"{base}{PREFIX}/"
        print(url)
        open_browser(url)
        print(OPEN_NOTE.format(name=drawio.name))
        try:
            session.closed.wait()
        except KeyboardInterrupt:
            pass
        with session.busy:
            pass


def run(args: argparse.Namespace) -> int:
    if args.file.suffix != ".drawio":
        print("view takes a .drawio file", file=sys.stderr)
        return 2
    try:
        drawio_app.ensure()
    except drawio_app.DrawioError as err:
        print(err, file=sys.stderr)
        if args.drawio_url is None:
            print(VIEW_NOTE, file=sys.stderr)
            return 2
        url = args.drawio_url.rstrip("/")
        if not snapshot.drawio_up(url):
            print(snapshot.DRAWIO_DOWN, file=sys.stderr)
            return 2
        return _lightbox(args.file, url)
    _edit(args.file.resolve())
    return 0
