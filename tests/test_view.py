import argparse
import base64
import threading
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

from cartographer import drawio_app, files, svg_export, view, view_browser

MXFILE = (
    '<mxfile><diagram name="p"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="a" value="hello" vertex="1" parent="1"><mxGeometry x="1" y="1" width="8" height="4" as="geometry"/>'
    "</mxCell></root></mxGraphModel></diagram></mxfile>"
)
EDITED = MXFILE.replace("hello", "edited")


@pytest.fixture
def served(tmp_path: Path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("editor")
    monkeypatch.setattr(drawio_app, "ensure", lambda: web)
    drawio = tmp_path / "a.drawio"
    drawio.write_text(MXFILE)
    renders = []

    def fake_export(mxfile: str, url: str) -> str:
        renders.append((mxfile, url))
        return f"<svg>{files.sha256_text(mxfile)}</svg>"

    monkeypatch.setattr(svg_export, "export_svg", fake_export)
    session = view.Session(drawio)
    with drawio_app.serve(session.handler()) as base:
        yield base, session, drawio, renders


def _request(base: str, path: str, *, body: str | None = None, origin: str | None = "", host: str | None = None):
    data = None if body is None else body.encode()
    req = urllib.request.Request(base + path, data=data)
    if data is not None and origin is not None:
        req.add_header("Origin", base if origin == "" else origin)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_host_page_and_file_are_served_and_static_files_still_work(served) -> None:
    base, _, _, _ = served
    status, page = _request(base, f"{view.PREFIX}/")
    assert status == 200 and b"sendBeacon" in page and b"offline=1" in page
    assert _request(base, f"{view.PREFIX}/file") == (200, MXFILE.encode())
    assert _request(base, "/index.html") == (200, b"editor")


def test_save_writes_the_file_atomically_and_regenerates_the_image(served) -> None:
    base, _, drawio, renders = served
    assert _request(base, f"{view.PREFIX}/save", body=EDITED)[0] == 204
    assert drawio.read_text() == EDITED
    assert not list(drawio.parent.glob(".*.tmp"))
    assert renders == [(EDITED, base)]
    assert files.image_path(drawio).read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"


def test_save_expands_a_compressed_diagram_so_the_image_matches_the_file(served) -> None:
    base, _, drawio, _ = served
    model = MXFILE[MXFILE.index("<mxGraphModel>"):MXFILE.index("</diagram>")]
    raw = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = base64.b64encode(raw.compress(model.encode()) + raw.flush()).decode()
    assert _request(base, f"{view.PREFIX}/save", body=f'<mxfile><diagram name="p">{packed}</diagram></mxfile>')[0] == 204
    assert "<mxGraphModel>" in drawio.read_text()


def test_save_rejects_a_foreign_origin_a_missing_origin_and_a_foreign_host(served) -> None:
    base, _, drawio, renders = served
    assert _request(base, f"{view.PREFIX}/save", body=EDITED, origin="http://evil.example")[0] == 403
    assert _request(base, f"{view.PREFIX}/save", body=EDITED, origin=None)[0] == 403
    assert _request(base, f"{view.PREFIX}/save", body=EDITED, host="evil.example")[0] == 403
    assert _request(base, f"{view.PREFIX}/file", host="evil.example")[0] == 403
    assert drawio.read_text() == MXFILE and renders == []


def test_save_rejects_something_that_is_not_a_drawio_file(served) -> None:
    base, _, drawio, _ = served
    assert _request(base, f"{view.PREFIX}/save", body="<html/>")[0] == 400
    assert _request(base, f"{view.PREFIX}/save", body="not xml")[0] == 400
    assert drawio.read_text() == MXFILE


def test_other_paths_are_rejected(served) -> None:
    base, _, drawio, _ = served
    assert _request(base, f"{view.PREFIX}/other")[0] == 404
    assert _request(base, f"{view.PREFIX}/other", body="x")[0] == 404
    assert _request(base, "/index.html", body="x")[0] == 404
    assert drawio.read_text() == MXFILE


def test_close_signals_the_session_and_a_foreign_close_does_not(served) -> None:
    base, session, _, _ = served
    assert _request(base, f"{view.PREFIX}/close", body="close", origin="http://evil.example")[0] == 403
    assert not session.closed.is_set()
    assert _request(base, f"{view.PREFIX}/close", body="close")[0] == 204
    assert session.closed.wait(2)


def test_run_serves_until_close_then_stops(tmp_path: Path, monkeypatch, capsys) -> None:
    web = tmp_path / "web"
    web.mkdir()
    monkeypatch.setattr(drawio_app, "ensure", lambda: web)
    drawio = tmp_path / "a.drawio"
    drawio.write_text(MXFILE)
    opened = []

    def fake_open(url: str) -> view_browser.Launch:
        opened.append(url)
        base = url.removesuffix(f"{view.PREFIX}/")
        threading.Timer(0.2, lambda: _request(base, f"{view.PREFIX}/close", body="c")).start()
        return view_browser.Launch(None, None, "")

    monkeypatch.setattr(view_browser, "launch", fake_open)
    assert view.run(_args(drawio)) == 0
    out = capsys.readouterr().out
    assert opened[0] in out and "Editing a.drawio. Save in the editor writes the file. Close the window to stop." in out
    with pytest.raises(OSError):
        urllib.request.urlopen(opened[0], timeout=2)


def _args(drawio: Path, url: str | None = None):
    return argparse.Namespace(file=str(drawio), drawio_url=url)


def test_run_without_the_app_and_without_a_url_prints_the_read_only_note(tmp_path: Path, monkeypatch, capsys) -> None:
    def refuse():
        raise drawio_app.DrawioError("could not download draw.io")

    monkeypatch.setattr(drawio_app, "ensure", refuse)
    drawio = tmp_path / "a.drawio"
    drawio.write_text(MXFILE)
    assert view.run(_args(drawio)) == 2
    err = capsys.readouterr().err
    assert "could not download" in err and view.VIEW_NOTE in err


def test_run_falls_back_to_the_lightbox_when_a_url_was_given(tmp_path: Path, monkeypatch, capsys) -> None:
    def refuse():
        raise drawio_app.DrawioError("blocked")

    opened = []
    monkeypatch.setattr(drawio_app, "ensure", refuse)
    monkeypatch.setattr(view.snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(view.webbrowser, "open", opened.append)
    drawio = tmp_path / "a.drawio"
    drawio.write_text(MXFILE)
    assert view.run(_args(drawio, "http://localhost:8080")) == 0
    assert opened[0].startswith("http://localhost:8080/?lightbox=1") and capsys.readouterr().out.strip() == view.VIEW_NOTE
    assert view.run(_args(tmp_path / "a.svg")) == 2
