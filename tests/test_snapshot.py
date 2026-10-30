import base64
import subprocess
import urllib.parse
import zlib
from pathlib import Path

import pytest

from cartographer import snapshot

XML = """<mxfile><diagram><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="g" parent="1" vertex="1"><mxGeometry x="100" y="50" width="400" height="300" as="geometry"/></mxCell>
<mxCell id="n" parent="g" vertex="1"><mxGeometry x="20" y="30" width="60" height="60" as="geometry"/></mxCell>
<mxCell id="e" parent="1" edge="1" source="g" target="n"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def test_viewer_url_round_trips():
    url = snapshot.viewer_url("http://localhost:8080", XML)
    prefix = "http://localhost:8080/?lightbox=1&nav=0&toolbar=0#R"
    assert url.startswith(prefix)
    raw = base64.b64decode(urllib.parse.unquote(url[len(prefix):]))
    inflated = zlib.decompress(raw, -15).decode()
    assert urllib.parse.unquote(inflated) == XML


def test_extent_resolves_parents_and_adds_margin():
    # vertices span x 100..500, y 50..350; margin 120 on each side
    assert snapshot.window_size(XML) == (400 + 240, 300 + 240)


def test_extent_child_outside_parent_counts():
    xml = XML.replace('x="20" y="30"', 'x="600" y="500"')
    # child absolute 700..760, 550..610 -> bbox x 100..760, y 50..610
    assert snapshot.window_size(xml) == (660 + 240, 560 + 240)


def test_tile_rects_2x2_overlap():
    rects = snapshot.tile_rects(1000, 500, 2, 2)
    assert len(rects) == 4
    r0c0, r0c1, r1c0, r1c1 = rects
    assert (r0c0.x, r0c0.y) == (0, 0)
    assert r0c0.w == 550 and r0c0.h == 275
    assert r0c1.x + r0c1.w == 1000 and r1c1.y + r1c1.h == 500
    assert r0c1.x == 450 and r1c0.y == 225
    assert (r1c1.row, r1c1.col) == (1, 1)


def test_parse_tiles():
    assert snapshot.parse_tiles("3x2") == (2, 3)
    with pytest.raises(ValueError):
        snapshot.parse_tiles("two")


def test_drawio_not_running_exits_2(tmp_path, monkeypatch, capsys):
    d = tmp_path / "a.drawio"
    d.write_text(XML)
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    monkeypatch.setattr(snapshot.subprocess, "run", lambda *a, **k: pytest.fail("chrome must not run"))
    assert snapshot.main([str(d), "-o", str(tmp_path / "out"), "--drawio-url", "http://localhost:8080"]) == 2
    assert "no draw.io answers" in capsys.readouterr().err


def test_main_writes_full_and_tiles(tmp_path, monkeypatch, capsys, bundled_app):
    d = tmp_path / "a.drawio"
    d.write_text(XML)
    out = tmp_path / "out"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        shot = next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]
        Path(shot).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    assert snapshot.main([str(d), "-o", str(out)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == str(out / "a.png")
    assert [Path(p).name for p in lines[1:]] == [
        "a.tile-r0c0.png", "a.tile-r0c1.png", "a.tile-r1c0.png", "a.tile-r1c1.png"]
    assert len(calls) == 5
    assert "--window-size=640,540" in calls[0]
    assert "--force-device-scale-factor=2" in calls[0]
    assert f"--host-resolver-rules={snapshot.OFFLINE_RULES}" in calls[0]
    assert calls[0][-1].startswith(bundled_app)


def test_find_chrome_missing(monkeypatch):
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: False)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    with pytest.raises(snapshot.SnapshotError, match="Chrome"):
        snapshot.find_chrome()
